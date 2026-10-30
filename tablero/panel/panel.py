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
import json
import os
import hashlib
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
PUERTO = 8090
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
cerrojo = threading.Lock()
_sock = None


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
                d = json.loads(linea)
                if d.get("t") == "estado":
                    with cerrojo:
                        estado["pasarela"] = d
                        estado["pasarela_ok"] = True
                    _toques_hmi(d.get("hmi_toques") or [])
        except (OSError, ValueError):
            pass
        _sock = None
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
        s.sendall((json.dumps(d) + "\n").encode())
        return True
    except OSError:
        return False


# ── MQTT ────────────────────────────────────────────────────────────────────
def hilo_mqtt():
    async def bucle():
        while True:
            c = ClienteMQTT("panel-pc")
            def al_mensaje(tema, carga):
                txt = carga.decode("utf-8", "replace")
                mqtt_msgs.append({"hora": time.strftime("%H:%M:%S"), "tema": tema, "carga": txt[:200]})
                mqtt_ultimo[tema] = {"hora": time.strftime("%H:%M:%S"), "t": time.time(), "tema": tema,
                                     "carga": txt[:8000]}
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
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
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
    nombre = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(nombre))
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
        tmp = "/tmp/" + nombre
        # El editor nuevo (2024) mete en el .st comentarios "(*DBG: ...*)" con el
        # codigo del depurador; el runtime de la imagen (2019) no los entiende y
        # falla con "unknown syntax error". Se quitan: no cambian el programa.
        salto = bytes([10])
        limpio = salto.join(l for l in datos.split(salto) if not l.lstrip().startswith(b"(*DBG:"))
        with open(tmp, "wb") as f:
            f.write(limpio)
        rc, out = docker("cp", tmp, "%s:/root/OpenPLC_v3/webserver/st_files/%s" % (c, nombre))
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
    if not ruta.startswith(os.path.realpath(PROYECTOS) + os.sep) or not ruta.endswith(".st"):
        return False, "Archivo no valido"
    nombre = rel.split("/")[-3] + ".st" if rel.endswith("build/generated_plc.st") else os.path.basename(rel)
    with open(ruta, "rb") as f:
        return subir(equipo, nombre, f.read())


# ── Modo docente ─────────────────────────────────────────────────────────────
# Los ejemplos que RESUELVEN una practica (los que nombra el catalogo o la practica como
# solucion) solo los ve y sube el docente, tras dar su clave en el portal. La clave se
# guarda solo como SHA-256 en panel/clave_docente.sha256, que NO va en el paquete de los
# alumnos (.gitattributes export-ignore), igual que esos ejemplos: sin ese archivo no hay
# modo docente. `.\lab.ps1 clave-docente` la cambia.
CLAVE_DOCENTE = os.path.join(AQUI, "clave_docente.sha256")
_tokens_docente = set()


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
    return hashlib.sha256(clave.encode("utf-8")).hexdigest() == esperado


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


def levantar_pila(pid: str):
    """`docker compose -p <id> up -d` de run/pc/<id>/docker-compose.yml, como lo haria el alumno."""
    base = _dir_host_tablero()
    fichero = os.path.join(RAIZ, "run", "pc", pid, "docker-compose.yml")
    if not base or not os.path.isfile(fichero):
        return False, "no se pudo localizar la carpeta del banco"
    rc, out = docker("compose", "-p", pid.lower(), "-f", fichero, "--project-directory",
                     "%s/run/pc/%s" % (base, pid), "up", "-d", timeout=900)
    if rc != 0:                                      # corre en segundo plano: que quede en el registro
        print("PILA %s no arranco: %s" % (pid, out.strip()[-400:]), flush=True)
    return rc == 0, out.strip().splitlines()[-1][:160] if out.strip() else ""


def montar_practica(pid: str):
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
    if m.get("pila"):                                 # la pila Docker de la practica queda levantada
        # En segundo plano: la primera vez puede bajar imagenes grandes (Odoo, ChirpStack...).
        threading.Thread(target=levantar_pila, args=(pid,), daemon=True).start()
        extra += " · levantando tu pila Docker en segundo plano (la primera vez puede tardar varios minutos)"
    if cargado:
        extra += " · " + "; ".join(cargado)
    if bajadas_otras:
        extra += " · se bajó la pila de %s (tus datos se conservan)" % ", ".join(bajadas_otras)
    return True, "Tablero preparado para %s%s" % (pid, extra)


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
        "✔" if x["ok"] else ("✘" if x["ok"] is False else "·"), x["txt"], x.get("motivo", "")) for x in inf["pasos"])
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
    seg = max(3, min(int(seg), 120))
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
class Atender(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _docente(self) -> bool:
        """¿Esta peticion viene de un navegador en modo docente? (cookie del portal)"""
        for parte in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = parte.strip().partition("=")
            if k == "docente" and v in _tokens_docente:
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

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(AQUI, "index.html"), "rb") as f:
                return self._texto(f.read(), "text/html; charset=utf-8")
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
            return self._json(p)
        if u.path == "/api/docente":
            return self._json({"disponible": docente_disponible(), "activo": self._docente()})
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

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        n = int(self.headers.get("Content-Length", 0))
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
            if not docente_disponible() or not clave_valida(clave):
                time.sleep(1.0)               # sin prisa para probar claves
                return self._json({"ok": False, "salida": "Clave incorrecta"}, 403)
            token = secrets.token_urlsafe(24)
            _tokens_docente.add(token)
            b = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", "docente=%s; Path=/; HttpOnly; SameSite=Strict" % token)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if u.path == "/api/docente_salir":
            for parte in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = parte.strip().partition("=")
                if k == "docente":
                    _tokens_docente.discard(v)
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
            modulos, n = [], 0
            for i, par in enumerate(p["solucion_cables"]):
                if re.search(r"\.(pot|dht11|boton\d|motor|foco|led|mm)\.", "%s %s" % (par[0], par[1])):
                    modulos.append(par)
                    continue
                a_pasarela({"t": "cable", "id": "sol%s_%d" % (p["id"], i), "a": par[0], "b": par[1]})
                n += 1
            return self._json({"ok": True, "modulos": modulos,
                               "salida": "Cableado de la solución: %d cables de red y %d de módulos" % (n, len(modulos))})
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
            if verif["corriendo"]:
                return self._json({"ok": False, "salida": "Ya hay una comprobación en curso"}, 409)
            if leer_practica(pid) is None:
                return self._json({"ok": False, "salida": "Práctica sin criterios de comprobación"}, 404)
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
    threading.Thread(target=hilo_pasarela, daemon=True).start()
    threading.Thread(target=hilo_mqtt, daemon=True).start()
    threading.Thread(target=hilo_auto, daemon=True).start()
    threading.Thread(target=hilo_hmi_3d, daemon=True).start()
    for h in HMIS.values():
        h.iniciar()
    print("Panel del laboratorio en http://localhost:%d" % PUERTO, flush=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PUERTO), Atender)
    cert, llave = "/tablero/run/certs/cert.pem", "/tablero/run/certs/key.pem"
    if os.path.isfile(cert) and os.path.isfile(llave):      # lab.ps1 compartir: HTTPS con certificado propio
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, llave)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        print("Panel por HTTPS (certificado propio)", flush=True)
    srv.serve_forever()
