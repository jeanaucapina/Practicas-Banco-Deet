#!/usr/bin/env python3
"""Prueba de extremo a extremo de la practica L10 (LoRaWAN) en ESTE equipo, sin el banco.

Levanta un ChirpStack v4 de verdad (Docker, red del anfitrion; copia de
practicas/L10/pc/docker-compose.yml con un mosquitto), el aire + pasarela LoRaWAN
(dispositivos/pasarela_lora.py), el RN2903 emulado (dispositivos/rn2903.py) y el
programa REAL del ESP32 (ejemplos_arduino/esp32plc_lora_pasarela.ino, compilado con el
nucleo Arduino del banco) y comprueba que el nodo se une y que ChirpStack decodifica
sus ascendentes, EN LOS DOS ORDENES:

  nodo-primero       el nodo arranca antes de que el dispositivo exista en ChirpStack
  provision-primero  el dispositivo existe antes de que arranque el nodo
  reprovisionar      el nodo ya unido y se vuelve a ejecutar l10_provisionar.py: no debe
                     perder la sesion (sin nueva union)
  recrear            el nodo ya unido y alguien borra y recrea el dispositivo
                     (l10_provisionar.py --recrear): el nodo debe volver solo
  reprogramar        el nodo unido se reprograma (reinicio del equipo) con el
                     dispositivo intacto: debe unirse otra vez
  preparar           como reprogramar, pero «Preparar el tablero» ademas borra
                     /programas/<equipo> (el contador DevNonce del modulo vuelve a empezar)

Solo lo que se simula aqui: el Controllino (un esclavo Modbus RTU de pega con el
potenciometro A0 en un archivo). La cadena real Controllino A0 -> RS-485 -> ESP32 ->
LoRa necesita los contenedores del banco y se prueba en local (ver al final).

    python tablero/herramientas/prueba_l10.py [--escenarios nodo-primero,provision-primero,...]
        [--periodo-ms 20000] [--mantener] [--sin-pila]

Necesita: docker, g++, python3 con `cryptography`, `grpcio`, `paho-mqtt` y
`chirpstack-api` (pip install chirpstack-api; si no compila la rueda, basta con
copiar el paquete a PYTHONPATH). Escribe en /programas/t1.esp32plc (como el banco).

En local, con el banco real (Docker Desktop):
    .\\lab.ps1 arrancar ; (montaje de L10: Preparar) ; cd tablero\\run\\pc\\L10
    docker compose -p l10 up -d ; python tablero\\herramientas\\l10_provisionar.py
    .\\lab.ps1 subir t1.controllino ejemplos_arduino\\controllino_esclavo_l10\\...ino
    .\\lab.ps1 subir t1.esp32plc <sketch con JOIN_EUI/APP_KEY>   (el nodo se une solo)
    .\\lab.ps1 serie t1.esp32plc    y   docker compose -p l10 logs -f chirpstack
"""

import argparse
import asyncio
import base64
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
TABLERO = os.path.abspath(os.path.join(AQUI, ".."))
DISP = os.path.join(TABLERO, "dispositivos")
INO = os.path.join(TABLERO, "ejemplos_arduino", "esp32plc_lora_pasarela", "esp32plc_lora_pasarela.ino")
COMPOSE_L10 = os.path.join(TABLERO, "practicas", "L10", "pc")
EQUIPO = "t1.esp32plc"
PROG = "/programas/" + EQUIPO
DEVEUI = "0004A30B001F7A01"        # el hweui del RN2903 del tablero 1 (rn2903.py)
JOINEUI = "70B3D57ED0000010"
APPKEY = "2B7E151628AED2A6ABF7158809CF4F3C"
GW = "A84041FFFE1F7603"
API = "127.0.0.1:8080"

# ── Compose de la prueba: la del repositorio, pero en la red del anfitrion ────
COMPOSE = """services:
  mosquitto:
    image: eclipse-mosquitto:2
    network_mode: host
    volumes: ["./mosquitto.conf:/mosquitto/config/mosquitto.conf"]
  chirpstack:
    image: chirpstack/chirpstack:4
    command: -c /etc/chirpstack
    network_mode: host
    restart: on-failure
    volumes: ["./configuration/chirpstack:/etc/chirpstack"]
    depends_on: [postgres, redis, mosquitto]
    environment: [MQTT_BROKER_HOST=127.0.0.1, REDIS_HOST=127.0.0.1, POSTGRESQL_HOST=127.0.0.1]
  chirpstack-gateway-bridge:
    image: chirpstack/chirpstack-gateway-bridge:4
    network_mode: host
    restart: on-failure
    volumes: ["./configuration/chirpstack-gateway-bridge:/etc/chirpstack-gateway-bridge"]
    environment:
      - INTEGRATION__MQTT__EVENT_TOPIC_TEMPLATE=us915_1/gateway/{{ .GatewayID }}/event/{{ .EventType }}
      - INTEGRATION__MQTT__STATE_TOPIC_TEMPLATE=us915_1/gateway/{{ .GatewayID }}/state/{{ .StateType }}
      - INTEGRATION__MQTT__COMMAND_TOPIC_TEMPLATE=us915_1/gateway/{{ .GatewayID }}/command/#
  postgres:
    image: postgres:14-alpine
    network_mode: host
    volumes: ["./configuration/postgresql/initdb:/docker-entrypoint-initdb.d"]
    environment: [POSTGRES_USER=chirpstack, POSTGRES_PASSWORD=chirpstack, POSTGRES_DB=chirpstack]
  redis:
    image: redis:7-alpine
    network_mode: host
"""


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# Papel "nodo": el programa.py del ESP32 con el bus RS-485 sustituido por un
# Controllino de pega (esclavo 1, FC3, A0 = potenciometro leido de un archivo)
# ══════════════════════════════════════════════════════════════════════════════
def rol_nodo(trabajo: str):
    sys.path.insert(0, DISP)
    import programa
    from modbus_mini import abrir_rtu, trama_rtu

    class Nodo(programa.Programa):
        def enviar_485_crudo(self, t, ya_emitida=False):
            r = abrir_rtu(t)
            if r is None or r[0] != 1 or r[1][0] != 3:
                return
            ini, n = int.from_bytes(r[1][1:3], "big"), int.from_bytes(r[1][3:5], "big")
            try:
                a0 = int(open(os.path.join(trabajo, "pot")).read().strip())
            except (OSError, ValueError):
                a0 = 0
            regs = [0] * 16
            regs[0], regs[8], regs[9] = a0, 300, 0           # A0, A1, estado
            carga = b"".join(v.to_bytes(2, "big") for v in regs[ini:ini + n])
            resp = trama_rtu(1, bytes([3, len(carga)]) + carga)
            asyncio.get_running_loop().call_later(0.03, lambda: self.crudo_485(resp))

    async def main():
        p = Nodo()
        await p.iniciar()
        while True:
            await asyncio.sleep(1.0)
            try:
                with open(os.path.join(trabajo, "estado_nodo.json.tmp"), "w") as f:
                    json.dump(p.lora.resumen(), f)
                os.replace(os.path.join(trabajo, "estado_nodo.json.tmp"), os.path.join(trabajo, "estado_nodo.json"))
            except OSError:
                pass

    asyncio.run(main())


# ══════════════════════════════════════════════════════════════════════════════
# Orquestador
# ══════════════════════════════════════════════════════════════════════════════
class Banco:
    def __init__(self, a):
        self.a = a
        self.trabajo = a.trabajo or tempfile.mkdtemp(prefix="l10prueba_")
        os.makedirs(self.trabajo, exist_ok=True)
        self.t_ini = time.time()
        self.eventos = []                   # (t, tipo, dict) de MQTT
        self.lock = threading.Lock()
        self.pasarela = self.nodo = None
        self.env = dict(os.environ, TAB_ID=EQUIPO, TAB_LORA_IP="127.0.0.1", TAB_LORA_LAN="127.0.0.1",
                        TAB_LORA_DIR=os.path.join(self.trabajo, "lora"))
        bindir = os.path.join(self.trabajo, "bin")
        os.makedirs(bindir, exist_ok=True)
        with open(os.path.join(bindir, "ip"), "w") as f:     # `ip -o -4 addr` de la pasarela (no hay iproute2 aqui)
            f.write("#!/bin/sh\necho '1: lo    inet 127.0.0.1/8 scope host lo'\n")
        os.chmod(os.path.join(bindir, "ip"), 0o755)
        if not shutil.which("ip"):
            self.env["PATH"] = bindir + os.pathsep + self.env["PATH"]
        os.makedirs(self.env["TAB_LORA_DIR"], exist_ok=True)
        with open(os.path.join(self.env["TAB_LORA_DIR"], "config.json"), "w") as f:
            json.dump({"fsb": 2, "servidor": "127.0.0.1", "puerto": 1700}, f)
        self.pot(0)

    # ── ChirpStack ────────────────────────────────────────────────────────────
    def pila(self):
        d = os.path.join(self.trabajo, "pila")
        if not os.path.isdir(d):
            os.makedirs(d)
            shutil.copytree(os.path.join(COMPOSE_L10, "configuration"), os.path.join(d, "configuration"))
            p = os.path.join(d, "configuration", "chirpstack-gateway-bridge", "chirpstack-gateway-bridge.toml")
            t = open(p).read().replace("tcp://192.168.1.50:1883", "tcp://127.0.0.1:1883")
            open(p, "w").write(t)
            open(os.path.join(d, "mosquitto.conf"), "w").write("listener 1883 127.0.0.1\nallow_anonymous true\n")
            open(os.path.join(d, "docker-compose.yml"), "w").write(COMPOSE)
        self.dir_pila = d
        if self.a.sin_pila:
            return
        if not shutil.which("docker"):
            sys.exit("falta docker")
        subprocess.run(["docker", "compose", "-p", "l10prueba", "down", "-v"], cwd=d, capture_output=True)
        r = subprocess.run(["docker", "compose", "-p", "l10prueba", "up", "-d"], cwd=d, capture_output=True, text=True)
        if r.returncode:
            sys.exit("docker compose up: " + r.stderr[-800:])
        t0 = time.time()
        while time.time() - t0 < 120:
            try:
                self.login()
                log("ChirpStack listo (%.0f s)" % (time.time() - t0))
                return
            except Exception:
                time.sleep(2)
        sys.exit("ChirpStack no arranco")

    def login(self):
        import grpc
        from chirpstack_api import api
        c = grpc.insecure_channel(API)
        api.InternalServiceStub(c).Login(api.LoginRequest(email="admin", password="admin"), timeout=3)

    def logs_chirpstack(self, desde: float, n=40):
        r = subprocess.run(["docker", "compose", "-p", "l10prueba", "logs", "--no-color", "--since",
                            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(desde)), "chirpstack"],
                           cwd=self.dir_pila, capture_output=True, text=True)
        import re
        return [re.sub(r"\x1b\[[0-9;]*m", "", l) for l in r.stdout.splitlines()][-n:]

    def bajar_pila(self):
        if not self.a.sin_pila:
            subprocess.run(["docker", "compose", "-p", "l10prueba", "down", "-v"], cwd=self.dir_pila, capture_output=True)

    # ── MQTT ──────────────────────────────────────────────────────────────────
    def mqtt(self):
        import paho.mqtt.client as mqtt
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        def al_msg(cl, ud, m):
            try:
                d = json.loads(m.payload)
            except ValueError:
                return
            tipo = m.topic.split("/")[-1]
            with self.lock:
                self.eventos.append((time.time(), tipo, d))

        c.on_message = al_msg
        c.on_connect = lambda cl, ud, f, rc, pr: cl.subscribe("application/+/device/+/event/#")
        c.connect("127.0.0.1", 1883)
        c.loop_start()
        self.cli_mqtt = c

    def eventos_desde(self, t, tipo):
        with self.lock:
            return [(te, d) for te, ty, d in self.eventos if ty == tipo and te >= t]

    # ── Aire y pasarela ───────────────────────────────────────────────────────
    def lanzar_pasarela(self):
        self.f_pas = open(os.path.join(self.trabajo, "pasarela.log"), "w")
        self.pasarela = subprocess.Popen([sys.executable, "-u", os.path.join(DISP, "pasarela_lora.py")],
                                         env=self.env, cwd=DISP, stdout=self.f_pas, stderr=subprocess.STDOUT)

    # ── Nodo ──────────────────────────────────────────────────────────────────
    def pot(self, v):
        open(os.path.join(self.trabajo, "pot"), "w").write(str(int(v)))

    def compilar(self, appkey=APPKEY, joineui=JOINEUI, ino=None):
        os.makedirs(PROG + "/fuente", exist_ok=True)
        for f in os.listdir(PROG + "/fuente"):
            os.remove(os.path.join(PROG, "fuente", f))
        t = open(ino or INO, encoding="utf-8").read()
        t = t.replace('JOIN_EUI = "0000000000000000"', 'JOIN_EUI = "%s"' % joineui)
        t = t.replace('APP_KEY  = "00000000000000000000000000000000"', 'APP_KEY  = "%s"' % appkey)
        if self.a.periodo_ms:
            t = t.replace("PERIODO_MS 600000UL", "PERIODO_MS %dUL" % self.a.periodo_ms)
        open(PROG + "/fuente/esp32plc_lora_pasarela.ino", "w").write(t)
        r = subprocess.run([sys.executable, os.path.join(DISP, "compilar.py")], env=self.env, cwd=DISP,
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit("no compila el .ino:\n" + r.stdout + r.stderr)

    def arrancar_nodo(self):
        """Lo que hace `docker restart` del contenedor del equipo (programa.py nuevo)."""
        self.parar_nodo()
        self.f_nodo = open(os.path.join(self.trabajo, "nodo.log"), "a")
        self.f_nodo.write("---- arranque %s ----\n" % time.strftime("%H:%M:%S"))
        self.f_nodo.flush()
        self.nodo = subprocess.Popen([sys.executable, "-u", os.path.abspath(__file__), "--rol-nodo", self.trabajo],
                                     env=self.env, cwd=DISP, stdout=self.f_nodo, stderr=subprocess.STDOUT)

    def parar_nodo(self):
        if self.nodo and self.nodo.poll() is None:
            self.nodo.send_signal(signal.SIGTERM)
            try:
                self.nodo.wait(5)
            except subprocess.TimeoutExpired:
                self.nodo.kill()
        self.nodo = None
        subprocess.run(["pkill", "-f", PROG + "/programa"], capture_output=True)

    def estado_nodo(self):
        try:
            return json.load(open(os.path.join(self.trabajo, "estado_nodo.json")))
        except (OSError, ValueError):
            return {}

    def lineas_nodo(self, desde=0):
        try:
            return open(os.path.join(self.trabajo, "nodo.log"), errors="replace").read().splitlines()[desde:]
        except OSError:
            return []

    def borrar_estado_modulo(self):
        shutil.rmtree(PROG, ignore_errors=True)

    # ── Provision ─────────────────────────────────────────────────────────────
    def provisionar(self, *extra):
        extra = [x for x in extra if not (self.a.provisionador and x == "--recrear")]
        r = subprocess.run([sys.executable, self.a.provisionador or os.path.join(AQUI, "l10_provisionar.py"), "--servidor", API,
                            "--deveui", DEVEUI, "--joineui", JOINEUI, "--appkey", APPKEY, *extra],
                           capture_output=True, text=True, env=os.environ)
        if r.returncode:
            sys.exit("provisionar: " + r.stderr[-800:])
        return r.stdout

    # ── Esperas ───────────────────────────────────────────────────────────────
    def espera_union(self, t0, limite):
        while time.time() - t0 < limite:
            ev = self.eventos_desde(t0, "join")
            if ev:
                return ev[0][0] - t0
            time.sleep(0.5)
        return None

    def espera_up(self, t0, limite, n=1):
        while time.time() - t0 < limite:
            ev = self.eventos_desde(t0, "up")
            if len(ev) >= n:
                return ev[n - 1][0] - t0, ev[n - 1][1]
            time.sleep(0.5)
        return None, None

    def cerrar(self):
        self.parar_nodo()
        if self.pasarela and self.pasarela.poll() is None:
            self.pasarela.terminate()
        try:
            self.cli_mqtt.loop_stop()
        except Exception:
            pass


def decodificar(d):
    """(temp, nivel) del objeto decodificado por ChirpStack, o de los bytes si no hay."""
    o = d.get("object") or {}
    return o


def trama_hex(d):
    return base64.b64decode(d.get("data", "")).hex().upper()


def escenario(b: Banco, nombre: str):
    a = b.a
    res = {"escenario": nombre}
    log("=== escenario", nombre)
    b.borrar_estado_modulo()
    b.compilar()
    b.pot(307)                                  # ~30,0 (307/1023*1000 = 300 decimas)
    t0 = time.time()
    if nombre == "provision-primero":
        b.provisionar()
        log("dispositivo creado en ChirpStack")
        t0 = time.time()
        b.arrancar_nodo()
    elif nombre == "nodo-primero":
        b.arrancar_nodo()
        espera = a.espera_previa
        log("el nodo arranca sin dispositivo en ChirpStack; espero %d s" % espera)
        time.sleep(espera)
        res["intentos_sin_dispositivo"] = sum(1 for l in b.lineas_nodo() if "Join rechazado" in l)
        t0 = time.time()
        b.provisionar()
        log("dispositivo creado en ChirpStack")
    elif nombre in ("recrear", "reprogramar", "preparar", "reprovisionar"):
        b.provisionar()
        t00 = time.time()
        b.arrancar_nodo()
        tj = b.espera_union(t00, a.limite)
        tu, _ = b.espera_up(t00, a.limite)
        res["union_inicial_s"] = None if tj is None else round(tj, 1)
        if tj is None or tu is None:
            return res
        log("unido; ahora", nombre)
        time.sleep(3)
        t0 = time.time()
        if nombre == "recrear":
            b.provisionar("--recrear")
        elif nombre == "reprovisionar":
            b.provisionar()
            time.sleep(a.espera_previa)         # tiempo de sobra para que, si se perdiera la sesion, se notara
        elif nombre == "preparar":
            b.parar_nodo()
            b.borrar_estado_modulo()
            b.compilar()
            b.arrancar_nodo()
        else:
            b.arrancar_nodo()
        if nombre == "reprovisionar":
            res["uniones_nuevas"] = len(b.eventos_desde(t0, "join"))
            tu, up = b.espera_up(t0, a.limite)
            res["t_primer_up_s"] = None if tu is None else round(tu, 1)
            res["ok"] = res["uniones_nuevas"] == 0 and up is not None
            return res
    tj = b.espera_union(t0, a.limite)
    res["t_union_s"] = None if tj is None else round(tj, 1)
    tu, up = b.espera_up(t0, a.limite)
    res["t_primer_up_s"] = None if tu is None else round(tu, 1)
    if up:
        res["fcnt"] = up.get("fCnt")
        res["hex"] = trama_hex(up)
        res["decodificado"] = decodificar(up)
        res["devAddr"] = up.get("deviceInfo", {}).get("devEui"), up.get("devAddr")
    # el potenciometro cambia -> el payload decodificado cambia
    if up:
        b.pot(716)                              # ~70,0
        t1 = time.time()
        t_ant = (up.get("object") or {}).get("temperatura")
        for _ in range(int(a.limite)):
            ev = [e for e in b.eventos_desde(t1, "up")
                  if (e[1].get("object") or {}).get("temperatura") not in (None, t_ant)]
            if ev:
                res["hex_tras_pot"] = trama_hex(ev[0][1])
                res["decodificado_tras_pot"] = decodificar(ev[0][1])
                res["t_cambio_pot_s"] = round(ev[0][0] - t1, 1)
                break
            time.sleep(1)
    res["ok"] = bool(up) and "hex_tras_pot" in res
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rol-nodo", metavar="TRABAJO", help=argparse.SUPPRESS)
    ap.add_argument("--escenarios", default="nodo-primero,provision-primero,reprovisionar,recrear,reprogramar,preparar")
    ap.add_argument("--periodo-ms", type=int, default=20000, help="periodo de envio del sketch (demo); 0 = el del sketch (10 min)")
    ap.add_argument("--espera-previa", type=int, default=75, help="s que el nodo corre sin dispositivo (nodo-primero)")
    ap.add_argument("--limite", type=float, default=300, help="s maximos de espera por hito")
    ap.add_argument("--trabajo", default="")
    ap.add_argument("--provisionador", default="", help=argparse.SUPPRESS)
    ap.add_argument("--sin-pila", action="store_true", help="ya hay un ChirpStack en 127.0.0.1:8080 y mosquitto en 1883")
    ap.add_argument("--mantener", action="store_true", help="no bajar la pila al terminar")
    a = ap.parse_args()
    if a.rol_nodo:
        return rol_nodo(a.rol_nodo)
    b = Banco(a)
    resultados = []
    try:
        b.pila()
        b.mqtt()
        b.lanzar_pasarela()
        for n in a.escenarios.split(","):
            n = n.strip()
            r = escenario(b, n)
            resultados.append(r)
            log(json.dumps(r, ensure_ascii=False))
            b.parar_nodo()
        print("\n=== RESUMEN")
        for r in resultados:
            print(json.dumps(r, ensure_ascii=False))
        print("trabajo:", b.trabajo)
        ok = all(r.get("ok") for r in resultados)
        print("RESULTADO:", "OK" if ok else "FALLA")
        return 0 if ok else 1
    finally:
        b.cerrar()
        if not a.mantener:
            b.bajar_pila()


if __name__ == "__main__":
    sys.exit(main())
