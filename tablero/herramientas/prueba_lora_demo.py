#!/usr/bin/env python3
"""Prueba del boton «MONTAR SOLUCION COMPLETA (L10)» del portal (panel.py: /api/lora_demo) en ESTE equipo,
sin el banco de Docker. Lo que se simula y lo que no:

  simulado   la pasarela del banco (puerto 7170): un servidor TCP de pega que contesta como ella (estado
             de los equipos, ordenes de antena y potenciometros) y apunta lo que le llega.
             Docker: un envoltorio `docker` (SHIM) que deja pasar todo al Docker real salvo lo que
             toca a los contenedores del banco (tab1-*): `exec ... compilar.py` COMPILA de verdad el
             .ino con el nucleo Arduino del repositorio y `restart` arranca el nodo emulado.
  real       la clave del docente (un hash temporal, nunca la del banco), las sesiones, el 403, las
             rutas de error (Docker apagado, imagen que no baja, compose que falla), el avance por
             pasos y «Reintentar desde aqui». Con --completo ademas: la pila de ChirpStack (compose del
             repositorio, red tab_lan y broker en 192.168.1.50 que crea la propia prueba), el alta del
             nodo (l10_provisionar.py), un Node-RED real, el RN2903 emulado + la pasarela LoRaWAN del
             repositorio con el .ino real, y la tabla «Asi debe salir» con ascendentes reales.

    python3 tablero/herramientas/prueba_lora_demo.py [--completo] [--mantener]

Necesita: docker, g++, python3 con grpcio, paho-mqtt, cryptography y chirpstack-api (en PYTHONPATH).
Usa el enlace  ln -sfn <repo>/tablero /tablero  (el panel tiene RAIZ=/tablero) y escribe en /programas.
"""
import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
TABLERO = os.path.abspath(os.path.join(AQUI, ".."))
DISP = os.path.join(TABLERO, "dispositivos")
PUERTO_PANEL, PUERTO_GW = 18090, 17170
BASE = "http://127.0.0.1:%d" % PUERTO_PANEL
DEVEUI = "0004a30b001f7a01"

resultados = []


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def check(nombre, ok, detalle=""):
    resultados.append((nombre, bool(ok)))
    log(("OK    " if ok else "FALLA ") + nombre + (" · " + str(detalle) if detalle != "" else ""))
    return ok


SHIM = r'''#!/usr/bin/env python3
import os, shutil, subprocess, sys, time
D = os.environ["SHIM_DIR"]; REAL = os.environ["SHIM_REAL"]; a = sys.argv[1:]
flag = lambda n: os.path.exists(os.path.join(D, n))
with open(os.path.join(D, "log"), "a") as f:
    f.write(" ".join(a) + "\n")
if flag("off"):
    sys.stderr.write("Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?\n"); sys.exit(1)
if a[:1] == ["pull"] and flag("pullfail"):
    sys.stderr.write("Error response from daemon: pull access denied for " + a[-1] + ", repository does not exist\n"); sys.exit(1)
if a[:2] == ["image", "inspect"] and flag("missing") and a[-1] in open(os.path.join(D, "missing")).read().split():
    sys.stderr.write("Error: No such image: " + a[-1] + "\n"); sys.exit(1)
if a[:1] == ["compose"] and "up" in a and flag("composefail"):
    sys.stderr.write("failed to create network tab_lan: Pool overlaps with other one on this address space\n"); sys.exit(1)
EQ = {"tab1-esp32plc": "t1.esp32plc", "tab1-controllino": "t1.controllino", "tab2-esp32plc": "t2.esp32plc", "tab2-controllino": "t2.controllino"}
if a[:1] in (["restart"], ["start"], ["stop"]) and len(a) > 1 and a[1].startswith("tab") and a[1] != "tab-nodered":
    open(os.path.join(D, a[0] + "_" + a[1]), "w").write(str(time.time()))
    sys.exit(0)
if a[:1] == ["exec"] and len(a) > 2 and a[1] in EQ:
    if "compilar.py" in a:
        eq = EQ[a[1]]
        src, dst = "/tablero/programas/%s/fuente" % eq, "/programas/%s/fuente" % eq
        os.makedirs(dst, exist_ok=True)
        for f in os.listdir(dst):
            os.remove(os.path.join(dst, f))
        for f in os.listdir(src):
            shutil.copy(os.path.join(src, f), dst)
        r = subprocess.run([sys.executable, os.path.join(os.environ["SHIM_DISP"], "compilar.py")], cwd=os.environ["SHIM_DISP"],
                           env=dict(os.environ, TAB_ID=eq), capture_output=True, text=True)
        sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); sys.exit(r.returncode)
    sys.exit(0)
os.execv(REAL, ["docker"] + a)
'''


# ══ La pasarela del banco, de pega ════════════════════════════════════════════
class PasarelaFalsa:
    def __init__(self, puerto, trabajo):
        self.trabajo = trabajo
        self.ai = [0, 0]
        self.antena = False
        self.ordenes = []
        self.cables = []
        self.estado_nodo = lambda: {}
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", puerto))
        self.srv.listen(5)
        threading.Thread(target=self._aceptar, daemon=True).start()

    def estado(self):
        lora = dict(self.estado_nodo())
        lora["antena"] = self.antena
        lora.setdefault("danado", False)
        lora.setdefault("unido", False)
        prog = lambda eq: os.path.isdir("/tablero/programas/" + eq)
        return {"t": "estado", "cables": {}, "hmi_toques": [], "equipos": {
            "t1.controllino": {"encendido": True, "modo": 9 if prog("t1.controllino") else 0, "ai": list(self.ai)},
            "t1.esp32plc": {"encendido": True, "modo": 9 if prog("t1.esp32plc") else 0, "ai": [0, 0, 0, 0], "lora": lora}}}

    def _aceptar(self):
        while True:
            c, _ = self.srv.accept()
            threading.Thread(target=self._atender, args=(c,), daemon=True).start()

    def _atender(self, c):
        c.settimeout(0.5)
        buf = b""
        t_est = 0
        try:
            while True:
                if time.time() - t_est > 0.4:
                    c.sendall((json.dumps(self.estado()) + "\n").encode())
                    t_est = time.time()
                try:
                    datos = c.recv(4096)
                    if not datos:
                        return
                    buf += datos
                except socket.timeout:
                    continue
                while b"\n" in buf:
                    linea, buf = buf.split(b"\n", 1)
                    self._orden(json.loads(linea))
        except OSError:
            return

    def _orden(self, d):
        self.ordenes.append(d)
        if d.get("t") == "cable":
            self.cables.append([d["a"], d["b"]])
        if d.get("t") == "orden":
            o = d.get("orden", {})
            if d["equipo"] == "t1.esp32plc" and o.get("cmd") == "lora":
                if "antena" in o:
                    self.antena = bool(o["antena"])
                sys.path.insert(0, DISP)
                import rn2903          # lo mismo que base.py: el modulo guarda antena/posicion en /programas/<equipo>/rn2903.json
                rn2903.guardar_hw("t1.esp32plc", {k: o[k] for k in ("antena", "pos") if k in o})
            if d["equipo"] == "t1.controllino" and o.get("cmd") == "analogica":
                self.ai[int(o["i"])] = int(o["v"])
                if int(o["i"]) == 0:
                    try:
                        open(os.path.join(self.trabajo, "pot"), "w").write(str(int(o["v"])))
                    except OSError:
                        pass


# ══ Cliente del panel ═════════════════════════════════════════════════════════
class Cliente:
    def __init__(self):
        self.cookie = ""

    def pedir(self, metodo, ruta, cuerpo=None, timeout=30):
        rq = urllib.request.Request(BASE + ruta, method=metodo, data=json.dumps(cuerpo).encode() if cuerpo is not None else (b"" if metodo == "POST" else None))
        if self.cookie:
            rq.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(rq, timeout=timeout) as r:
                if r.headers.get("Set-Cookie"):
                    self.cookie = r.headers["Set-Cookie"].split(";")[0]
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}

    def esperar_demo(self, limite=120):
        t0 = time.time()
        while time.time() - t0 < limite:
            c, d = self.pedir("GET", "/api/lora_demo")
            if c == 200 and not d["demo"]["corriendo"]:
                return d
            time.sleep(1)
        raise TimeoutError("la demostracion no termino en %d s" % limite)


def arrancar_panel(env, trabajo):
    f = open(os.path.join(trabajo, "panel.log"), "a")
    p = subprocess.Popen([sys.executable, "-u", "/tablero/panel/panel.py"], env=env, cwd=trabajo, stdout=f, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/api/docente", timeout=1).read()
            return p
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("el panel no arranca; mira " + f.name)


def pasos_txt(d):
    return " | ".join("%s=%s%s" % (p["id"], p["estado"], "(%ss)" % p["seg"] if p["seg"] else "") for p in d["demo"]["pasos"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--completo", action="store_true", help="ChirpStack, Node-RED, nodo y pasarela LoRaWAN reales")
    ap.add_argument("--mantener", action="store_true")
    a = ap.parse_args()
    if not os.path.isdir("/tablero/panel"):
        sys.exit("falta el enlace:  ln -sfn %s /tablero" % TABLERO)
    trabajo = tempfile.mkdtemp(prefix="l10demo_")
    shim = os.path.join(trabajo, "shim")
    os.makedirs(shim)
    open(os.path.join(shim, "docker"), "w").write(SHIM)
    os.chmod(os.path.join(shim, "docker"), 0o755)
    clave = secrets.token_urlsafe(14)                  # clave de la prueba: ni se imprime ni se guarda aparte del hash
    archivo_clave = os.path.join(trabajo, "clave.sha256")
    open(archivo_clave, "w").write(hashlib.sha256(clave.encode()).hexdigest() + "\n")
    sesiones = os.path.join(trabajo, "sesiones.json")
    pasarela = PasarelaFalsa(PUERTO_GW, trabajo)
    open(os.path.join(trabajo, "pot"), "w").write("0")
    env = dict(os.environ, PATH=shim + os.pathsep + os.environ["PATH"], SHIM_DIR=shim, SHIM_REAL=shutil.which("docker"),
               SHIM_DISP=DISP, PANEL_PUERTO=str(PUERTO_PANEL), PANEL_PASARELA="127.0.0.1:%d" % PUERTO_GW,
               PANEL_BROKER="192.168.1.50", PANEL_CLAVE_ARCHIVO=archivo_clave, PANEL_SESIONES_ARCHIVO=sesiones,
               PANEL_DIR_HOST=TABLERO, PANEL_CHIRPSTACK="127.0.0.1:8089", PANEL_NODERED="http://127.0.0.1:1890",
               PYTHONUNBUFFERED="1")
    creado = {"red": False, "broker": False, "nodered": False}
    nodo = None
    panel = None
    try:
        # ── infraestructura de la prueba: red tab_lan y el broker del banco (192.168.1.50) ──
        if subprocess.run(["docker", "network", "inspect", "tab_lan"], capture_output=True).returncode:
            subprocess.run(["docker", "network", "create", "--subnet", "192.168.1.0/24", "--gateway", "192.168.1.254", "tab_lan"], check=True, capture_output=True)
            creado["red"] = True
        if subprocess.run(["docker", "inspect", "tab-broker"], capture_output=True).returncode:
            subprocess.run(["docker", "run", "-d", "--name", "tab-broker", "--network", "tab_lan", "--ip", "192.168.1.50", "eclipse-mosquitto:2",
                            "sh", "-c", 'printf "listener 1883 0.0.0.0\\nallow_anonymous true\\n" > /tmp/m.conf; mosquitto -c /tmp/m.conf'],
                           check=True, capture_output=True)
            creado["broker"] = True
        # «Preparar» borra el estado del modulo LoRa (/programas/<equipo>/rn2903.json) en el banco real; aqui, a mano.
        for f in ("rn2903.json", "rn2903.json.tmp"):
            try:
                os.remove("/programas/t1.esp32plc/" + f)
            except OSError:
                pass
        panel = arrancar_panel(env, trabajo)
        cli = Cliente()

        # ── 1. Sin modo docente: 403 y nada de las soluciones ────────────────────
        c, d = cli.pedir("GET", "/api/lora_demo")
        check("GET /api/lora_demo sin docente -> 403", c == 403, c)
        c, d = cli.pedir("POST", "/api/lora_demo")
        check("POST /api/lora_demo sin docente -> 403", c == 403, c)
        c, d = cli.pedir("POST", "/api/cablear_solucion?id=L10")
        check("POST /api/cablear_solucion sin docente -> 403", c == 403, c)
        c, d = cli.pedir("GET", "/api/practica?id=L10")
        check("/api/practica L10 sin docente no trae solucion_cables ni demo_lora", c == 200 and "solucion_cables" not in d and "demo_lora" not in d)
        c, d = cli.pedir("POST", "/api/docente_entrar", {"clave": "no-es-la-clave"})
        check("clave incorrecta -> 403", c == 403, c)
        c, d = cli.pedir("POST", "/api/docente_entrar", {"clave": clave})
        check("clave correcta -> 200 y cookie", c == 200 and cli.cookie.startswith("docente="), c)
        txt = open(sesiones).read()
        check("el archivo de sesiones no contiene la clave, su hash ni la ficha en claro",
              clave not in txt and open(archivo_clave).read().strip() not in txt and cli.cookie.split("=")[1] not in txt)
        check("archivo de sesiones con permisos 600", oct(os.stat(sesiones).st_mode & 0o777) == "0o600", oct(os.stat(sesiones).st_mode & 0o777))
        c, d = cli.pedir("GET", "/api/practica?id=L10")
        check("con docente /api/practica trae solucion_cables (11 hilos) y demo_lora", len(d.get("solucion_cables", [])) == 11 and "demo_lora" in d,
              len(d.get("solucion_cables", [])))

        # ── 2. La sesion sobrevive al reinicio del panel ─────────────────────────
        panel.terminate(); panel.wait(10)
        panel = arrancar_panel(env, trabajo)
        c, d = cli.pedir("GET", "/api/docente")
        check("tras reiniciar el panel el docente sigue dentro", d.get("activo") is True, d)
        c, d = Cliente().pedir("GET", "/api/docente")
        check("otro navegador (sin cookie) no es docente", d.get("activo") is False)
        os.utime(archivo_clave, (time.time() + 5, time.time() + 5))      # «cambiar la clave» invalida las sesiones
        panel.terminate(); panel.wait(10)
        panel = arrancar_panel(env, trabajo)
        c, d = cli.pedir("GET", "/api/docente")
        check("si cambia el archivo de la clave, las sesiones guardadas dejan de valer", d.get("activo") is False, d)
        os.utime(archivo_clave, (time.time() - 100, time.time() - 100))
        cli.pedir("POST", "/api/docente_entrar", {"clave": clave})
        c, d = cli.pedir("POST", "/api/docente_salir")
        c, d = cli.pedir("GET", "/api/docente")
        check("salir cierra la sesion", d.get("activo") is False)
        cli.pedir("POST", "/api/docente_entrar", {"clave": clave})

        # ── 3. Rutas de error ────────────────────────────────────────────────────
        time.sleep(2)
        open(os.path.join(shim, "off"), "w").close()
        time.sleep(21)                                           # la cache del plan caduca a los 20 s
        c, d = cli.pedir("GET", "/api/lora_demo")
        check("Docker apagado: el plan lo dice antes de empezar", c == 200 and d["plan"]["docker"] is False and "Docker no responde" in d["plan"]["motivo"], d["plan"]["motivo"][:70])
        c, d = cli.pedir("POST", "/api/lora_demo")
        d = cli.esperar_demo(30)
        e = d["demo"]["error"] or {}
        check("Docker apagado: la demo para en el paso 1 con un mensaje claro", e.get("paso") == "imagenes" and "Docker no responde" in e.get("msg", ""), e.get("msg", "")[:90])
        os.remove(os.path.join(shim, "off"))

        open(os.path.join(shim, "missing"), "w").write("chirpstack/chirpstack:4\nredis:7-alpine\n")
        open(os.path.join(shim, "pullfail"), "w").close()
        time.sleep(21)
        c, d = cli.pedir("GET", "/api/lora_demo")
        pl = d["plan"]
        check("imagen ausente: el plan lista lo que falta con su tamaño aproximado", [f["nombre"] for f in pl["faltan"]] == ["chirpstack/chirpstack:4", "redis:7-alpine"] and pl["faltan_aprox_bytes"] == 140_000_000,
              "%d MB" % (pl["faltan_aprox_bytes"] // 1_000_000))
        cli.pedir("POST", "/api/lora_demo")
        d = cli.esperar_demo(90)
        e = d["demo"]["error"] or {}
        check("imagen que no baja: error en el paso 1 con el motivo", e.get("paso") == "imagenes" and "No se pudo bajar chirpstack/chirpstack:4" in e.get("msg", ""), e.get("msg", "")[:90])
        os.remove(os.path.join(shim, "pullfail")); os.remove(os.path.join(shim, "missing"))
        time.sleep(21)

        # ── 4. Secuencia completa hasta ChirpStack (compose que falla) ───────────
        open(os.path.join(shim, "composefail"), "w").close()
        t0 = time.time()
        c, d0 = cli.pedir("POST", "/api/lora_demo")
        c2, d2 = cli.pedir("POST", "/api/lora_demo")
        check("segunda orden mientras corre -> 409", c2 == 409, c2)
        visto = set()
        while time.time() - t0 < 180:
            c, d = cli.pedir("GET", "/api/lora_demo")
            for p in d["demo"]["pasos"]:
                if p["estado"] == "ahora":
                    visto.add(p["id"])
            if not d["demo"]["corriendo"]:
                break
            time.sleep(0.3)
        log("pasos:", pasos_txt(d))
        e = d["demo"]["error"] or {}
        orden_ok = [p["id"] for p in d["demo"]["pasos"] if p["estado"] == "ok"]
        check("los 6 primeros pasos terminan ok y en orden", orden_ok == ["imagenes", "preparar", "antena", "cables", "controllino", "esp32"], orden_ok)
        check("el paso en curso se ve mientras corre (progreso por sondeo)", {"preparar", "esp32"} <= visto, sorted(visto))
        check("compose que falla: error en el paso «chirpstack»", e.get("paso") == "chirpstack" and "docker compose up" in e.get("msg", ""), e.get("msg", "")[:100])
        check("no deja la pila a medias: se ejecuto «compose ... down»", any(l.startswith("compose") and " down" in l and "l10" in l for l in open(os.path.join(shim, "log")).read().splitlines()))
        check("los pasos posteriores quedan sin hacer", [p["estado"] for p in d["demo"]["pasos"][7:]] == ["pend"] * 3)
        antes = {p["id"]: p["seg"] for p in d["demo"]["pasos"]}
        check("cada paso trae sus segundos", all(antes[i] >= 0 for i in orden_ok) and sum(antes.values()) > 5, antes)
        check("antena: la pasarela recibio {cmd:lora, antena:true}", any(o.get("t") == "orden" and o["orden"].get("cmd") == "lora" and o["orden"].get("antena") is True for o in pasarela.ordenes))
        check("cables de red de la solucion enviados (RS-485, USB, lora.eth)", ["lora.eth", "t1.switch.p4"] in pasarela.cables and ["t1.controllino.485A", "t1.esp32plc.485A"] in pasarela.cables, len(pasarela.cables))
        check("cables de modulos (P1->A0, P2->A1) devueltos para el 3D", ["t1.esp32plc.pot.senal", "t1.controllino.A0"] in d["demo"]["modulos"] and ["t2.esp32plc.pot.senal", "t1.controllino.A1"] in d["demo"]["modulos"], len(d["demo"]["modulos"]))
        check("A0=600 y A1=300 por /analogica (la via sin 3D)", pasarela.ai == [600, 300], pasarela.ai)
        fuente = open("/tablero/programas/t1.esp32plc/fuente/esp32plc_lora_pasarela.ino").read()
        appkey = open("/tablero/run/l10_demo_appkey").read().strip()
        check("el .ino del ESP32 lleva PERIODO_MS 20000UL, JOIN_EUI y la AppKey de la demo",
              fuente.startswith("#define PERIODO_MS 20000UL") and '"70B3D57ED0000010"' in fuente and appkey in fuente and len(appkey) == 32)
        check("ambos .ino compilan con el nucleo Arduino (g++)", os.path.isfile("/programas/t1.esp32plc/programa") and os.path.isfile("/programas/t1.controllino/programa"))
        os.remove(os.path.join(shim, "composefail"))

        if not a.completo:
            return 0 if all(ok for _, ok in resultados) else 1
        # ══ Parte real: ChirpStack, Node-RED, nodo y pasarela LoRaWAN ═══════════════
        sys.path.insert(0, AQUI)
        import prueba_l10 as L
        arg = argparse.Namespace(trabajo=trabajo, sin_pila=True, periodo_ms=0, provisionador="")
        banco = L.Banco(arg)
        banco.pot(pasarela.ai[0])            # Banco() lo pone a 0: se respeta el A0 que dejo la demo
        with open(os.path.join(banco.env["TAB_LORA_DIR"], "config.json"), "w") as f:
            json.dump({"fsb": 2, "servidor": "192.168.1.80", "puerto": 1700}, f)
        os.makedirs("/tablero/run", exist_ok=True)
        if os.path.lexists("/tablero/run/lora"):
            os.remove("/tablero/run/lora") if os.path.islink("/tablero/run/lora") else shutil.rmtree("/tablero/run/lora")
        os.symlink(banco.env["TAB_LORA_DIR"], "/tablero/run/lora")
        banco.lanzar_pasarela()
        pasarela.estado_nodo = banco.estado_nodo
        stop = threading.Event()

        def vigila():           # `docker restart tab1-esp32plc` -> el nodo arranca con el binario recien compilado
            ultimo = 0
            f = os.path.join(shim, "restart_tab1-esp32plc")
            while not stop.is_set():
                try:
                    t = os.path.getmtime(f)
                    if t > ultimo and os.path.isfile("/programas/t1.esp32plc/programa"):
                        ultimo = t
                        log("nodo: arranca con el programa nuevo")
                        banco.arrancar_nodo()
                except OSError:
                    pass
                time.sleep(0.5)
        threading.Thread(target=vigila, daemon=True).start()
        # Node-RED real (si la imagen esta) en 192.168.1.60, publicado en 127.0.0.1:1890
        if subprocess.run(["docker", "image", "inspect", "nodered/node-red:4.0"], capture_output=True).returncode == 0:
            subprocess.run(["docker", "rm", "-f", "tab-nodered-prueba"], capture_output=True)
            subprocess.run(["docker", "run", "-d", "--name", "tab-nodered-prueba", "--network", "tab_lan", "--ip", "192.168.1.60",
                            "-p", "127.0.0.1:1890:1880", "nodered/node-red:4.0"], check=True, capture_output=True)
            creado["nodered"] = True
        else:
            log("AVISO: no esta la imagen nodered/node-red:4.0; el paso del flujo fallara")
        subprocess.run(["docker", "compose", "-p", "l10", "down", "-v"], capture_output=True, cwd="/tablero/run/pc/L10")

        # «Reintentar desde aqui»: sigue en «chirpstack» sin repetir lo anterior
        t0 = time.time()
        c, d0 = cli.pedir("POST", "/api/lora_demo?desde=chirpstack")
        check("Reintentar desde aquí -> 200", c == 200, c)
        visto = []
        while time.time() - t0 < 900:
            c, d = cli.pedir("GET", "/api/lora_demo")
            ahora = [p["id"] for p in d["demo"]["pasos"] if p["estado"] == "ahora"]
            if ahora and (not visto or visto[-1] != ahora[0]):
                visto.append(ahora[0])
                log("paso en curso: %s (%.0f s)" % (ahora[0], time.time() - t0))
            if not d["demo"]["corriendo"]:
                break
            time.sleep(1)
        log("pasos:", pasos_txt(d))
        e = d["demo"]["error"]
        check("el reintento no repite los pasos anteriores", visto[:1] == ["chirpstack"] and all(v not in visto for v in ("preparar", "esp32")), visto)
        check("demostracion completa sin error (los 10 pasos ok)", e is None and all(p["estado"] == "ok" for p in d["demo"]["pasos"]), e or "")
        log("resumen:", d["demo"]["resumen"], "| total %.0f s" % (time.time() - t0))
        for p in d["demo"]["pasos"]:
            log("   %-12s %6.1f s  %s" % (p["id"], p["seg"], p["detalle"][:110]))
        cad = d["cadena"]
        check("«Asi debe salir»: toda la cadena en verde", all(c["estado"] == "ok" for c in cad), [(c["id"], c["estado"]) for c in cad])
        for c_ in cad:
            log("   cadena %-10s %-6s %s" % (c_["id"], c_["estado"], c_["detalle"][:110]))
        ups = d["uplinks"]
        check("tabla de ascendentes con filas reales", len(ups) >= 1, len(ups))
        if ups:
            u = ups[0]
            log("   ultimo ascendente:", json.dumps({k: u[k] for k in ("fcnt", "frec_mhz", "canal", "sf", "dr", "rssi", "snr", "temperatura", "nivel", "alarma_temp", "alarma_nivel", "bytes")}))
            check("trama de 9 B, SF10/DR0, canal 8-15 (903.9-905.3 MHz) y A0=600 -> 58.6 C, A1=300 -> 29.3 %",
                  u["bytes"] == 9 and u["sf"] == 10 and u["dr"] == 0 and 903.8 < u["frec_mhz"] < 905.4 and u["temperatura"] == 58.6 and u["nivel"] == 29.3,
                  (u["bytes"], u["sf"], u["frec_mhz"], u["temperatura"], u["nivel"]))
        ex = d["esperado"]
        check("esperado: DevEUI, JoinEUI, canales y tema", ex["deveui"] == "0004A30B001F7A01" and ex["joineui"] == "70B3D57ED0000010" and ex["canales"] == "8-15,65" and ex["temperatura"] == 58.6, ex["tema"])
        en = d["enlaces"]
        check("enlace directo al dispositivo banco-t1", "/#/tenants/" in en["dispositivo"] or "/tenants/" in en["dispositivo"], en["dispositivo"])
        # el UI de ChirpStack responde en la ruta de ese enlace y los ids existen
        import grpc
        from chirpstack_api import api
        canal = grpc.insecure_channel("127.0.0.1:8089")
        tok = api.InternalServiceStub(canal).Login(api.LoginRequest(email="admin", password="admin")).jwt
        md = [("authorization", "Bearer " + tok)]
        ids = json.load(open("/tablero/run/l10_ids.json"))
        dev = api.DeviceServiceStub(canal).Get(api.GetDeviceRequest(dev_eui=DEVEUI), metadata=md).device
        check("los ids del enlace (tenant, app) son los del dispositivo en ChirpStack", dev.application_id == ids["app_id"] and dev.name == "banco-t1")
        check("l10_ids.json sin AppKey", "app_key" not in json.dumps(ids).lower() and appkey.lower() not in json.dumps(ids).lower())

        # Slider: A0 -> 900 (87.9 C) y se ve en el siguiente ascendente
        t1 = time.time()
        c, _ = cli.pedir("POST", "/api/montar", {"ordenes": [["t1.controllino", {"cmd": "analogica", "i": 0, "v": 900}]]})
        nuevo = None
        while time.time() - t1 < 60:
            c, d = cli.pedir("GET", "/api/lora_demo")
            if d["uplinks"] and d["uplinks"][0]["temperatura"] == 87.9:
                nuevo = d["uplinks"][0]
                break
            time.sleep(1)
        check("slider A0=900 por /api/montar -> el uplink muestra 87.9 C", nuevo is not None, "%.0f s hasta verlo (periodo 20 s)" % (time.time() - t1) if nuevo else "no llego")
        # (alarma_temp/alarma_nivel no se comprueban aqui: el Controllino de pega no calcula el registro [9]; el real si)
        # ── la cadena marca el eslabon roto ──
        subprocess.run(["docker", "stop", "l10-chirpstack"], capture_output=True)
        time.sleep(7)
        c, d = cli.pedir("GET", "/api/lora_demo")
        rotos = [x["id"] for x in d["cadena"] if x["estado"] != "ok"]
        check("ChirpStack parado: «ChirpStack recibe» sale en rojo", "chirpstack" in rotos and d["cadena"][2]["estado"] == "fallo", d["cadena"][2]["detalle"][:80])
        subprocess.run(["docker", "start", "l10-chirpstack"], capture_output=True)
        banco.pasarela.terminate(); banco.pasarela.wait(5)
        time.sleep(9)
        c, d = cli.pedir("GET", "/api/lora_demo")
        check("pasarela LoRa parada: «Pasarela con backhaul» sale en rojo", d["cadena"][1]["estado"] == "fallo", d["cadena"][1]["detalle"][:80])
        stop.set()
    finally:
        log("--- RESUMEN:", sum(1 for _, ok in resultados if ok), "de", len(resultados), "comprobaciones OK")
        for n, ok in resultados:
            if not ok:
                log("    FALLA:", n)
        try:
            if panel:
                panel.terminate()
        except Exception:
            pass
        try:
            banco.cerrar()
        except Exception:
            pass
        if not a.mantener:
            subprocess.run(["docker", "compose", "-p", "l10", "down", "-v"], capture_output=True, cwd="/tablero/run/pc/L10")
            if creado["nodered"]:
                subprocess.run(["docker", "rm", "-f", "tab-nodered-prueba"], capture_output=True)
            if creado["broker"]:
                subprocess.run(["docker", "rm", "-f", "tab-broker"], capture_output=True)
            if creado["red"]:
                subprocess.run(["docker", "network", "rm", "tab_lan"], capture_output=True)
        print("trabajo:", trabajo)
    return 0 if all(ok for _, ok in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
