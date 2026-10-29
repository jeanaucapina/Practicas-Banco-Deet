#!/usr/bin/env python3
"""Barrido de practicas del curso (L1, L3, L6, L7, L9) contra el banco virtual.

Cada practica se hace como la haria un estudiante: cablea (como las manos en el 3D),
sube su .ino, pulsa pulsadores y comprueba el efecto REAL en los equipos (/api/estado
del panel). Sirve para saber que practicas se pueden hacer a distancia ya y cuales
no, antes de que lleguen las guias.

    python prueba_practicas.py [panel_url] [L1 L3 L6 L7 L9]

Deja el banco en fabrica y sin cables.
"""
import json
import os
import sys
import time
import urllib.request

PANEL = "http://localhost:8090"
args = [x for x in sys.argv[1:]]
if args and args[0].startswith("http"):
    PANEL = args.pop(0)
SOLO = [x.upper() for x in args]
EJ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ejemplos_arduino")

resultados = []   # (practica, texto, ok, extra)


def http(ruta, cuerpo=None, metodo=None):
    rq = urllib.request.Request(PANEL + ruta, data=cuerpo, method=metodo or ("POST" if cuerpo is not None else "GET"))
    with urllib.request.urlopen(rq, timeout=180) as r:
        return json.load(r)


def estado():
    return http("/api/estado")


def equipo(e):
    return (estado()["pasarela"]["equipos"] or {}).get(e, {})


def orden(eq, o):
    http("/api/orden", json.dumps({"t": "orden", "equipo": eq, "orden": o}).encode())


def montar(cables=(), ordenes=()):
    http("/api/montar", json.dumps({"limpiar": True, "cables": list(cables), "ordenes": list(ordenes)}).encode())
    time.sleep(2.5)


def pulsar(eq, i, seg=1.0):
    orden(eq, {"cmd": "entrada", "i": i, "v": 1})
    time.sleep(seg)
    orden(eq, {"cmd": "entrada", "i": i, "v": 0})
    time.sleep(0.8)


def subir(eq, ej):
    http("/api/preparar?equipo=%s&modo=ino" % eq, b"")
    d = http("/api/subir_ejemplo?equipo=%s&ejemplo=%s" % (eq, ej), b"")
    time.sleep(3.5)
    return d["ok"], d.get("salida", "")


def fabrica(eq):
    http("/api/fabrica?equipo=" + eq, b"")


def serie(eq):
    return http("/api/serie?equipo=" + eq).get("texto", "")


def ok(p, txt, cond, extra=""):
    resultados.append((p, txt, bool(cond), extra))
    print("  %s  %s%s" % ("OK   " if cond else "FALLA", txt, ("   " + extra) if extra else ""))


def espera(f, seg=8.0):
    t0 = time.time()
    while time.time() - t0 < seg:
        v = f()
        if v:
            return v
        time.sleep(0.4)
    return f()


FILAS = {0: (0, 6, 12), 1: (1, 7, 13), 2: (2, 8, 14)}


def fila_encendida(eq):
    do = equipo(eq).get("do", [0] * 24)
    return [f for f, ls in FILAS.items() if all(do[i] for i in ls) and not any(do[j] for g, l2 in FILAS.items() if g != f for j in l2)]


# ── L1: E/S digitales y maquina de estados ──────────────────────────────────
def l1():
    print("L1  E/S digitales y maquina de estados")
    r, out = subir("t1.controllino", "controllino_fsm")
    ok("L1", "controllino_fsm compila y se sube", r, out[-120:] if not r else "")
    ok("L1", "arranca en VERDE (fila de arriba)", espera(lambda: fila_encendida("t1.controllino") == [0]))
    pulsar("t1.controllino", 16)
    ok("L1", "I16 -> AMARILLO (fila del medio)", fila_encendida("t1.controllino") == [1])
    pulsar("t1.controllino", 16)
    ok("L1", "I16 -> ROJO (fila de abajo)", fila_encendida("t1.controllino") == [2])
    pulsar("t1.controllino", 17)
    ok("L1", "I17 vuelve a VERDE", fila_encendida("t1.controllino") == [0])
    ok("L1", "el monitor serie cuenta los estados", "estado: ROJO" in serie("t1.controllino"))
    fabrica("t1.controllino")


# ── L2: HMI tactil (Serial2) ────────────────────────────────────────────────
def l2():
    print("L2  HMI industrial (diseñador + Serial2)")
    ejemplo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hmi", "ejemplo.json")
    with open(ejemplo, "rb") as f:
        http("/api/hmi_cargar?n=1", f.read())
    r, out = subir("t1.controllino", "controllino_hmi")
    ok("L2", "controllino_hmi (Serial2 + tramas A5 5A) compila y se sube", r, out[-120:] if not r else "")
    orden("t1.controllino", {"cmd": "analogica", "i": 0, "v": 700})
    h = espera(lambda: http("/api/hmi?n=1")["vars"].get("32") == 700, 6)
    ok("L2", "el Controllino escribe A0 en la variable 0x0020 de la HMI", h)
    http("/api/hmi_toque?n=1&w=luz&ev=down", b"")
    ok("L2", "tocar el interruptor de la HMI enciende D0", espera(lambda: equipo("t1.controllino")["do"][0] == 1, 4))
    http("/api/hmi_toque?n=1&w=luz&ev=down", b"")
    fabrica("t1.controllino")


# ── L3: RS-485 con tramas propias ───────────────────────────────────────────
def l3():
    print("L3  RS-485 con tramas propias")
    A = [["t1.controllino.485A", "t2.controllino.485A"], ["t1.controllino.485B", "t2.controllino.485B"]]
    X = [["t1.controllino.485A", "t2.controllino.485B"], ["t1.controllino.485B", "t2.controllino.485A"]]
    montar(A)
    r1, o1 = subir("t1.controllino", "controllino_trama485_tx")
    r2, o2 = subir("t2.controllino", "controllino_trama485_rx")
    ok("L3", "TX y RX compilan y se suben", r1 and r2, (o1 + o2)[-120:] if not (r1 and r2) else "")
    time.sleep(2)
    pulsar("t1.controllino", 16, 1.6)
    # el pulsador debe verse en T2 mientras T1 lo manda: se mantiene pulsado
    orden("t1.controllino", {"cmd": "entrada", "i": 16, "v": 1})
    v = espera(lambda: equipo("t2.controllino").get("do", [0])[0] == 1, 6)
    orden("t1.controllino", {"cmd": "entrada", "i": 16, "v": 0})
    ok("L3", "pulsar I16 en T1 enciende D0 en T2 por RS-485", v)
    ok("L3", "T2 valida la trama (XOR y cola)", "trama valida" in serie("t2.controllino"))
    montar(X)
    time.sleep(3)
    ok("L3", "con A/B cruzados T2 rechaza la trama", espera(lambda: "invalida" in serie("t2.controllino")[-300:], 6))
    montar([])
    fabrica("t1.controllino")
    fabrica("t2.controllino")


# ── L6: Modbus RTU maestro-esclavo ──────────────────────────────────────────
def l6():
    print("L6  Modbus RTU maestro-esclavo sobre RS-485")
    montar([["t1.controllino.485A", "t2.controllino.485A"], ["t1.controllino.485B", "t2.controllino.485B"]],
           [["t2.controllino", {"cmd": "modo", "v": 0}]])
    r, out = subir("t1.controllino", "controllino_rtu")
    ok("L6", "controllino_rtu (maestro RTU escrito a mano) compila", r, out[-120:] if not r else "")
    orden("t2.controllino", {"cmd": "entrada", "i": 16, "v": 1})
    v = espera(lambda: equipo("t1.controllino").get("do", [0])[0] == 1, 8)
    orden("t2.controllino", {"cmd": "entrada", "i": 16, "v": 0})
    ok("L6", "pulsar I16 en el esclavo (T2) se lee desde el maestro (T1)", v)
    ok("L6", "el maestro imprime las tramas por serie", "pulsadores remotos" in serie("t1.controllino"))
    montar([])
    fabrica("t1.controllino")


# ── L7: Modbus TCP ──────────────────────────────────────────────────────────
def l7():
    print("L7  Modbus TCP por Ethernet")
    montar([["t1.controllino.eth", "t1.switch.p1"], ["t2.controllino.eth", "t2.switch.p1"],
            ["t1.switch.p2", "t2.switch.p2"]],
           [["t2.controllino", {"cmd": "modo", "v": 0}]])
    r, out = subir("t1.controllino", "controllino_modbus_tcp")
    ok("L7", "controllino_modbus_tcp (maestro TCP a mano) compila", r, out[-120:] if not r else "")
    orden("t2.controllino", {"cmd": "entrada", "i": 17, "v": 1})
    v = espera(lambda: equipo("t1.controllino").get("do", [0] * 3)[1] == 1, 10)
    orden("t2.controllino", {"cmd": "entrada", "i": 17, "v": 0})
    ok("L7", "pulsar I17 en T2 se refleja en D1 de T1 por Modbus TCP", v,
       "" if v else serie("t1.controllino")[-150:])
    tr = [t for t in (estado()["pasarela"].get("tramas") or []) if "FC02" in json.dumps(t) or "Read Discrete" in json.dumps(t)]
    ok("L7", "la pasarela ve la trama MBAP FC02 (la misma que sale en Wireshark)", tr)
    montar([])
    fabrica("t1.controllino")


# ── L9: WiFi + MQTT en el ESP32 PLC ─────────────────────────────────────────
def l9():
    print("L9  WiFi + MQTT (+ Node-RED) en ESP32 PLC")
    http("/api/orden", json.dumps({"t": "wifi", "equipo": "t1.esp32plc", "v": True}).encode())
    r, out = subir("t1.esp32plc", "esp32plc_mqtt")
    ok("L9", "esp32plc_mqtt compila y se sube", r, out[-120:] if not r else "")
    m = espera(lambda: [x for x in estado().get("mqtt", []) if "entradas" in x["tema"]], 15)
    ok("L9", "el ESP32 publica por MQTT (visto en el broker)", m, (m[-1]["tema"] + " " + m[-1]["carga"][:40]) if m else serie("t1.esp32plc")[-150:])
    # Node-RED: ¿hay un contenedor?
    c = estado().get("contenedores", {})
    ok("L9", "Node-RED disponible en el laboratorio (editor + dashboard)", any("nodered" in k for k in c),
       "tab-nodered no existe: lab.ps1 arrancar lo crea")
    http("/api/orden", json.dumps({"t": "wifi", "equipo": "t1.esp32plc", "v": False}).encode())
    fabrica("t1.esp32plc")


# ── L8: PROFINET simulado ───────────────────────────────────────────────────
def pcap_tipos(datos):
    """EtherType -> numero de tramas de un pcap clasico (little endian)."""
    import struct
    cuenta, i = {}, 24
    while i + 16 <= len(datos):
        n = struct.unpack_from("<I", datos, i + 8)[0]
        tr = datos[i + 16:i + 16 + n]
        if len(tr) >= 14:
            et = struct.unpack(">H", tr[12:14])[0]
            cuenta[et] = cuenta.get(et, 0) + 1
        i += 16 + n
    return cuenta


def l8():
    print("L8  PROFINET simulado (DCP / LLDP / RT)")
    c = estado().get("contenedores", {})
    ok("L8", "el simulador PROFINET (tab-pnio) esta en marcha", (c.get("tab-pnio") or {}).get("estado") == "running")
    montar([["t1.controllino.eth", "t1.switch.p1"], ["t2.controllino.eth", "t2.switch.p1"], ["t1.switch.p2", "t2.switch.p2"]])
    time.sleep(3)
    rq = urllib.request.Request(PANEL + "/api/captura?red=tab-lan&seg=14")
    datos = urllib.request.urlopen(rq, timeout=120).read()
    t = pcap_tipos(datos)
    ok("L8", "en tab-lan salen tramas RT cclicas (0x8892)".replace("cclicas", "cíclicas"), t.get(0x8892, 0) > 50, "%d tramas" % t.get(0x8892, 0))
    ok("L8", "salen anuncios LLDP (0x88CC)", t.get(0x88CC, 0) >= 3, "%d tramas" % t.get(0x88CC, 0))
    montar([])
    time.sleep(2)
    rq = urllib.request.Request(PANEL + "/api/captura?red=tab-lan&seg=6")
    t2 = pcap_tipos(urllib.request.urlopen(rq, timeout=120).read())
    ok("L8", "sin cables los dispositivos desaparecen (solo queda el PLC)", t2.get(0x8892, 0) < 5, "%d tramas RT" % t2.get(0x8892, 0))


# ── Lo que el banco aun no tiene ───────────────────────────────────────────
def huecos():
    print("Otras practicas (solo comprobacion de lo que existe)")
    c = estado().get("contenedores", {})
    ok("L4", "captura con Wireshark (tab-lan/tab-wifi/tab-485)", True, "desde el portal")


TODAS = {"L1": l1, "L2": l2, "L3": l3, "L6": l6, "L7": l7, "L8": l8, "L9": l9}
if __name__ == "__main__":
    # Todo el montaje parte de OpenPLC apagado: pisaria las salidas
    for n in ("1", "2"):
        http("/api/preparar?equipo=t%s.controllino&modo=ino" % n, b"")
    for k, f in TODAS.items():
        if not SOLO or k in SOLO:
            try:
                f()
            except Exception as e:
                ok(k, "excepcion durante la practica", False, repr(e))
    if not SOLO:
        huecos()
    montar([])
    print()
    print("Resumen:")
    for p in sorted({r[0] for r in resultados}):
        rs = [r for r in resultados if r[0] == p]
        print("  %-3s %s  (%d/%d)" % (p, "SE PUEDE" if all(r[2] for r in rs) else "FALTA   ", sum(r[2] for r in rs), len(rs)))
    sys.exit(0 if all(r[2] for r in resultados if r[0] in TODAS) else 1)
