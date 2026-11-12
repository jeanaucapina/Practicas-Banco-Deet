"""Panel del laboratorio en el PC: una sola pagina con todo el tablero.

    http://localhost:8090      (solo desde este PC: el puerto va a 127.0.0.1)

Corre en un contenedor (docker-compose: panel) con el socket de Docker y el
repo montado en /tablero. De donde saca cada cosa:

  pasarela   cliente TCP como las gafas (172.30.99.1:7170): estado de los
             equipos, cables y la captura de tramas; reenvia las ordenes que
             se dan desde la pagina (pulsadores, potenciometro, WiFi)
  MQTT       suscrito a "#" en el broker por la red de gestion (172.30.99.50),
             asi no aparece en la captura de tab-lan
  S7-1200    el fichero que vuelca s7.py (run/panel/s7.json), sin trafico S7
  Docker     `docker ps` para saber que contenedores corren; `docker exec` para
             compilar el .ino / .st que se sube desde la pagina (lo mismo que
             `.\\lab.ps1 subir`) y `docker logs` para el monitor serie

Sin dependencias fuera de la biblioteca estandar (y mqtt_mini del tablero).
"""

import asyncio
import base64
import binascii
import json
import os
import hashlib
import hmac
import html
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

RAIZ = "/tablero"
sys.path.insert(0, os.path.join(RAIZ, "dispositivos"))
from mqtt_mini import ClienteMQTT  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verificador  # noqa: E402
import hmi_stone  # noqa: E402

PASARELA = os.environ.get("PANEL_PASARELA", "172.30.99.1:7170")
BROKER = os.environ.get("PANEL_BROKER", "172.30.99.50")
PUERTO = int(os.environ.get("PANEL_PUERTO", "8090"))
AQUI = os.path.dirname(os.path.abspath(__file__))

EQUIPOS_INO = {"t1.controllino": "tab1-controllino", "t2.controllino": "tab2-controllino",
               "t1.esp32plc": "tab1-esp32plc", "t2.esp32plc": "tab2-esp32plc"}
EQUIPOS_ST = {"t1.openplc": "tab1-openplc", "t2.openplc": "tab2-openplc"}
GUIAS = {
    "arduino": "ejemplos_arduino/LEEME.md",
    "openplc": "openplc/LEEME.md",
    "tablero": "README.md",
    "practicas": "PRACTICAS.md",
}

HMIS = {n: hmi_stone.HMI(n, os.path.join(RAIZ, "run", "hmi")) for n in (1, 2)}
estado = {"pasarela": None, "pasarela_ok": False, "contenedores": {}, "t_contenedores": 0}
mqtt_msgs = deque(maxlen=40)
# Ultimo mensaje entero de cada tema (los eventos de ChirpStack pasan de 1 kB y llegan
# cada 10 min: el autocorrector los busca aqui, no en la cola corta de la pagina).
mqtt_ultimo = {}
# Ascendentes LoRaWAN que ChirpStack publica (application/<app>/device/<deveui>/event/up), ya
# desmenuzados: alimentan el panel «Asi debe salir» de la L10 (docente).
uplinks = deque(maxlen=30)
RX_UP = re.compile(r"^application/([^/]+)/device/([0-9a-f]{16})/event/up$")
cerrojo = threading.Lock()
_sock = None
_cerrojo_envio = threading.Lock()


# ── Pasarela ────────────────────────────────────────────────────────────────
def hilo_pasarela():
    global _sock
    host, puerto = PASARELA.split(":")
    while True:
        try:
            s = socket.create_connection((host, int(puerto)), timeout=3)
            s.settimeout(5)
            _sock = s
            f = s.makefile("r", encoding="utf-8")
            while True:
                linea = f.readline()
                if not linea:
                    break
                try:
                    d = json.loads(linea)
                    if d.get("t") == "estado":
                        with cerrojo:
                            estado["pasarela"] = d
                            estado["pasarela_ok"] = True
                        _toques_hmi(d.get("hmi_toques") or [])
                except (ValueError, TypeError, AttributeError, KeyError):
                    continue             # una linea rara no debe matar este hilo ni cortar la conexion
        except OSError:
            pass
        _sock = None
        try:
            s.close()
        except (OSError, NameError, UnboundLocalError):
            pass
        with cerrojo:
            estado["pasarela_ok"] = False
        time.sleep(2)


# ── HMI del alumno en el tablero 3D ─────────────────────────────────────────
# La pantalla STONE que diseña el alumno vive aqui (HMIS). Para que se vea en la HMI del
# tablero 3D se publica en la pasarela (pagina actual, valores, textos, series), y los
# toques que hace el alumno en el 3D vuelven numerados en el estado de la pasarela.
_hmi_seq_visto = None


def _toques_hmi(toques: list):
    global _hmi_seq_visto
    if _hmi_seq_visto is None:                 # al (re)conectar no se repiten los viejos
        _hmi_seq_visto = max((int(t.get("seq", 0)) for t in toques), default=0)
        return
    for t in toques:
        if int(t.get("seq", 0)) > _hmi_seq_visto:
            _hmi_seq_visto = int(t["seq"])
            h = HMIS.get(int(t.get("n", 1)))
            if h is not None:
                h.toque(str(t.get("widget", "")), str(t.get("ev", "")), t.get("v"))


def _hmi_para_3d(h) -> dict:
    e = h.estado()
    p = e.get("proyecto") or {}
    paginas = p.get("paginas") or []
    if not paginas or not any(pg.get("widgets") for pg in paginas):
        return {}
    pg = paginas[min(e.get("pagina", 0), len(paginas) - 1)]
    return {"pagina": pg["nombre"], "widgets": pg["widgets"], "valores": e["valores"],
            "textos": e["textos"], "series": {k: v[-60:] for k, v in e["series"].items()}}


def hilo_hmi_3d():
    ultimo, t_envio = {}, {}
    while True:
        for n, h in HMIS.items():
            try:
                e = _hmi_para_3d(h)
            except Exception:
                e = {}
            txt = json.dumps(e, sort_keys=True)
            if txt != ultimo.get(n) or time.time() - t_envio.get(n, 0) > 3:
                if a_pasarela({"t": "hmi", "n": n, "e": e}):
                    ultimo[n], t_envio[n] = txt, time.time()
        time.sleep(0.25)


def a_pasarela(d: dict) -> bool:
    s = _sock
    if s is None:
        return False
    try:
        with _cerrojo_envio:         # ThreadingHTTPServer: dos hilos no deben mezclar lineas
            s.sendall((json.dumps(d) + "\n").encode())
        return True
    except OSError:
        return False


# ── MQTT ────────────────────────────────────────────────────────────────────
def _anotar_uplink(tema: str, txt: str):
    """Evento `up` de ChirpStack v4 -> fila de la tabla de ascendentes (lo que ve el docente)."""
    try:
        d = json.loads(txt)
        m = RX_UP.match(tema)
        rx = (d.get("rxInfo") or [{}])[0]
        lora = ((d.get("txInfo") or {}).get("modulation") or {}).get("lora") or {}
        obj = d.get("object") or {}
        uplinks.append({
            "hora": time.strftime("%H:%M:%S"), "t": time.time(), "dev_eui": m.group(2), "app": m.group(1),
            "fcnt": d.get("fCnt"), "fport": d.get("fPort"), "confirmado": bool(d.get("confirmed")),
            "frec_mhz": round((d.get("txInfo") or {}).get("frequency", 0) / 1e6, 1) or None,
            "canal": rx.get("channel"), "sf": lora.get("spreadingFactor"), "bw": lora.get("bandwidth"),
            "dr": d.get("dr"), "rssi": rx.get("rssi"), "snr": rx.get("snr"),
            "nombre": (d.get("deviceInfo") or {}).get("deviceName"),
            "temperatura": obj.get("temperatura"), "nivel": obj.get("nivel"),
            "alarma_temp": obj.get("alarma_temp"), "alarma_nivel": obj.get("alarma_nivel"),
            "ts_nodo": obj.get("ts_nodo"), "decodificado": bool(obj), "bytes": len(base64.b64decode(d.get("data") or ""))})
    except (ValueError, TypeError, AttributeError, binascii.Error):
        pass


def hilo_mqtt():
    async def bucle():
        while True:
            c = ClienteMQTT("panel-pc")
            def al_mensaje(tema, carga):
                txt = carga.decode("utf-8", "replace")
                mqtt_msgs.append({"hora": time.strftime("%H:%M:%S"), "tema": tema, "carga": txt[:200]})
                mqtt_ultimo[tema] = {"hora": time.strftime("%H:%M:%S"), "t": time.time(), "tema": tema,
                                     "carga": txt[:8000]}
                if RX_UP.match(tema):
                    _anotar_uplink(tema, txt)
                if len(mqtt_ultimo) > 400:
                    for k in sorted(mqtt_ultimo, key=lambda k: mqtt_ultimo[k]["t"])[:100]:
                        mqtt_ultimo.pop(k, None)
            c.al_mensaje = al_mensaje
            if await c.conectar(BROKER, timeout=2.0):
                c.suscribir("#")
                while c.conectado:
                    await asyncio.sleep(1)
            await asyncio.sleep(3)
    asyncio.run(bucle())


# ── Docker ──────────────────────────────────────────────────────────────────
def docker(*args, timeout=120):
    try:
        r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "docker no esta instalado o no esta en el PATH"
    except subprocess.TimeoutExpired:
        return 124, "docker %s no contesto en %d s" % (args[0] if args else "", timeout)
    return r.returncode, (r.stdout + r.stderr)


def contenedores():
    with cerrojo:
        if time.time() - estado["t_contenedores"] < 3:
            return estado["contenedores"]
    rc, out = docker("ps", "-a", "--filter", "name=tab", "--format", "{{.Names}}|{{.State}}|{{.Status}}", timeout=10)
    c = {}
    for l in out.splitlines():
        p = l.split("|")
        if len(p) == 3:
            c[p[0]] = {"estado": p[1], "detalle": p[2]}
    with cerrojo:
        estado["contenedores"], estado["t_contenedores"] = c, time.time()
    return c


_cerrojos_subida = {}
subidos = {}          # equipo -> {nombre, sha256, hora} del ultimo .ino subido desde aqui


def usb_conectado(equipo: str) -> bool:
    """Como en el banco real, un PLC solo se programa (y su monitor serie solo se
    ve) con el cable USB del PC enchufado: USB-B del Controllino, micro USB del ESP32."""
    with cerrojo:
        eq = ((estado["pasarela"] or {}).get("equipos") or {}).get(equipo) or {}
    return bool(eq.get("usb"))


SIN_USB = ("No hay cable USB entre el PC y %s. En el 3D, cablea el puerto USB del PC al "
           "%s (como en el banco: sin cable el IDE no ve la placa).")
NOMBRE_USB = {"controllino": "USB-B del Controllino (al lado del Ethernet)",
              "esp32plc": "micro USB del ESP32 PLC"}


def subir(equipo: str, nombre: str, datos: bytes, sin_usb: bool = False):
    """Lo mismo que `.\\lab.ps1 subir`: compila y, si va bien, reinicia."""
    nombre = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(nombre or ""))
    with _cerrojos_subida.setdefault(equipo, threading.Lock()):   # dos subidas a la vez se pisarian la carpeta fuente
        return _subir(equipo, nombre, datos, sin_usb)


def _subir(equipo: str, nombre: str, datos: bytes, sin_usb: bool):
    if equipo in EQUIPOS_INO:
        if not nombre.endswith(".ino"):
            return False, "Para %s hace falta un archivo .ino" % equipo
        if not sin_usb and not usb_conectado(equipo):      # sin_usb: el montaje de una practica deja listo un PLC de produccion
            return False, SIN_USB % (equipo, NOMBRE_USB[equipo.split(".")[1]])
        c = EQUIPOS_INO[equipo]
        fuente = os.path.join(RAIZ, "programas", equipo, "fuente")
        os.makedirs(fuente, exist_ok=True)
        for f in os.listdir(fuente):
            os.remove(os.path.join(fuente, f))
        with open(os.path.join(fuente, nombre), "wb") as f:
            f.write(datos)
        rc, out = docker("exec", c, "python", "compilar.py")
        if rc != 0:
            return False, out + "\nNo compila: el equipo sigue con el programa anterior."
        docker("restart", c, timeout=30)
        subidos[equipo] = {"nombre": nombre, "sha256": hashlib.sha256(datos).hexdigest(),
                           "hora": time.strftime("%Y-%m-%d %H:%M:%S")}
        return True, out + "\nSubido: %s corre %s." % (equipo, nombre)
    if equipo in EQUIPOS_ST:
        if not nombre.endswith(".st"):
            return False, "Para %s hace falta un .st (OpenPLC Editor > Generar programa para OpenPLC Runtime)" % equipo
        c = EQUIPOS_ST[equipo]
        if contenedores().get(c, {}).get("estado") != "running":
            return False, "OpenPLC no esta en marcha: en PowerShell, .\\lab.ps1 openplc"
        tmp = "/tmp/%s_%s" % (secrets.token_hex(4), nombre)      # nombre unico: dos subidas no se pisan
        # El editor nuevo (2024) mete en el .st comentarios "(*DBG: ...*)" con el
        # codigo del depurador; el runtime de la imagen (2019) no los entiende y
        # falla con "unknown syntax error". Se quitan: no cambian el programa.
        salto = bytes([10])
        limpio = salto.join(l for l in datos.split(salto) if not l.lstrip().startswith(b"(*DBG:"))
        with open(tmp, "wb") as f:
            f.write(limpio)
        try:
            rc, out = docker("cp", tmp, "%s:/root/OpenPLC_v3/webserver/st_files/%s" % (c, nombre))
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if rc == 0:
            rc, out = docker("exec", c, "python2", "/openplc/cargar.py", nombre)
        if rc != 0:
            return False, out + "\nNo compila."
        docker("restart", c, timeout=30)
        return True, out[-1500:] + "\nCargado: OpenPLC en RUN con %s." % nombre
    return False, "Equipo desconocido: %s" % equipo


def cargar_binario(equipo: str, ruta: str):
    """Pone un programa YA COMPILADO (del paquete de alumnos) en el equipo y lo reinicia, sin el .ino."""
    if equipo not in EQUIPOS_INO:
        return False, "Equipo desconocido: %s" % equipo
    destino = os.path.join(RAIZ, "programas", equipo)
    os.makedirs(destino, exist_ok=True)
    with open(ruta, "rb") as f, open(os.path.join(destino, "programa"), "wb") as g:
        g.write(f.read())
    os.chmod(os.path.join(destino, "programa"), 0o755)
    with open(os.path.join(destino, "nombre"), "w") as g:
        g.write(os.path.basename(ruta))
    docker("restart", EQUIPOS_INO[equipo], timeout=30)
    return True, "Cargado %s en %s" % (os.path.basename(ruta), equipo)


def fabrica(equipo: str):
    if equipo not in EQUIPOS_INO:
        return False, "Solo para Controllino / ESP32"
    if not usb_conectado(equipo):
        return False, SIN_USB % (equipo, NOMBRE_USB[equipo.split(".")[1]])
    _borrar_programa(equipo)
    return True, "%s vuelve al programa de fabrica." % equipo


def _borrar_programa(equipo: str):
    """Quita el .ino cargado y reinicia el equipo: vuelve la imitacion de fabrica."""
    d = os.path.join(RAIZ, "programas", equipo)
    for raiz, dirs, fich in os.walk(d, topdown=False):
        for f in fich:
            os.remove(os.path.join(raiz, f))
        for x in dirs:
            os.rmdir(os.path.join(raiz, x))
    if os.path.isdir(d):
        os.rmdir(d)
    docker("restart", EQUIPOS_INO[equipo], timeout=30)


def _todo_a_fabrica() -> list:
    """«Preparar el tablero» deja los cuatro PLC con el programa de fabrica. Un .ino de
    otra practica (o de otro grupo) cargado hacia fallar la siguiente (U2 tras L2). Es el
    banco quien lo hace, no el alumno: no hace falta el cable USB. Devuelve los equipos
    que se reiniciaron y espera (hasta 20 s) a que vuelvan a informar."""
    with cerrojo:
        eqs = ((estado["pasarela"] or {}).get("equipos") or {})
    con_programa = [e for e in EQUIPOS_INO
                    if (eqs.get(e) or {}).get("modo") == 9 or os.path.isdir(os.path.join(RAIZ, "programas", e))]
    for e in con_programa:
        _borrar_programa(e)
    t0 = time.time()
    while con_programa and time.time() - t0 < 20:
        time.sleep(1.0)
        with cerrojo:
            eqs = ((estado["pasarela"] or {}).get("equipos") or {})
        if all((eqs.get(e) or {}).get("encendido") and (eqs.get(e) or {}).get("modo") != 9 for e in con_programa):
            break
    return con_programa


PROYECTOS = os.path.join(RAIZ, "openplc", "proyectos")


def proyectos():
    """Programas listos para OpenPLC en la carpeta del editor: el ultimo que
    genero cada proyecto (boton naranja -> <proyecto>/build/generated_plc.st)
    y cualquier .st suelto que se haya guardado alli."""
    out = []
    for raiz, dirs, fich in os.walk(PROYECTOS):
        for f in fich:
            ruta = os.path.join(raiz, f)
            rel = os.path.relpath(ruta, PROYECTOS).replace(os.sep, "/")
            if f == "generated_plc.st" and os.path.basename(raiz) == "build":
                nombre = os.path.basename(os.path.dirname(raiz))
            elif f.endswith(".st") and "/build/" not in "/" + rel:
                nombre = f[:-3]
            else:
                continue
            out.append({"nombre": nombre, "archivo": rel, "t": os.path.getmtime(ruta),
                        "hora": time.strftime("%d/%m %H:%M", time.localtime(os.path.getmtime(ruta)))})
    return sorted(out, key=lambda x: -x["t"])[:20]


def cargar(rel: str, equipo: str):
    ruta = os.path.realpath(os.path.join(PROYECTOS, rel))
    if not ruta.startswith(os.path.realpath(PROYECTOS) + os.sep) or not ruta.endswith(".st") or not os.path.isfile(ruta):
        return False, "Archivo no valido"
    partes = rel.replace("\\", "/").split("/")
    nombre = partes[-3] + ".st" if rel.endswith("build/generated_plc.st") and len(partes) >= 3 else os.path.basename(rel)
    with open(ruta, "rb") as f:
        return subir(equipo, nombre, f.read())


# ── Modo docente ─────────────────────────────────────────────────────────────
# Los ejemplos que RESUELVEN una practica (los que nombra el catalogo o la practica como
# solucion) solo los ve y sube el docente, tras dar su clave en el portal. La clave se
# guarda solo como SHA-256 en panel/clave_docente.sha256, que NO va en el paquete de los
# alumnos (.gitattributes export-ignore), igual que esos ejemplos: sin ese archivo no hay
# modo docente. `.\lab.ps1 clave-docente` la cambia.
# PANEL_CLAVE_ARCHIVO solo lo usan las pruebas (un hash temporal): en el banco no se define.
CLAVE_DOCENTE = os.environ.get("PANEL_CLAVE_ARCHIVO") or os.path.join(AQUI, "clave_docente.sha256")
# La sesion del docente sobrevive a un reinicio del panel: tablero/run/docente_sesiones.json guarda el
# SHA-256 de cada ficha (nunca la clave ni su hash) con su caducidad. Si la clave cambia (el archivo
# de la clave es mas nuevo que la sesion) las sesiones dejan de valer.
SESIONES_DOCENTE = os.environ.get("PANEL_SESIONES_ARCHIVO") or os.path.join(RAIZ, "run", "docente_sesiones.json")
SESION_DOCENTE_S = 24 * 3600
_tokens_docente = {}          # sha256(ficha) -> {"hasta": epoch, "desde": epoch}
_cerrojo_sesiones = threading.Lock()
_cerrojo_intentos = threading.Lock()   # serializa los intentos de clave (frena la fuerza bruta)


def _huella(ficha: str) -> str:
    return hashlib.sha256(ficha.encode("utf-8")).hexdigest()


def _guardar_sesiones():
    try:
        with _cerrojo_sesiones:      # varios hilos HTTP: sin esto json.dump ve el dict cambiar
            os.makedirs(os.path.dirname(SESIONES_DOCENTE), exist_ok=True)
            tmp = SESIONES_DOCENTE + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(dict(_tokens_docente), f)
            os.replace(tmp, SESIONES_DOCENTE)
    except (OSError, RuntimeError):
        pass


def _cargar_sesiones():
    try:
        with open(SESIONES_DOCENTE, encoding="utf-8") as f:
            d = json.load(f)
        clave_t = os.path.getmtime(CLAVE_DOCENTE)
    except (OSError, ValueError):
        return
    ahora = time.time()
    for h, v in (d if isinstance(d, dict) else {}).items():
        if isinstance(v, dict) and v.get("hasta", 0) > ahora and v.get("desde", 0) >= clave_t:
            _tokens_docente[h] = v


def _ficha_valida(ficha: str) -> bool:
    v = _tokens_docente.get(_huella(ficha))
    if v is None:
        return False
    if v["hasta"] < time.time():
        _tokens_docente.pop(_huella(ficha), None)
        return False
    return True


def soluciones() -> set:
    sol = set()
    for e in catalogo():
        sol.update(e.get("ejemplos", []))
        p = leer_practica(e.get("id", "")) or {}
        if p.get("solucion_ejemplo"):
            sol.add(p["solucion_ejemplo"])
        sol.update(x[1] for x in p.get("solucion_equipos", []) if len(x) > 1)
    return sol


def docente_disponible() -> bool:
    return os.path.isfile(CLAVE_DOCENTE)


def clave_valida(clave: str) -> bool:
    try:
        with open(CLAVE_DOCENTE, encoding="utf-8") as f:
            esperado = f.read().split()[0].strip().lower()
    except (OSError, IndexError):
        return False
    return hmac.compare_digest(hashlib.sha256(clave.encode("utf-8")).hexdigest(), esperado)


def ejemplos(docente=False):
    """Ejemplos .ino del repo (ejemplos_arduino/<nombre>/<nombre>.ino) para
    subirlos desde la pagina con un clic. Sin modo docente, solo los que no son la
    solucion de una practica."""
    out = []
    ocultos = set() if docente else soluciones()
    base = os.path.join(RAIZ, "ejemplos_arduino")
    for d in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        if d in ocultos:
            continue
        ino = os.path.join(base, d, d + ".ino")
        if not os.path.isfile(ino):
            continue
        cabecera = ""
        with open(ino, encoding="utf-8", errors="replace") as f:
            for linea in f:
                if linea.startswith("//"):
                    cabecera = linea[2:].strip()
                    if cabecera:
                        break
        out.append({"nombre": d, "equipo": "esp32plc" if "esp32" in d else "controllino", "resumen": cabecera})
    return out


def leer_ejemplo(nombre: str):
    if not re.fullmatch(r"[A-Za-z0-9_]+", nombre):
        return None
    ruta = os.path.join(RAIZ, "ejemplos_arduino", nombre, nombre + ".ino")
    if not os.path.isfile(ruta):
        return None
    with open(ruta, "rb") as f:
        return nombre + ".ino", f.read()


# ── Cargar solo al generar ───────────────────────────────────────────────────
# El editor no ve los Controllino virtuales (su "Transfer" graba placas reales por
# USB). Equivalente: al pulsar "Generate program for OpenPLC Runtime" el panel ve
# el .st nuevo y lo carga en la CPU del tablero elegido.
auto = {"destino": "", "info": None}
AUTO_DESTINOS = {"": [], "t1": ["t1.openplc"], "t2": ["t2.openplc"], "ambas": ["t1.openplc", "t2.openplc"]}


def hilo_auto():
    vistos = {}
    primera = True
    while True:
        time.sleep(1.0)
        try:
            for p in proyectos():
                antes = vistos.get(p["archivo"])
                vistos[p["archivo"]] = p["t"]
                # Solo lo generado DESPUES de la primera pasada: un archivo nuevo
                # (primer programa de un proyecto) cuenta; uno que ya estaba, no.
                if primera or (antes is not None and p["t"] <= antes):
                    continue
                destinos = AUTO_DESTINOS.get(auto["destino"], [])
                if not destinos:
                    continue
                time.sleep(1.0)                    # que el editor termine de escribir
                if any(contenedores().get(c, {}).get("estado") != "running"
                       for c in ("tab1-openplc", "tab2-openplc")):
                    docker("start", "tab1-openplc", "tab2-openplc", timeout=60)
                    time.sleep(10)
                res = []
                for eq in destinos:
                    ok, txt = cargar(p["archivo"], eq)
                    res.append({"equipo": eq, "ok": ok, "salida": txt[-400:]})
                auto["info"] = {"hora": time.strftime("%H:%M:%S"), "programa": p["nombre"], "resultados": res}
            primera = False
        except Exception as e:                     # un fallo no debe parar el vigilante
            auto["info"] = {"hora": time.strftime("%H:%M:%S"), "programa": "", "error": str(e),
                            "resultados": []}


def preparar(equipo: str, modo: str):
    """Deja un equipo listo para programarlo de una de dos formas:
      openplc  enciende el editor de escalera y la CPU de ese tablero, la deja como
               destino de la flecha naranja, enchufa el Ethernet del Controllino al
               switch y lo pone en ESCLAVO (la CPU lo lee y escribe por Modbus TCP)
      ino      apaga la CPU de ese tablero: si siguiera en RUN pisaria las salidas
               del programa .ino cada 100 ms"""
    m = re.fullmatch(r"t([12])\.(controllino|esp32plc)", equipo)
    if not m:
        return False, "Equipo desconocido: %s" % equipo
    n, tipo = m.group(1), m.group(2)
    cpu = "tab%s-openplc" % n
    if modo == "ino":
        if contenedores().get(cpu, {}).get("estado") == "running":
            docker("stop", cpu, timeout=60)
            with cerrojo:
                estado["t_contenedores"] = 0
        if auto["destino"] in ("t" + n, "ambas"):
            auto["destino"] = "" if auto["destino"] == "t" + n else ("t2" if n == "1" else "t1")
        return True, "listo para .ino"
    if modo != "openplc" or tipo != "controllino":
        return False, "La escalera solo se carga en el Controllino"
    # Si el Controllino corria un .ino de otro alumno/practica, vuelve a fabrica:
    # la CPU solo puede leerlo y escribirlo por Modbus si esta en ESCLAVO.
    eq = ((estado["pasarela"] or {}).get("equipos") or {}).get(equipo) or {}
    if eq.get("modo") == 9:
        ok, txt = fabrica(equipo)
        if not ok:
            return False, "El Controllino corre un .ino: para volver al firmware esclavo hace falta el USB. " + txt
        time.sleep(4)
    rc, out = docker("start", "tab-editor", cpu, timeout=90)
    with cerrojo:
        estado["t_contenedores"] = 0
    if rc != 0:
        return False, "No arranca OpenPLC: " + out[-300:]
    auto["destino"] = "t" + n
    # Cable al switch (si no esta ya) y modo esclavo.
    pasa = estado["pasarela"] or {}
    eth = "t%s.controllino.eth" % n
    enchufado = any(eth in (c.get("a"), c.get("b")) for c in (pasa.get("cables") or {}).values())
    if not enchufado:
        a_pasarela({"t": "cable", "id": "portal_%s" % n, "a": eth, "b": "t%s.switch.p1" % n})
    a_pasarela({"t": "orden", "equipo": "t%s.controllino" % n, "orden": {"cmd": "modo", "v": 0}})
    return True, "OpenPLC T%s encendida; flecha naranja del editor -> Controllino %s" % (n, n)


# ── Practicas y autocorrector ───────────────────────────────────────────────
PRACTICAS = os.path.join(RAIZ, "practicas")
_cerrojo_verif = threading.Lock()
verif = {"corriendo": False, "practica": "", "pasos": [], "actual": -1, "fin": None, "informe": None}


def catalogo():
    try:
        with open(os.path.join(PRACTICAS, "catalogo.json"), encoding="utf-8") as f:
            cat = json.load(f)
    except (OSError, ValueError):
        return []
    for p in cat:
        p["disponible"] = os.path.isfile(os.path.join(PRACTICAS, p["id"], "practica.json"))
    return cat


def leer_practica(pid: str):
    if not re.fullmatch(r"[A-Za-z0-9_]+", pid or ""):
        return None
    d = os.path.join(PRACTICAS, pid)
    try:
        with open(os.path.join(d, "practica.json"), encoding="utf-8") as f:
            p = json.load(f)
        for clave in ("enunciado", "plantilla"):
            if p.get(clave):
                with open(os.path.join(d, p[clave]), encoding="utf-8") as f:
                    p[clave + "_texto"] = f.read()
    except (OSError, ValueError):
        return None
    return p


# ── Espacio en disco: las imagenes pesadas se bajan al necesitarlas y se pueden soltar ──
# Las practicas con servidor propio (L5, L9, L10, L11, U6) traen su docker-compose.yml; sus
# imagenes (Odoo 2,7 GB, ChirpStack...) no hacen falta para el resto del banco. Aqui se
# bajan por adelantado o se sueltan al terminar. NUNCA se tocan los volumenes (el trabajo
# del alumno: base de Odoo, dispositivos de ChirpStack) ni las imagenes del propio banco.
EXTRAS_IMG = {"fuxa": {"titulo": "FUXA (SCADA, alternativa de la L9)", "contenedores": ["tab-fuxa"],
                       "patron": r"frangoteam/fuxa"}}
bajadas = {}          # clave -> {"estado": bajando|listo|error, actual, hechas, total, salida, t}


def _imagenes_de(ruta: str):
    try:
        with open(ruta, encoding="utf-8") as f:
            txt = f.read()
    except OSError:
        return []
    return list(dict.fromkeys(m for m in re.findall(r"^\s*image:\s*['\"]?([^\s'\"#]+)", txt, re.M) if "$" not in m))


def _protegidas():
    """Imagenes del propio banco (compose principal): nunca se sueltan desde el portal."""
    prot = {i for i in _imagenes_de(os.path.join(RAIZ, "docker-compose.yml"))
            if not any(re.search(e["patron"], i) for e in EXTRAS_IMG.values())}
    # ...y las bases de sus Dockerfile (python:3.12-slim lo usan el panel, la pasarela y el MES de la L11)
    try:
        for f in os.listdir(RAIZ):
            if f.startswith("Dockerfile"):
                with open(os.path.join(RAIZ, f), encoding="utf-8") as g:
                    prot.update(re.findall(r"^FROM\s+(?:--\S+\s+)?([^\s]+)", g.read(), re.M))
    except OSError:
        pass
    return prot


def _tam_imagen(img: str):
    rc, out = docker("image", "inspect", "-f", "{{.Size}}", img, timeout=10)
    return int(out.strip()) if rc == 0 and out.strip().isdigit() else None


def paquetes_imagenes():
    """Lo que cada practica (y FUXA) necesita bajar: {clave: {titulo, imagenes, ...}}."""
    protegidas = _protegidas()
    res = {}
    for p in catalogo():
        imgs = [i for i in _imagenes_de(os.path.join(PRACTICAS, p["id"], "pc", "docker-compose.yml"))
                if i not in protegidas and not i.startswith("tablero-")]
        if imgs:
            res[p["id"]] = {"titulo": "%s · %s" % (p["id"], p["titulo"]), "imagenes": imgs, "contenedores": []}
    base = _imagenes_de(os.path.join(RAIZ, "docker-compose.yml"))
    for k, e in EXTRAS_IMG.items():
        imgs = [i for i in base if re.search(e["patron"], i)]
        if imgs:
            res[k] = {"titulo": e["titulo"], "imagenes": imgs, "contenedores": e["contenedores"]}
    for k, r in res.items():
        r["imagenes"] = [{"nombre": i, "bytes": _tam_imagen(i)} for i in r["imagenes"]]
        r["bajado"] = all(i["bytes"] is not None for i in r["imagenes"])
        r["bytes"] = sum(i["bytes"] or 0 for i in r["imagenes"])
        r["bajando"] = bajadas.get(k)
    return res


def _contenedores_pila(clave: str, extra):
    """Contenedores de la pila de una practica (los que lanzo su compose desde run/pc/<id>)."""
    ids = []
    rc, out = docker("ps", "-a", "--format",
                     '{{.ID}}|{{.Label "com.docker.compose.project.working_dir"}}', timeout=15)
    for l in out.splitlines():
        cid, _, wd = l.partition("|")
        if wd and wd.replace("\\", "/").rstrip("/").endswith("/run/pc/" + clave):
            ids.append(cid)
    for nombre in extra:
        rc, out = docker("ps", "-a", "-q", "--filter", "name=^%s$" % nombre, timeout=10)
        ids += out.split()
    return ids


def _bajar(clave: str, imgs):
    b = bajadas[clave]
    for i, img in enumerate(imgs):
        b.update(actual=img, hechas=i)
        for intento in range(3):                       # el registro a veces corta el primer token
            rc, out = docker("pull", img, timeout=3600)
            if rc == 0:
                break
            b["salida"] = "Reintentando %s…" % img
            time.sleep(4 * (intento + 1))
        if rc != 0:
            b.update(estado="error", salida="No se pudo bajar %s: %s" % (img, out.strip().splitlines()[-1][:200] if out.strip() else "sin respuesta"))
            return
    b.update(estado="listo", hechas=len(imgs), actual="", salida="Listo: %s." % ("1 imagen bajada" if len(imgs) == 1 else "%d imágenes bajadas" % len(imgs)))


def bajar_imagenes(clave: str):
    paq = paquetes_imagenes().get(clave)
    if paq is None:
        return False, "Esa práctica no necesita imágenes extra"
    if (bajadas.get(clave) or {}).get("estado") == "bajando":
        return False, "Ya se están bajando"
    pend = [i["nombre"] for i in paq["imagenes"] if i["bytes"] is None]
    if not pend:
        return True, "Ya están en este PC"
    bajadas[clave] = {"estado": "bajando", "actual": pend[0], "hechas": 0, "total": len(pend), "salida": "", "t": time.time()}
    threading.Thread(target=_bajar, args=(clave, pend), daemon=True).start()
    return True, "Bajando %s…" % ("1 imagen" if len(pend) == 1 else "%d imágenes" % len(pend))


def liberar_imagenes(clave: str):
    """Quita los contenedores de la pila y sus imagenes. Los volumenes se conservan."""
    paq = paquetes_imagenes().get(clave)
    if paq is None:
        return False, "Esa práctica no necesita imágenes extra"
    if (bajadas.get(clave) or {}).get("estado") == "bajando":
        return False, "Se están bajando: espera a que termine"
    protegidas = _protegidas()
    ids = _contenedores_pila(clave, paq["contenedores"])
    if ids:
        docker("rm", "-f", *ids, timeout=120)
    liberado, notas = 0, []
    for im in paq["imagenes"]:
        if im["bytes"] is None or im["nombre"] in protegidas:
            continue
        rc, out = docker("rmi", im["nombre"], timeout=120)       # sin -f: si algo la usa, se conserva
        if rc == 0:
            liberado += im["bytes"]
        else:
            notas.append("%s se conserva (la usa otro contenedor)" % im["nombre"])
    bajadas.pop(clave, None)
    txt = "Liberados hasta %.1f GB (las imágenes que comparten capas con otras liberan menos)." % (liberado / 1e9)
    if ids:
        txt += " Se quitaron %d contenedores de la práctica." % len(ids)
    txt += " Tus datos (volúmenes) siguen ahí."
    return True, txt + ("\n" + "\n".join(notas) if notas else "")


def tam_cache_construccion():
    rc, out = docker("system", "df", "--format", "{{.Type}}|{{.Size}}|{{.Reclaimable}}", timeout=60)
    for l in out.splitlines():
        p = l.split("|")
        if len(p) == 3 and p[0].startswith("Build Cache"):
            return p[1], p[2]
    return None, None


def _bajar_otras_pilas(pid: str):
    """Al preparar una practica se bajan las pilas Docker de las demas (L5, L10, L11, L13...).
    Comparten puertos (4841 de OPC UA), IPs del segmento y hasta el registro 4 del PLC, y su
    montaje no tiene sentido tras volver los PLC a fabrica. Solo quita contenedores: los
    volumenes (base de Odoo, dispositivos de ChirpStack) y los archivos del alumno se quedan."""
    rc, out = docker("ps", "-a", "--format",
                     '{{.ID}}|{{.Names}}|{{.Label "com.docker.compose.project.working_dir"}}', timeout=15)
    ids, practicas = [], set()
    for l in out.splitlines():
        cid, nom, wd = (l.split("|") + ["", ""])[:3]
        m = re.search(r"/run/pc/([A-Za-z0-9_]+)/?$", wd.replace("\\", "/"))
        if m and m.group(1) != pid:
            ids.append(cid)
            practicas.add(m.group(1))
    if ids:
        docker("rm", "-f", *ids, timeout=120)
    return sorted(practicas)


def _dir_host_tablero():
    """Ruta de `tablero/` como la ve el demonio de Docker (para los bind mounts de un compose lanzado
    desde este contenedor). Docker Desktop en Windows: unidad:/Users/x pasa a /run/desktop/mnt/host/<unidad>/Users/x."""
    rc, out = docker("inspect", "tab-panel", "--format",
                     '{{range .Mounts}}{{if eq .Destination "/tablero"}}{{.Source}}{{end}}{{end}}', timeout=10)
    src = out.strip()
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", src)
    if m:
        src = "/run/desktop/mnt/host/%s/%s" % (m.group(1).lower(), m.group(2).replace("\\", "/"))
    return src.rstrip("/") if rc == 0 and src else ""


pilas = {}          # id de practica -> {estado: subiendo|ok|error, detalle, t}


def levantar_pila(pid: str):
    """`docker compose -p <id> up -d` de run/pc/<id>/docker-compose.yml, como lo haria el alumno.
    Si falla no deja la pila a medias: se baja (sin tocar volumenes) y el motivo queda en `pilas`."""
    pilas[pid] = {"estado": "subiendo", "detalle": "", "t": time.time()}
    base = os.environ.get("PANEL_DIR_HOST") or _dir_host_tablero()
    fichero = os.path.join(RAIZ, "run", "pc", pid, "docker-compose.yml")
    if not base or not os.path.isfile(fichero):
        pilas[pid].update(estado="error", detalle="no se pudo localizar la carpeta del banco")
        return False, pilas[pid]["detalle"]
    args = ["compose", "-p", pid.lower(), "-f", fichero, "--project-directory", "%s/run/pc/%s" % (base, pid)]
    rc, out = docker(*args, "up", "-d", timeout=900)
    det = out.strip().splitlines()[-1][:160] if out.strip() else ""
    if rc != 0:                                      # corre en segundo plano: que quede en el registro
        print("PILA %s no arranco: %s" % (pid, out.strip()[-400:]), flush=True)
        docker(*args, "down", "--remove-orphans", timeout=120)      # sin -v: los datos se quedan
        det = "no arranco (%s); se bajo lo que habia subido" % (det or "sin detalle")
    pilas[pid].update(estado="ok" if rc == 0 else "error", detalle=det, t=time.time())
    return rc == 0, det


RX_MODULO = re.compile(r"\.(pot|dht11|boton\d|motor|foco|led|mm)\.")


def cablear_solucion(p: dict):
    """Cables de la solucion de una practica: los de la red van a la pasarela; los de los modulos
    (potenciometro...) son del 3D y se devuelven para que el portal se los pase. -> (modulos, n_red)"""
    modulos, n = [], 0
    for i, par in enumerate(p["solucion_cables"]):
        if RX_MODULO.search("%s %s" % (par[0], par[1])):
            modulos.append(par)
            continue
        a_pasarela({"t": "cable", "id": "sol%s_%d" % (p["id"], i), "a": par[0], "b": par[1]})
        n += 1
    return modulos, n


def montar_practica(pid: str, pila: bool = True):
    p = leer_practica(pid)
    if p is None:
        return False, "Práctica desconocida"
    m = p.get("montaje", {})
    bajadas_otras = _bajar_otras_pilas(pid)
    reiniciados = _todo_a_fabrica()
    if m.get("limpiar"):
        a_pasarela({"t": "limpiar"})
    for i, par in enumerate(m.get("cables", [])):
        a_pasarela({"t": "cable", "id": "p%s_%d" % (pid, i), "a": par[0], "b": par[1]})
    for eq, o in m.get("ordenes", []):
        a_pasarela({"t": "orden", "equipo": eq, "orden": o})
    for eq in m.get("wifi", []):                    # antena puesta: radio del ESP32 encendida
        a_pasarela({"t": "wifi", "equipo": eq, "v": True})
    for id_, v in m.get("energia", []):             # interruptores del tablero
        a_pasarela({"t": "energia", "id": id_, "v": bool(v)})
    if m.get("sin_openplc") and p.get("equipo"):
        preparar(p["equipo"], "ino")
    cargado = []
    for eq, ruta in m.get("cargar_plc", []):        # PLC de produccion ya programado (no es lo evaluado)
        try:
            fuente = os.path.join(PRACTICAS, ruta)
            if os.path.isfile(fuente):                 # banco del docente: se compila el .ino
                with open(fuente, "rb") as f:
                    datos = f.read()
                ok_plc, txt_plc = subir(eq, os.path.basename(ruta), datos, sin_usb=True)
            else:                                      # paquete de alumnos: solo el binario (no el codigo de la L7)
                ok_plc, txt_plc = cargar_binario(eq, os.path.splitext(fuente)[0] + ".bin")
        except OSError as e:
            ok_plc, txt_plc = False, str(e)
        cargado.append("%s %s" % (eq, "ya corre %s" % os.path.basename(ruta) if ok_plc else "NO se pudo programar (%s)" % txt_plc.strip()[-120:]))
    # Los archivos de la practica para el PC (clientes Python, capturas provistas,
    # docker-compose con su carpeta de configuracion...) se copian a ~/trabajo/<id> del PC
    # del banco, sin pisar lo que el alumno cambio. Recursivo: L10/U6 traen subcarpetas.
    origen = os.path.join(PRACTICAS, pid, "pc")
    if os.path.isdir(origen):
        destino = os.path.join(RAIZ, "run", "pc", pid)
        for raiz, _dirs, archivos in os.walk(origen):
            rel = os.path.relpath(raiz, origen)
            ddir = destino if rel == "." else os.path.join(destino, rel)
            os.makedirs(ddir, exist_ok=True)
            for nombre in archivos:
                d = os.path.join(ddir, nombre)
                if not os.path.exists(d) or nombre in m.get("pc_actualizar", []):
                    with open(os.path.join(raiz, nombre), "rb") as f, open(d, "wb") as g:
                        g.write(f.read())
    # Archivos que se generan (capturas provistas grandes): [script, archivo, args...]
    for g in m.get("generar", []):
        destino = os.path.join(RAIZ, "run", "pc", pid, g[1])
        if not os.path.exists(destino):
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            subprocess.run([sys.executable, os.path.join(RAIZ, g[0]), destino] + [str(x) for x in g[2:]],
                           capture_output=True, timeout=300)
    hay = os.path.isdir(origen) or m.get("generar")
    extra = " · archivos en ~/trabajo/%s del PC" % pid if hay else ""
    if reiniciados:
        extra += " · %s vuelve%s al programa de fábrica" % (", ".join(reiniciados), "n" if len(reiniciados) > 1 else "")
    if m.get("pila") and pila:                        # la pila Docker de la practica queda levantada
        # En segundo plano: la primera vez puede bajar imagenes grandes (Odoo, ChirpStack...).
        threading.Thread(target=levantar_pila, args=(pid,), daemon=True).start()
        extra += " · levantando tu pila Docker en segundo plano (la primera vez puede tardar varios minutos)"
    if cargado:
        extra += " · " + "; ".join(cargado)
    if bajadas_otras:
        extra += " · se bajó la pila de %s (tus datos se conservan)" % ", ".join(bajadas_otras)
    return True, "Tablero preparado para %s%s" % (pid, extra)


# ── Demostracion completa de la L10 (docente) ───────────────────────────────
# Un boton hace lo que el docente haria a mano: Preparar, antena, cables, los dos .ino, la pila de
# ChirpStack, el alta del nodo, el flujo de Node-RED y espera el primer ascendente. Cada paso deja
# su estado (pend|ahora|ok|error|omitido) y los segundos que tardo; si uno falla se para ahi, con el
# motivo, y «Reintentar desde aquí» sigue sin repetir lo anterior.
L10_CHIRPSTACK = os.environ.get("PANEL_CHIRPSTACK", "host.docker.internal:8089")      # gRPC / web (anfitrion)
L10_CHIRPSTACK_LAN = "192.168.1.81:8080"                                              # lo mismo, desde tab_lan
L10_PASOS = [("imagenes", "Imágenes de Docker"), ("preparar", "Preparar el tablero"),
             ("antena", "Antena de 915 MHz atornillada"), ("cables", "Cables de la solución"),
             ("controllino", "Programa del Controllino (esclavo L10)"),
             ("esp32", "Programa del ESP32 (nodo + pasarela, periodo de demo)"),
             ("chirpstack", "ChirpStack arriba (postgres, redis, bridge)"), ("provision", "Nodo dado de alta en ChirpStack"),
             ("nodered", "Flujo de Node-RED cargado"), ("uplink", "Primer ascendente hasta planta/lorawan/temperatura")]
lora_demo = {"corriendo": False, "pasos": [], "error": None, "t0": 0, "modulos": [], "resumen": ""}


class PasoFallido(Exception):
    pass


def _docker_vivo():
    rc, out = docker("version", "--format", "{{.Server.Version}}", timeout=15)
    if rc != 0 or not out.strip():
        raise PasoFallido("Docker no responde (%s). Abre Docker Desktop y espera a que diga «running»; "
                          "luego «Reintentar desde aquí»." % (out.strip().splitlines() or ["sin salida"])[-1][:140])


def _esperar(cond, limite, cada=1.5):
    """Repite `cond()` hasta que devuelva algo verdadero o pase el limite. -> ultimo valor"""
    t0, v = time.time(), None
    while time.time() - t0 < limite:
        v = cond()
        if v:
            return v
        time.sleep(cada)
    return v


def l10_config():
    p = leer_practica("L10") or {}
    return dict({"periodo_ms": 20000, "controllino": "controllino_esclavo_l10", "esp32": "esp32plc_lora_pasarela",
                 "join_eui": "70B3D57ED0000010", "dev_eui": "0004A30B001F7A01", "a0": 600, "a1": 300,
                 "espera_uplink_s": 300}, **p.get("demo_lora", {}))


def l10_appkey():
    """La AppKey de la demo: se crea una vez y se conserva en run/ (el nodo y ChirpStack la comparten)."""
    ruta = os.path.join(RAIZ, "run", "l10_demo_appkey")
    try:
        with open(ruta, encoding="utf-8") as f:
            k = f.read().strip()
        if re.fullmatch(r"[0-9A-Fa-f]{32}", k):
            return k.upper()
    except OSError:
        pass
    k = secrets.token_hex(16).upper()
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(k + "\n")
    return k


_cache_plan = {"t": 0, "v": None}


def l10_plan():
    """Lo que la demo va a necesitar bajar de Docker Hub (para avisar ANTES de empezar). En cache 20 s."""
    if time.time() - _cache_plan["t"] < 20 and _cache_plan["v"] is not None:
        return _cache_plan["v"]
    try:
        _docker_vivo()
        vivo, motivo = True, ""
    except PasoFallido as e:
        vivo, motivo = False, str(e)
    paq = (paquetes_imagenes().get("L10") or {"imagenes": []}) if vivo else {"imagenes": []}
    faltan = [i for i in paq["imagenes"] if i["bytes"] is None]
    v = {"docker": vivo, "motivo": motivo,
         "imagenes": [{"nombre": i["nombre"], "bytes": i["bytes"], "aprox": APROX_IMG.get(i["nombre"])} for i in paq["imagenes"]],
         "faltan": [{"nombre": i["nombre"], "aprox": APROX_IMG.get(i["nombre"], 0)} for i in faltan],
         "faltan_aprox_bytes": sum(APROX_IMG.get(i["nombre"], 0) for i in faltan)}
    _cache_plan.update(t=time.time(), v=v)
    return v


# Tamano en disco de las imagenes de la L10 (medido con `docker image inspect`; solo para avisar).
APROX_IMG = {"chirpstack/chirpstack:4": 82_000_000, "chirpstack/chirpstack-gateway-bridge:4": 36_000_000,
             "postgres:14-alpine": 415_000_000, "redis:7-alpine": 58_000_000}


def _paso_imagenes(cfg):
    _docker_vivo()
    paq = paquetes_imagenes().get("L10")
    pend = [i["nombre"] for i in (paq or {"imagenes": []})["imagenes"] if i["bytes"] is None]
    if not pend:
        return "ya están en este PC"
    bajadas["L10"] = {"estado": "bajando", "actual": pend[0], "hechas": 0, "total": len(pend), "salida": "", "t": time.time()}
    _bajar("L10", pend)
    b = bajadas["L10"]
    _cache_plan["t"] = 0
    if b.get("estado") != "listo":
        raise PasoFallido("%s Comprueba la conexión a Internet; las imágenes que ya bajó se conservan." % b.get("salida", "no se pudo bajar"))
    return "bajadas: " + ", ".join(pend)


def _paso_preparar(cfg):
    _docker_vivo()
    if not estado["pasarela_ok"]:
        raise PasoFallido("La pasarela del banco no contesta (%s). Arranca el banco con .\\lab.ps1 arrancar." % PASARELA)
    ok, txt = montar_practica("L10", pila=False)
    if not ok:
        raise PasoFallido(txt)
    def listos():
        with cerrojo:
            eqs = (estado["pasarela"] or {}).get("equipos") or {}
        return all((eqs.get(e) or {}).get("encendido") for e in ("t1.controllino", "t1.esp32plc"))
    if not _esperar(listos, 30):
        raise PasoFallido("t1.controllino / t1.esp32plc no informan encendidos tras Preparar (docker ps -a --filter name=tab1).")
    return txt.split(" · ")[0]


def _paso_antena(cfg):
    a_pasarela({"t": "orden", "equipo": "t1.esp32plc", "orden": {"cmd": "lora", "antena": True, "pos": "P1"}})
    def puesta():
        with cerrojo:
            lora = (((estado["pasarela"] or {}).get("equipos") or {}).get("t1.esp32plc") or {}).get("lora") or {}
        return lora.get("antena") and not lora.get("danado")
    if not _esperar(puesta, 10):
        raise PasoFallido("El ESP32 no confirma la antena (lora.antena). ¿Está encendido? Si el RN2903 salió dañado, "
                          "usa «Cambiar el módulo RN2903 averiado» y reintenta.")
    return "antena puesta, nodo en P1"


def _paso_cables(cfg):
    p = leer_practica("L10") or {}
    if not p.get("solucion_cables"):
        raise PasoFallido("L10/practica.json no trae solucion_cables")
    modulos, n = cablear_solucion(p)
    # Con o sin 3D abierto, el potenciometro queda en un valor conocido (el 3D lo sigue si esta abierto).
    montar_ordenes([["t1.controllino", {"cmd": "analogica", "i": 0, "v": int(cfg["a0"])}],
                    ["t1.controllino", {"cmd": "analogica", "i": 1, "v": int(cfg["a1"])}]])
    lora_demo["modulos"] = modulos
    return "%d cables de red, %d de módulos (P1→A0, P2→A1; el portal los pasa al 3D) y A0=%s, A1=%s" % (n, len(modulos), cfg["a0"], cfg["a1"])


def montar_ordenes(ordenes):
    ok = True
    for eq, o in ordenes:
        ok = a_pasarela({"t": "orden", "equipo": str(eq), "orden": o}) and ok
    return ok


def _subir_demo(equipo, nombre_ej, cambios=None):
    ej = leer_ejemplo(nombre_ej)
    if ej is None:
        raise PasoFallido("Falta el ejemplo %s en ejemplos_arduino/" % nombre_ej)
    datos = ej[1]
    if cambios:
        datos = cambios(datos.decode("utf-8", "replace")).encode("utf-8")
    ok, txt = subir(equipo, ej[0], datos, sin_usb=True)          # el USB ya lo pone el montaje de la practica
    if not ok:
        raise PasoFallido("%s no se pudo programar: %s" % (equipo, txt.strip()[-300:]))
    return txt.strip().splitlines()[-1][:120] if txt.strip() else "subido"


def _paso_controllino(cfg):
    return _subir_demo("t1.controllino", cfg["controllino"])


def _paso_esp32(cfg):
    clave = l10_appkey()
    def poner(src):
        src, n1 = re.subn(r'(JOIN_EUI\s*=\s*")[0-9A-Fa-f]*(")', r"\g<1>%s\g<2>" % cfg["join_eui"], src)
        src, n2 = re.subn(r'(APP_KEY\s*=\s*")[0-9A-Fa-f]*(")', r"\g<1>%s\g<2>" % clave, src)
        if n1 != 1 or n2 != 1:
            raise PasoFallido("El sketch ya no tiene las líneas JOIN_EUI / APP_KEY que espera la demo")
        return "#define PERIODO_MS %dUL\n" % int(cfg["periodo_ms"]) + src
    r = _subir_demo("t1.esp32plc", cfg["esp32"], poner)
    return "%s · un envío cada %g s" % (r, int(cfg["periodo_ms"]) / 1000)


def _estado_contenedor(nombre):
    rc, out = docker("inspect", "-f", "{{.State.Status}}|{{.RestartCount}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}",
                     nombre, timeout=10)
    if rc != 0:
        return None
    est, reinicios, salud = (out.strip().split("|") + ["", ""])[:3]
    return {"estado": est, "reinicios": int(reinicios or 0), "salud": salud}


def _http_vivo(url, limite=2):
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=limite) as r:
            return r.status == 200
    except Exception:
        return False


def _pila_lista():
    """None si esta lista; si no, el motivo. Sin esperas a ciegas: cada servicio se interroga."""
    sondas = [("l10-postgres", ["exec", "l10-postgres", "pg_isready", "-U", "chirpstack"], None),
              ("l10-redis", ["exec", "l10-redis", "redis-cli", "ping"], "PONG"),
              ("l10-gateway-bridge", None, None), ("l10-chirpstack", None, None)]
    for nombre, args, espera in sondas:
        c = _estado_contenedor(nombre)
        if c is None:
            return "%s no existe" % nombre
        if c["estado"] != "running" or c["salud"] in ("unhealthy", "starting"):   # "restarting" tambien cae aqui
            return "%s: %s%s" % (nombre, c["estado"], " (%s)" % c["salud"] if c["salud"] else "")
        # RestartCount no baja nunca: ChirpStack se reinicia 2-3 veces mientras postgres arranca y es normal.
        if args:
            rc, out = docker(*args, timeout=10)
            if rc != 0 or (espera and espera not in out):
                return "%s no está listo (%s)" % (nombre, (out.strip().splitlines() or ["sin respuesta"])[-1][:80])
    if not _http_vivo("http://%s/" % L10_CHIRPSTACK):
        return "la web de ChirpStack aún no contesta en %s" % L10_CHIRPSTACK
    return None


def _paso_chirpstack(cfg):
    _docker_vivo()
    rc, out = docker("network", "inspect", "tab_lan", "--format", "{{.Name}}", timeout=10)
    if rc != 0:
        raise PasoFallido("No existe la red tab_lan: el banco no está arrancado (.\\lab.ps1 arrancar).")
    # Esta practica monta su pila aqui, no en segundo plano (Preparar de la demo la omite).
    destino = os.path.join(RAIZ, "run", "pc", "L10")
    if not os.path.isfile(os.path.join(destino, "docker-compose.yml")):
        raise PasoFallido("Falta %s: el paso «Preparar» no copió los archivos de la práctica." % destino)
    ok, det = levantar_pila("L10")
    if not ok:
        raise PasoFallido("docker compose up falló: %s. Si dice «pool overlaps»/«address already in use» hay otra pila usando "
                          "192.168.1.80/.81; si no encuentra la red, falta arrancar el banco." % det)
    ult = [None]
    def lista():
        ult[0] = _pila_lista()
        return ult[0] is None
    if not _esperar(lista, 150, 3):
        rc2, logs = docker("logs", "--tail", "4", "l10-chirpstack", timeout=10)
        raise PasoFallido("La pila no llegó a estar lista en 150 s: %s. ChirpStack dice: %s" % (ult[0], " | ".join(logs.strip().splitlines()[-3:])[:260]))
    return "postgres, redis, bridge y ChirpStack listos"


def _provisionar_l10(appkey, cfg):
    script = os.path.join(RAIZ, "herramientas", "l10_provisionar.py")
    ids = os.path.join(RAIZ, "run", "l10_ids.json")
    try:
        os.remove(ids)
    except OSError:
        pass
    comun = ["--appkey", appkey, "--joineui", cfg["join_eui"], "--deveui", cfg["dev_eui"]]
    try:
        import grpc, chirpstack_api  # noqa: F401
        cmd = [sys.executable, script, "--servidor", L10_CHIRPSTACK, "--json", ids] + comun
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        rc, out = r.returncode, r.stdout + r.stderr
    except ImportError:
        # El contenedor del panel no trae grpc: una vez, en un Python desechable dentro de tab_lan.
        base = os.environ.get("PANEL_DIR_HOST") or _dir_host_tablero()
        if not base:
            raise PasoFallido("No se pudo localizar la carpeta del banco para el contenedor de aprovisionamiento")
        rc, out = docker("run", "--rm", "--network", "tab_lan", "-v", "%s:/t" % base, "python:3.12-slim", "sh", "-c",
                         "pip install -q --disable-pip-version-check grpcio chirpstack-api >/dev/null 2>&1 && "
                         "python /t/herramientas/l10_provisionar.py --servidor %s --json /t/run/l10_ids.json %s"
                         % (L10_CHIRPSTACK_LAN, " ".join(comun)), timeout=420)
    return rc, out, ids


def _paso_provision(cfg):
    clave = l10_appkey()
    rc, out, ids = _provisionar_l10(clave, cfg)
    if rc != 0:
        raise PasoFallido("l10_provisionar.py falló: %s" % (out.strip().splitlines() or ["sin salida"])[-1][:240])
    try:
        with open(ids, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    cambio = "AppKey CAMBIADA" in out
    return "dispositivo %s en la aplicación %s%s" % (cfg["dev_eui"], (d.get("app_id") or "?")[:8],
                                                    " · la clave cambió: el ESP32 ya lleva la nueva" if cambio else "")


def nodered_url():
    """Node-RED al que se manda el flujo: PANEL_NODERED, el de ot-lab si corre (1880) o el del banco (1890)."""
    if os.environ.get("PANEL_NODERED"):
        return os.environ["PANEL_NODERED"].rstrip("/"), "Node-RED (PANEL_NODERED)"
    rc, out = docker("inspect", "-f", "{{.State.Running}}", "node-red", timeout=10)
    if rc == 0 and out.strip() == "true":
        return "http://host.docker.internal:1880", "Node-RED de ot-lab"
    return "http://host.docker.internal:1890", "Node-RED del banco"


def _paso_nodered(cfg):
    url, quien = nodered_url()
    if not os.environ.get("PANEL_NODERED") and "1890" in url:
        rc, out = docker("inspect", "-f", "{{.State.Running}}", "tab-nodered", timeout=10)
        if rc != 0:
            raise PasoFallido("No existe el contenedor tab-nodered: créalo con .\\lab.ps1 nodered y reintenta.")
        if out.strip() != "true":
            docker("start", "tab-nodered", timeout=60)
    import urllib.request
    def vivo():
        try:
            with urllib.request.urlopen(url + "/settings", timeout=3) as r:
                return r.status == 200
        except Exception:
            return False
    if not _esperar(vivo, 90, 3):
        raise PasoFallido("%s no contesta en %s (tarda ~20 s en arrancar; docker logs tab-nodered)." % (quien, url))
    sys.path.insert(0, os.path.join(RAIZ, "herramientas"))
    try:
        import l10_flujo_referencia as ref
    except ImportError as e:
        raise PasoFallido("Falta herramientas/l10_flujo_referencia.py (%s)" % e)
    try:
        ref.desplegar(url, "poner")
    except Exception as e:
        raise PasoFallido("%s rechazó el flujo: %s" % (quien, str(e)[:200]))
    lora_demo["t_flujo"] = time.time()
    return "pestaña «L10 referencia» desplegada en %s (%s)" % (quien, url.replace("host.docker.internal", "localhost"))


def _paso_uplink(cfg):
    t0 = time.time()
    def llega():
        return next((u for u in reversed(uplinks) if u["t"] >= lora_demo["t0"] and u["dev_eui"] == cfg["dev_eui"].lower()), None)
    up = _esperar(llega, cfg["espera_uplink_s"], 2)
    if not up:
        raise PasoFallido("Sin ascendente en %d s. %s" % (cfg["espera_uplink_s"], _donde_se_rompe()))
    if not up.get("decodificado"):
        raise PasoFallido("Llegó el ascendente fCnt %s pero ChirpStack no lo decodificó (¿perfil sin el decodificador?)." % up["fcnt"])
    t_flujo = lora_demo.get("t_flujo", lora_demo["t0"])
    espera = 2 * int(cfg["periodo_ms"]) / 1000.0 + 15          # hasta dos periodos: el flujo puede cargar entre ascendentes
    pl = _esperar(lambda: (mqtt_ultimo.get("planta/lorawan/temperatura") or {}).get("t", 0) >= t_flujo, espera, 1)
    if not pl:
        raise PasoFallido("Llegó el ascendente fCnt %s (temperatura %s) pero Node-RED no publicó planta/lorawan/temperatura en %.0f s. "
                          "Abre el editor de Node-RED: ¿el mqtt in está conectado a 192.168.1.50?" % (up["fcnt"], up["temperatura"], espera))
    return "fCnt %s · %s °C · %s %% · %.0f s de espera" % (up["fcnt"], up["temperatura"], up["nivel"], time.time() - t0)


FUNCIONES_L10 = {"imagenes": _paso_imagenes, "preparar": _paso_preparar, "antena": _paso_antena, "cables": _paso_cables,
                 "controllino": _paso_controllino, "esp32": _paso_esp32, "chirpstack": _paso_chirpstack,
                 "provision": _paso_provision, "nodered": _paso_nodered, "uplink": _paso_uplink}


def _correr_lora_demo(desde: str):
    ids = [p[0] for p in L10_PASOS]
    cfg = l10_config()
    i0 = ids.index(desde)
    for i, (pid, nombre) in enumerate(L10_PASOS):
        paso = lora_demo["pasos"][i]
        if i < i0:
            continue
        paso.update(estado="ahora", detalle="", seg=0, t=time.time())
        try:
            paso["detalle"] = FUNCIONES_L10[pid](cfg) or ""
            paso["estado"] = "ok"
        except PasoFallido as e:
            paso.update(estado="error", detalle=str(e))
            lora_demo["error"] = {"paso": pid, "nombre": nombre, "msg": str(e)}
            break
        except Exception as e:                                   # un fallo inesperado tambien se explica
            paso.update(estado="error", detalle="%s: %s" % (type(e).__name__, str(e)[:200]))
            lora_demo["error"] = {"paso": pid, "nombre": nombre, "msg": paso["detalle"]}
            break
        finally:
            paso["seg"] = round(time.time() - paso["t"], 2)
    else:
        lora_demo["resumen"] = "Listo en %.0f s: mueve los sliders de A0/A1 y mira cambiar el siguiente ascendente." % (time.time() - lora_demo["t0"])
    lora_demo["corriendo"] = False


def lanzar_lora_demo(desde: str = ""):
    ids = [p[0] for p in L10_PASOS]
    if lora_demo["corriendo"]:
        return False, "Ya hay una demostración en curso"
    if desde and desde not in ids:
        return False, "Paso desconocido: %s" % desde
    desde = desde or ids[0]
    previos = {p["id"]: p for p in lora_demo["pasos"]}
    lora_demo.update(corriendo=True, error=None, resumen="", t0=time.time())
    if desde == ids[0]:
        lora_demo["modulos"] = []
    lora_demo["pasos"] = [
        dict(previos[pid]) if pid in previos and ids.index(pid) < ids.index(desde)
        else {"id": pid, "nombre": nombre, "estado": "pend", "detalle": "", "seg": 0}
        for pid, nombre in L10_PASOS]
    threading.Thread(target=_correr_lora_demo, args=(desde,), daemon=True).start()
    return True, "Demostración en marcha"


# ── «Asi debe salir»: la cadena entera de la L10, un vistazo ────────────────
def _donde_se_rompe():
    for c in cadena_l10():
        if c["estado"] != "ok":
            return "La cadena se rompe en «%s»: %s." % (c["nombre"], c["detalle"])
    return "Toda la cadena parece sana (revisa el periodo de envío del sketch)."


_cache_cs = {"t": 0, "v": None}


def cadena_l10():
    cfg = l10_config()
    ahora = time.time()
    with cerrojo:
        eqs = (estado["pasarela"] or {}).get("equipos") or {}
        pas_ok = estado["pasarela_ok"]
    esp = eqs.get("t1.esp32plc") or {}
    lora = esp.get("lora") or {}
    ult = lora.get("ultima") or {}
    cad = []
    def c(id_, nombre, est, det):
        cad.append({"id": id_, "nombre": nombre, "estado": est, "detalle": det})
    # 1 nodo unido
    if not pas_ok:
        c("nodo", "Nodo unido (RN2903)", "fallo", "la pasarela del banco no contesta; sin ella no hay estado del ESP32")
    elif not lora:
        c("nodo", "Nodo unido (RN2903)", "fallo", "el ESP32 no informa del módulo LoRa")
    elif lora.get("danado"):
        c("nodo", "Nodo unido (RN2903)", "fallo", "RN2903 dañado (emitió sin antena): «Cambiar el módulo»")
    elif not lora.get("antena"):
        c("nodo", "Nodo unido (RN2903)", "fallo", "antena sin atornillar")
    elif not lora.get("unido"):
        c("nodo", "Nodo unido (RN2903)", "espera", "sin unir todavía (reintenta a los 15, 30, 60, 120 s; ¿está dado de alta en ChirpStack con la misma AppKey?)")
    elif not re.fullmatch(r"8-15(,6[4-9](-7[01])?|,7[01])*", str(lora.get("canales", ""))):
        c("nodo", "Nodo unido (RN2903)", "fallo", "unido pero con canales %s (debe ser 8-15 y los de 500 kHz)" % lora.get("canales"))
    else:
        c("nodo", "Nodo unido (RN2903)", "ok", "DevAddr %s · canales %s · DR%s" % (lora.get("devaddr"), lora.get("canales"), lora.get("dr")))
    # 2 pasarela
    try:
        with open(os.path.join(RAIZ, "run", "lora", "pasarela.json"), encoding="utf-8") as f:
            pj = json.load(f)
        vivo = ahora - pj.get("t", 0) < 6
    except (OSError, ValueError):
        pj, vivo = {}, False
    if not vivo:
        c("pasarela", "Pasarela LoRaWAN con backhaul", "fallo", "tab-lora no escribe su estado (docker ps --filter name=tab-lora)")
    elif not pj.get("backhaul"):
        c("pasarela", "Pasarela LoRaWAN con backhaul", "fallo", "sin cable: enchufa lora.eth al puerto 4 del switch")
    elif not pj.get("ult_ack"):
        c("pasarela", "Pasarela LoRaWAN con backhaul", "fallo", "el servidor de red no le contesta (ChirpStack abajo o servidor mal en /lora)")
    else:
        c("pasarela", "Pasarela LoRaWAN con backhaul", "ok", "backhaul arriba · último ACK del servidor %s" % pj["ult_ack"])
    # 3 ChirpStack recibe
    if ahora - _cache_cs["t"] > 5:
        _cache_cs["v"] = _http_vivo("http://%s/" % L10_CHIRPSTACK, 1.0)
        _cache_cs["t"] = ahora
    arriba = _cache_cs["v"]
    ups = [u for u in uplinks if u["dev_eui"] == cfg["dev_eui"].lower()]
    ultimo = ups[-1] if ups else None
    if not arriba:
        c("chirpstack", "ChirpStack recibe", "fallo", "la web de ChirpStack no contesta en %s (docker compose -p l10 ps)" % L10_CHIRPSTACK)
    elif ultimo is None:
        c("chirpstack", "ChirpStack recibe", "espera", "arriba, pero aún no ha publicado ningún ascendente del nodo")
    else:
        edad = ahora - ultimo["t"]
        enviado = ult.get("fcnt")
        if enviado is not None and ult.get("t") and ahora - ult["t"] > 10 and (ultimo["fcnt"] is None or ultimo["fcnt"] < enviado):
            c("chirpstack", "ChirpStack recibe", "fallo", "el nodo envió fCnt %s hace %.0f s y ChirpStack solo llegó a %s (¿sesión perdida? mira «docker compose -p l10 logs chirpstack»)"
                % (enviado, ahora - ult["t"], ultimo["fcnt"]))
        else:
            c("chirpstack", "ChirpStack recibe", "ok", "último ascendente fCnt %s hace %.0f s" % (ultimo["fcnt"], edad))
    # 4 MQTT up
    if ultimo is None:
        c("mqtt", "MQTT application/…/event/up", "espera", "ningún evento en el broker del banco (192.168.1.50)")
    elif not ultimo["decodificado"]:
        c("mqtt", "MQTT application/…/event/up", "fallo", "llega pero sin `object`: el perfil no tiene el decodificador (L10.4)")
    else:
        c("mqtt", "MQTT application/…/event/up", "ok", "decodificado: temperatura %s, nivel %s" % (ultimo["temperatura"], ultimo["nivel"]))
    # 5 planta/lorawan/temperatura
    pl = mqtt_ultimo.get("planta/lorawan/temperatura")
    if pl is None:
        c("planta", "planta/lorawan/temperatura", "espera" if ultimo is None else "fallo",
          "nadie la ha publicado" + ("" if ultimo is None else ": Node-RED no está llevando el ascendente (flujo sin cargar o mqtt in desconectado)"))
    elif ultimo is not None and pl["t"] < ultimo["t"] - 2:
        c("planta", "planta/lorawan/temperatura", "fallo", "el último valor (%s, %s) es anterior al ascendente: Node-RED dejó de publicar" % (pl["carga"][:12], pl["hora"]))
    else:
        c("planta", "planta/lorawan/temperatura", "ok", "%s a las %s" % (pl["carga"][:12], pl["hora"]))
    return cad


def estado_lora_demo():
    cfg = l10_config()
    cad = cadena_l10()
    ai = ((((estado["pasarela"] or {}).get("equipos") or {}).get("t1.controllino")) or {}).get("ai") or [0, 0]
    esp_t, esp_n = ai[0] * 1000 // 1023, ai[1] * 1000 // 1023
    ups = [u for u in uplinks if u["dev_eui"] == cfg["dev_eui"].lower()][-10:]
    ids = {}
    try:
        with open(os.path.join(RAIZ, "run", "l10_ids.json"), encoding="utf-8") as f:
            ids = json.load(f)
    except (OSError, ValueError):
        pass
    url_nr, quien_nr = nodered_url() if not lora_demo["corriendo"] else ("", "")
    enlace_dev = "/#/tenants/%s/applications/%s/devices/%s" % (ids["tenant_id"], ids["app_id"], cfg["dev_eui"].lower()) \
        if ids.get("tenant_id") and ids.get("app_id") else ""
    demo = {k: lora_demo[k] for k in ("corriendo", "pasos", "error", "resumen", "modulos")}
    if not demo["pasos"]:         # antes de la primera vez: los pasos que va a hacer, sin empezar
        demo["pasos"] = [{"id": i, "nombre": n, "estado": "pend", "detalle": "", "seg": 0} for i, n in L10_PASOS]
    return {"demo": demo,
            "plan": l10_plan() if not lora_demo["corriendo"] else None,
            "esperado": {"a0": ai[0], "a1": ai[1], "temperatura": esp_t / 10.0, "nivel": esp_n / 10.0,
                         "alarma_temp": not 50 <= esp_t <= 300, "alarma_nivel": not 200 <= esp_n <= 900,
                         "deveui": cfg["dev_eui"], "joineui": cfg["join_eui"], "canales": "8-15,65", "bytes": 9,
                         "tema": "application/<app>/device/%s/event/up" % cfg["dev_eui"].lower(),
                         "periodo_ms": cfg["periodo_ms"]},
            "cadena": cad, "uplinks": list(reversed(ups)),
            "enlaces": {"chirpstack": "http://{host}:8089/", "dispositivo": ("http://{host}:8089" + enlace_dev) if enlace_dev else "",
                        "nodered": url_nr.replace("host.docker.internal", "{host}") if url_nr else "",
                        "nodered_quien": quien_nr},
            "pila": pilas.get("L10")}


class _Banco(verificador.Contexto):
    def __init__(self):
        self.t0 = time.time()           # el monitor serie solo cuenta lo de esta comprobacion

    def equipo(self, nombre):
        with cerrojo:
            return ((estado["pasarela"] or {}).get("equipos") or {}).get(nombre) or {}

    def orden(self, nombre, orden):
        a_pasarela({"t": "orden", "equipo": nombre, "orden": orden})

    def serie(self, nombre):
        c = EQUIPOS_INO.get(nombre)
        if not c:
            return ""
        desde = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.t0))
        return docker("logs", "--since", desde, c, timeout=10)[1]

    def mqtt(self):
        return list(mqtt_msgs)

    def mqtt_ultimos(self):
        return list(mqtt_ultimo.values())

    def hmi(self, n):
        return HMIS[n].estado()

    def hmi_toque(self, n, widget, ev, v=None):
        HMIS[n].toque(widget, ev, v)

    def docker(self, args, timeout):
        # Solo lectura de los contenedores del alumno (exec/inspect/ps), nada que cambie el banco.
        if not args or args[0] not in ("exec", "inspect", "ps", "network", "logs") or                 (args[0] == "network" and args[1:2] not in (["ls"], ["inspect"])):
            return "orden no permitida"
        return docker(*args, timeout=timeout + 10)[1]

    def energia(self, id_, v):
        a_pasarela({"t": "energia", "id": id_, "v": bool(v)})

    def pc(self, cmd, timeout):
        # Lo que el alumno teclearia en la terminal del PC del banco (tab-editor).
        if contenedores().get("tab-editor", {}).get("estado") != "running":
            docker("start", "tab-editor", timeout=60)
            time.sleep(4)
        return docker("exec", "tab-editor", "bash", "-c", cmd, timeout=timeout + 10)[1]


def _verificar(pid: str):
    try:
        _verificar_(pid)
    except Exception as e:                     # sin esto «corriendo» quedaba en True para siempre
        verif["informe"] = None
        verif["pasos"] = [{"txt": "El autocorrector fallo", "ok": False, "motivo": "%s: %s" % (type(e).__name__, e)}]
    finally:
        verif.update({"corriendo": False, "fin": time.time(), "actual": -1})


def _verificar_(pid: str):
    p = leer_practica(pid)
    verif.update({"corriendo": True, "practica": pid, "pasos": [], "actual": 0, "fin": None, "informe": None})
    banco = _Banco()
    eq = p.get("equipo", "")
    e = banco.equipo(eq)
    # Un programa con estado (una FSM, un contador) puede estar en cualquier punto tras
    # lo que el alumno haya probado a mano: se reinicia el equipo, como un reset, para
    # que la comprobacion parta siempre del estado inicial.
    if p.get("reiniciar", True) and eq in EQUIPOS_INO and e.get("modo") == 9:
        docker("restart", EQUIPOS_INO[eq], timeout=30)
        time.sleep(5.0)
        banco.t0 = time.time()
        e = banco.equipo(eq)
    verif["pasos"] = [{"txt": x.get("txt", ""), "ok": None, "motivo": ""} for x in p.get("verificacion", [])]
    # Practicas sin programa propio en un PLC (captura, PROFINET, seguridad): solo pasos.
    if eq and p.get("exige_programa", True) and e.get("modo") != 9:
        verif["pasos"] = [{"txt": "Hay un programa tuyo cargado en %s" % eq, "ok": False,
                           "motivo": "El equipo corre el programa de fábrica: sube primero tu .ino."}] + [
            dict(x, motivo="no se ejecutó") for x in verif["pasos"]]
    else:
        def al_paso(i, r):
            verif["actual"] = i
            if r is not None:
                verif["pasos"][i] = r
        verificador.correr(p, banco, al_paso)
    ok = sum(1 for x in verif["pasos"] if x["ok"])
    sub = subidos.get(eq, {})
    verif["informe"] = {
        "practica": pid, "titulo": p.get("titulo", ""), "equipo": eq,
        "hora": time.strftime("%Y-%m-%d %H:%M:%S"),
        "programa": e.get("programa") or sub.get("nombre", ""), "sha256": sub.get("sha256", ""),
        "subido": sub.get("hora", ""), "pasos": verif["pasos"], "aprobados": ok, "total": len(verif["pasos"]),
    }
    verif.update({"corriendo": False, "fin": time.time(), "actual": -1})


def informe_html(inf: dict) -> str:
    filas = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        "✔" if x["ok"] else ("✘" if x["ok"] is False else "·"), html.escape(str(x["txt"])),
        html.escape(str(x.get("motivo", "")))) for x in inf["pasos"])
    inf = {k: (html.escape(str(v)) if isinstance(v, str) else v) for k, v in inf.items()}
    return ("<!doctype html><meta charset=utf-8><title>Informe %(practica)s</title>"
            "<style>body{font:15px system-ui;max-width:800px;margin:30px auto}td,th{border-bottom:1px solid #ccc;padding:6px;text-align:left}"
            "</style><h1>%(practica)s · %(titulo)s</h1><p>Equipo: %(equipo)s · Comprobado: %(hora)s<br>"
            "Programa: %(programa)s · subido %(subido)s<br>SHA-256: <code>%(sha256)s</code></p>"
            "<h2>%(aprobados)d de %(total)d pasos</h2><table><tr><th></th><th>Paso</th><th>Motivo</th></tr>" % inf
            + filas + "</table><p><small>Informe orientativo del autocorrector del laboratorio; "
            "la nota la pone el docente.</small></p>")


_cap_cerrojo = threading.Lock()


def capturar(red: str, seg: int):
    """Graba `seg` segundos de una red del tablero en formato pcap (lo abre
    Wireshark). Es el mismo sniffer.py que `lab.ps1 wireshark`, pero su codigo
    va por argumento (-c): el demonio de Docker no ve las rutas de este contenedor."""
    if red not in ("tab-lan", "tab-wifi", "tab-485"):
        return None
    try:
        seg = max(3, min(int(seg), 120))
    except (TypeError, ValueError):
        seg = 30
    with open(os.path.join(RAIZ, "herramientas", "sniffer.py"), encoding="utf-8") as f:
        codigo = f.read()
    with _cap_cerrojo:
        docker("rm", "-f", "tab-cap", timeout=15)
        r = subprocess.run(["docker", "run", "--rm", "--name", "tab-cap", "--network", "host",
                            "--cap-add", "NET_RAW", "--cap-add", "NET_ADMIN", "python:3.12-slim",
                            "timeout", str(seg), "python", "-u", "-c", codigo, red, "-"],
                           capture_output=True, timeout=seg + 90)
    return r.stdout


def leer_s7():
    try:
        with open(os.path.join(RAIZ, "run", "panel", "s7.json")) as f:
            d = json.load(f)
        d["vivo"] = time.time() - d.get("t", 0) < 3
        return d
    except (OSError, ValueError):
        return None


# ── HTTP ────────────────────────────────────────────────────────────────────
MAX_CUERPO = 4 * 1024 * 1024          # un .ino / .st / proyecto HMI de alumno pesa kB


class Atender(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _docente(self) -> bool:
        """¿Esta peticion viene de un navegador en modo docente? (cookie del portal)"""
        for parte in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = parte.strip().partition("=")
            if k == "docente" and _ficha_valida(v):
                return True
        return False

    def _json(self, d, code=200):
        b = json.dumps(d).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _texto(self, t, tipo="text/plain; charset=utf-8", code=200):
        b = t.encode() if isinstance(t, str) else t
        self.send_response(code)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _cross_site(self) -> bool:
        """Peticion lanzada por otra web desde el navegador del alumno/docente (CSRF)? Los
        navegadores mandan Origin / Sec-Fetch-Site; curl y Python no, y esos pasan."""
        if (self.headers.get("Sec-Fetch-Site") or "same-origin") == "cross-site":
            return True
        o = self.headers.get("Origin")
        if o is None:
            return False
        return urlparse(o).netloc != (self.headers.get("Host") or "")

    def _seguro(self, f):
        try:
            if self._cross_site():
                return self._json({"ok": False, "salida": "Peticion de otro origen rechazada"}, 403)
            return f()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:                  # JSON roto, int() de un parametro...: 400/500 limpio, sin traza
            try:
                malo = isinstance(e, (ValueError, TypeError, KeyError, IndexError, AttributeError))
                self._json({"ok": False, "salida": "Peticion no valida" if malo else "Error interno"},
                           400 if malo else 500)
            except OSError:
                pass
            print("panel: %s %s -> %s: %s" % (self.command, self.path.split("?")[0], type(e).__name__, e),
                  file=sys.stderr, flush=True)

    def do_GET(self):
        self._seguro(self._get)

    def do_POST(self):
        self._seguro(self._post)

    def _get(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(AQUI, "index.html"), "rb") as f:
                return self._texto(f.read(), "text/html; charset=utf-8")
        if u.path == "/deet.css":                       # linea grafica DEET compartida por las paginas del portal
            with open(os.path.join(AQUI, "deet.css"), "rb") as f:
                return self._texto(f.read(), "text/css; charset=utf-8")
        if u.path in ("/lab", "/lab.html"):
            with open(os.path.join(AQUI, "lab.html"), "rb") as f:
                return self._texto(f.read(), "text/html; charset=utf-8")
        if u.path == "/api/estado":
            with cerrojo:
                d = {"pasarela": estado["pasarela"], "pasarela_ok": estado["pasarela_ok"]}
            d["contenedores"] = contenedores()
            d["mqtt"] = list(mqtt_msgs)[-15:]
            d["s7"] = leer_s7()
            d["proyectos"] = proyectos()
            d["ejemplos"] = ejemplos(self._docente())
            d["auto"] = auto["destino"]
            d["auto_info"] = auto["info"]
            return self._json(d)
        if u.path == "/api/serie":
            eq = q.get("equipo", [""])[0]
            c = EQUIPOS_INO.get(eq)
            if not c:
                return self._json({"texto": ""})
            if not usb_conectado(eq):
                return self._json({"texto": "(sin cable USB del PC a este equipo: el monitor serie va por el USB)",
                                   "usb": False})
            rc, out = docker("logs", "--tail", "60", c, timeout=10)
            return self._json({"texto": out, "usb": True})
        if u.path == "/api/captura":
            red, seg = q.get("red", ["tab-lan"])[0], int(q.get("seg", ["30"])[0])
            datos = capturar(red, seg)
            if not datos or len(datos) < 24:
                return self._json({"ok": False, "salida": "No se pudo capturar %s" % red}, 500)
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.tcpdump.pcap")
            self.send_header("Content-Disposition", 'attachment; filename="captura_%s_%s.pcap"' % (red, time.strftime("%H%M%S")))
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)
            return
        if u.path in ("/hmi", "/hmi.html"):
            with open(os.path.join(AQUI, "hmi.html"), "rb") as f:
                return self._texto(f.read(), "text/html; charset=utf-8")
        if u.path in ("/lora", "/lora.html"):         # pagina local de la pasarela LoRaWAN (L10)
            with open(os.path.join(AQUI, "lora.html"), "rb") as f:
                return self._texto(f.read(), "text/html; charset=utf-8")
        if u.path == "/api/lora":
            try:
                with open(os.path.join(RAIZ, "run", "lora", "pasarela.json"), encoding="utf-8") as f:
                    d = json.load(f)
                d["vivo"] = time.time() - d.get("t", 0) < 5
            except (OSError, ValueError):
                d = {"vivo": False}
            return self._json(d)
        if u.path == "/api/hmi":
            h = HMIS.get(int(q.get("n", ["1"])[0]) if q.get("n", ["1"])[0] in ("1", "2") else 1)
            return self._json(h.estado())
        if u.path == "/api/hmi_ejemplo":
            try:
                with open(os.path.join(RAIZ, "hmi", "ejemplo.json"), encoding="utf-8") as f:
                    return self._json(json.load(f))
            except (OSError, ValueError):
                return self._json({"ok": False}, 404)
        if u.path == "/api/practicas":
            cat = catalogo()
            if not self._docente():           # las soluciones de cada practica, solo al docente
                cat = [{k: v for k, v in e.items() if k != "ejemplos"} for e in cat]
            return self._json(cat)
        if u.path == "/api/practica":
            p = leer_practica(q.get("id", [""])[0])
            if p is None:
                return self._json({"ok": False}, 404)
            p["pasos"] = [x.get("txt", "") for x in p.pop("verificacion", [])]
            if not self._docente():
                p.pop("solucion_ejemplo", None)
                p.pop("solucion_cables", None)
                p.pop("solucion_archivos", None)
                p.pop("solucion_equipos", None)
                p.pop("demo_lora", None)
            return self._json(p)
        if u.path == "/api/docente":
            return self._json({"disponible": docente_disponible(), "activo": self._docente()})
        if u.path == "/api/lora_demo":
            # Estado de la demostracion L10 + «Asi debe salir» (cadena, ascendentes). Solo docente.
            if not self._docente():
                return self._json({"ok": False, "salida": "Solo el docente"}, 403)
            return self._json(estado_lora_demo())
        if u.path == "/api/espacio":
            d = {"paquetes": paquetes_imagenes()}
            if q.get("completo"):
                d["cache"], d["cache_recuperable"] = tam_cache_construccion()
            return self._json(d)
        if u.path == "/api/verificar_estado":
            return self._json({k: verif[k] for k in ("corriendo", "practica", "pasos", "actual", "informe")})
        if u.path == "/api/informe":
            if not verif["informe"]:
                return self._texto("Aún no hay informe", code=404)
            return self._texto(informe_html(verif["informe"]), "text/html; charset=utf-8")
        if u.path.startswith("/guias/"):
            # PDF de las guias del curso (carpeta «Talleres Guia», la del docente).
            nombre = unquote(u.path[len("/guias/"):])
            ruta = os.path.join(RAIZ, "Talleres Guia", nombre)
            if not re.fullmatch(r"[\w .()-]+\.pdf", nombre) or not os.path.isfile(ruta):
                return self._texto("Guía no disponible en este banco", code=404)
            with open(ruta, "rb") as f:
                return self._texto(f.read(), "application/pdf")
        if u.path == "/api/guia":
            g = GUIAS.get(q.get("g", [""])[0])
            if not g:
                return self._texto("guia desconocida", code=404)
            with open(os.path.join(RAIZ, g), encoding="utf-8") as f:
                return self._texto(f.read(), "text/markdown; charset=utf-8")
        return self._texto("no existe", code=404)

    def _post(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = -1
        if n < 0:
            return self._json({"ok": False, "salida": "Content-Length no valido"}, 400)
        if n > MAX_CUERPO:
            self.close_connection = True
            return self._json({"ok": False, "salida": "Cuerpo demasiado grande (maximo %d MB)" % (MAX_CUERPO >> 20)}, 413)
        cuerpo = self.rfile.read(n) if n else b""
        if u.path == "/api/lora_config":
            # FSB y servidor de red de la pasarela LoRaWAN (lo lee tab-lora cada segundo)
            d = json.loads(cuerpo or b"{}")
            try:
                fsb = int(d.get("fsb", 2))
                srv = str(d.get("servidor", "192.168.1.80")).strip()
                puerto = int(d.get("puerto", 1700))
            except (TypeError, ValueError):
                return self._json({"ok": False}, 400)
            if not (1 <= fsb <= 8 and re.fullmatch(r"[0-9.]{7,15}|[A-Za-z0-9_.-]{1,63}", srv) and 0 < puerto < 65536):
                return self._json({"ok": False}, 400)
            os.makedirs(os.path.join(RAIZ, "run", "lora"), exist_ok=True)
            with open(os.path.join(RAIZ, "run", "lora", "config.json"), "w") as f:
                json.dump({"fsb": fsb, "servidor": srv, "puerto": puerto}, f)
            return self._json({"ok": True})
        if u.path == "/api/orden":
            d = json.loads(cuerpo or b"{}")
            if d.get("t") not in ("orden", "wifi"):        # solo lo que dan los botones
                return self._json({"ok": False}, 400)
            return self._json({"ok": a_pasarela(d)})
        if u.path == "/api/saturar":
            # Taller U6, Parte III: el atacante satura el segmento (nivel 0-100, seg de duracion).
            nivel = max(0, min(100, int(q.get("nivel", ["50"])[0])))
            seg = max(0.0, min(120.0, float(q.get("seg", ["30"])[0])))
            return self._json({"ok": a_pasarela({"t": "saturar", "nivel": nivel, "seg": seg})})
        if u.path == "/api/docente_entrar":
            try:
                clave = str(json.loads(cuerpo or b"{}").get("clave", ""))
            except ValueError:
                clave = ""
            with _cerrojo_intentos:               # un intento por segundo en total, aunque lleguen en paralelo
                bien = docente_disponible() and clave_valida(clave)
                if not bien:
                    time.sleep(1.0)           # sin prisa para probar claves
            if not bien:
                return self._json({"ok": False, "salida": "Clave incorrecta"}, 403)
            token = secrets.token_urlsafe(24)
            ahora = time.time()
            for h in [h for h, v in list(_tokens_docente.items()) if v["hasta"] < ahora]:
                _tokens_docente.pop(h, None)
            _tokens_docente[_huella(token)] = {"desde": ahora, "hasta": ahora + SESION_DOCENTE_S}
            _guardar_sesiones()
            b = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", "docente=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d" % (token, SESION_DOCENTE_S))
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if u.path == "/api/docente_salir":
            for parte in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = parte.strip().partition("=")
                if k == "docente":
                    _tokens_docente.pop(_huella(v), None)
            _guardar_sesiones()
            return self._json({"ok": True})
        if u.path == "/api/subir_ejemplo":
            nombre_ej = q.get("ejemplo", [""])[0]
            if nombre_ej in soluciones() and not self._docente():
                return self._json({"ok": False, "salida": "Ese ejemplo es la solución de una práctica: "
                                   "solo lo sube el docente (modo docente)."}, 403)
            ej = leer_ejemplo(nombre_ej)
            if ej is None:
                return self._json({"ok": False, "salida": "Ejemplo desconocido"}, 404)
            ok, txt = subir(q.get("equipo", [""])[0], ej[0], ej[1])
            return self._json({"ok": ok, "salida": txt})
        if u.path == "/api/subir":
            ok, txt = subir(q.get("equipo", [""])[0], q.get("nombre", [""])[0], cuerpo)
            return self._json({"ok": ok, "salida": txt})
        if u.path == "/api/cargar":
            ok, txt = cargar(q.get("archivo", [""])[0], q.get("equipo", [""])[0])
            return self._json({"ok": ok, "salida": txt})
        if u.path == "/api/auto":
            a = q.get("destino", [""])[0]
            if a not in AUTO_DESTINOS:
                return self._json({"ok": False}, 400)
            auto["destino"] = a
            return self._json({"ok": True})
        if u.path == "/api/openplc":
            # Encender/apagar CPUs y editor: los contenedores ya existen
            # (los crea `.\lab.ps1 arrancar`), aqui solo start/stop.
            # El editor no toca el Controllino y puede estar siempre encendido;
            # las CPUs si (escriben las salidas) y se manejan aparte.
            acc = q.get("accion", [""])[0]
            que = {"cpus": ["tab1-openplc", "tab2-openplc"], "editor": ["tab-editor"], "nodered": ["tab-nodered"]}.get(q.get("que", ["cpus"])[0])
            if acc not in ("start", "stop") or not que:
                return self._json({"ok": False}, 400)
            # Convivencia con ot-lab: si su Node-RED corre (1880, enchufado al banco por la
            # pasarela), se usa ese y no se levanta el nuestro (1890); no chocan de puerto.
            if que == ["tab-nodered"] and acc == "start":
                rc_o, out_o = docker("inspect", "-f", "{{.State.Running}}", "node-red", timeout=10)
                if rc_o == 0 and out_o.strip() == "true":
                    return self._json({"ok": True, "puerto": 1880,
                                       "salida": "Node-RED de ot-lab (http://localhost:1880), enchufado al banco: "
                                       "ve el broker 192.168.1.50 y los PLC."})
            rc, out = docker(acc, *que, timeout=60)
            with cerrojo:
                estado["t_contenedores"] = 0
            return self._json({"ok": rc == 0, "salida": out})
        if u.path == "/api/montar":
            # Cablea el banco como lo pide una practica: {"cables": [[a, b], ...],
            # "limpiar": true, "ordenes": [[equipo, {...}], ...]}. Es lo mismo que
            # harian las manos en el 3D, pero de un clic.
            d = json.loads(cuerpo or b"{}")
            ok = True
            if d.get("limpiar"):
                ok = a_pasarela({"t": "limpiar"}) and ok
            for i, par in enumerate(d.get("cables", [])):
                ok = a_pasarela({"t": "cable", "id": "m%d_%d" % (int(time.time()) % 100000, i),
                                 "a": str(par[0]), "b": str(par[1])}) and ok
            for eq, o in d.get("ordenes", []):
                ok = a_pasarela({"t": "orden", "equipo": str(eq), "orden": o}) and ok
            return self._json({"ok": ok})
        if u.path == "/api/hmi_cargar":
            try:
                n = int(q.get("n", ["1"])[0])
                HMIS[n].cargar(json.loads(cuerpo or b"{}"))
            except (KeyError, ValueError, TypeError) as e:
                return self._json({"ok": False, "salida": "Proyecto no válido: %s" % e}, 400)
            return self._json({"ok": True})
        if u.path == "/api/hmi_toque":
            try:
                h = HMIS[int(q.get("n", ["1"])[0])]
                v = q.get("v", [None])[0]
                ev = q.get("ev", ["down"])[0]
                if v not in (None, "") and ev == "set":
                    try:
                        v = float(v)
                    except ValueError:
                        pass            # el texto de un edit
                ok = h.toque(q.get("w", [""])[0], ev, v if v not in (None, "") else None)
            except (KeyError, ValueError):
                return self._json({"ok": False}, 400)
            return self._json({"ok": ok})
        if u.path == "/api/cablear_solucion":
            # Boton «Cablear solucion» (modo docente): pone los cables de la solucion de una practica
            # que el alumno tiene que cablear a mano. Los de la red van a la pasarela; los de los
            # modulos (potenciometro...) son del 3D y se devuelven para que el portal se los pase.
            if not self._docente():
                return self._json({"ok": False, "salida": "Solo el docente"}, 403)
            p = leer_practica(q.get("id", [""])[0])
            if p is None or not p.get("solucion_cables"):
                return self._json({"ok": False, "salida": "Esta práctica no tiene cableado de solución"}, 404)
            modulos, n = cablear_solucion(p)
            return self._json({"ok": True, "modulos": modulos,
                               "salida": "Cableado de la solución: %d cables de red y %d de módulos" % (n, len(modulos))})
        if u.path == "/api/lora_demo":
            # MONTAR SOLUCION COMPLETA (L10): arranca los pasos en segundo plano; el avance se lee con GET.
            # ?desde=<paso> = «Reintentar desde aqui». Solo docente.
            if not self._docente():
                return self._json({"ok": False, "salida": "Solo el docente"}, 403)
            ok, txt = lanzar_lora_demo(q.get("desde", [""])[0])
            return self._json({"ok": ok, "salida": txt}, 200 if ok else 409)
        if u.path == "/api/mes_demo":
            # Demostracion L11 (docente): crea una orden en Odoo y la pasa al MES. Lo hace el panel porque
            # el navegador, con el portal por HTTPS, no puede llamar al MES por HTTP (contenido mixto).
            if not self._docente():
                return self._json({"ok": False, "salida": "Solo el docente"}, 403)
            import urllib.request
            try:
                n = int(q.get("cantidad", ["20"])[0])
                with urllib.request.urlopen("http://host.docker.internal:8095/api/crear_orden?cantidad=%d" % n, timeout=20) as r:
                    d = json.loads(r.read().decode())
                if d.get("ok"):
                    urllib.request.urlopen("http://host.docker.internal:8095/api/nueva_orden", timeout=10).read()
                return self._json(d)
            except Exception as e:
                return self._json({"ok": False, "error": str(e)[:200]})
        if u.path == "/api/practica_montar":
            ok, txt = montar_practica(q.get("id", [""])[0])
            return self._json({"ok": ok, "salida": txt})
        if u.path == "/api/verificar":
            pid = q.get("id", [""])[0]
            if leer_practica(pid) is None:
                return self._json({"ok": False, "salida": "Práctica sin criterios de comprobación"}, 404)
            with _cerrojo_verif:
                if verif["corriendo"]:
                    return self._json({"ok": False, "salida": "Ya hay una comprobación en curso"}, 409)
                verif["corriendo"] = True
            threading.Thread(target=_verificar, args=(pid,), daemon=True).start()
            return self._json({"ok": True})
        if u.path == "/api/preparar":
            ok, txt = preparar(q.get("equipo", [""])[0], q.get("modo", [""])[0])
            return self._json({"ok": ok, "salida": txt})
        if u.path == "/api/fabrica":
            ok, txt = fabrica(q.get("equipo", [""])[0])
            return self._json({"ok": ok, "salida": txt})
        if u.path == "/api/imagenes_bajar":
            ok, txt = bajar_imagenes(q.get("id", [""])[0])
            return self._json({"ok": ok, "salida": txt})
        if u.path == "/api/imagenes_liberar":
            ok, txt = liberar_imagenes(q.get("id", [""])[0])
            return self._json({"ok": ok, "salida": txt})
        if u.path == "/api/limpiar_cache":
            # Residuo de construir las imagenes del banco; no afecta a nada que corra.
            rc, out = docker("builder", "prune", "-f", timeout=300)
            ult = [l for l in out.splitlines() if l.strip()][-1:] or [""]
            return self._json({"ok": rc == 0, "salida": ult[0]})
        return self._json({"ok": False}, 404)


if __name__ == "__main__":
    _cargar_sesiones()
    threading.Thread(target=hilo_pasarela, daemon=True).start()
    threading.Thread(target=hilo_mqtt, daemon=True).start()
    threading.Thread(target=hilo_auto, daemon=True).start()
    threading.Thread(target=hilo_hmi_3d, daemon=True).start()
    for h in HMIS.values():
        h.iniciar()
    print("Panel del laboratorio en http://localhost:%d" % PUERTO, flush=True)
    ThreadingHTTPServer(("0.0.0.0", PUERTO), Atender).serve_forever()
