#!/usr/bin/env python3
"""HMI STONE virtual + Controllino + EPC (guia L2), contra el banco en marcha.

    python prueba_hmi.py [panel_url]

Descarga el proyecto de ejemplo de la L2 en la HMI del tablero 1, sube el Listado
L2.2 (controllino_stone_epc), marca el EPC como cableado (lo que haria el 3D), mueve
slider1 desde la HMI y mira que la velocidad vuelva a label4 y a la grafica.
"""
import json
import sys
import time
import urllib.request

PANEL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090"
fallos = 0


def http(ruta, cuerpo=None):
    rq = urllib.request.Request(PANEL + ruta, data=cuerpo, method="POST" if cuerpo is not None else "GET")
    with urllib.request.urlopen(rq, timeout=180) as r:
        return json.load(r)


def ver(txt, ok, extra=""):
    global fallos
    fallos += 0 if ok else 1
    print("  %-5s %s  %s" % ("OK" if ok else "FALLO", txt, extra))


def epc():
    http("/api/orden", json.dumps({"t": "orden", "equipo": "t1.controllino", "orden": {"cmd": "epc", "conectado": True}}).encode())


http("/api/montar", json.dumps({"limpiar": True, "cables": [["t1.controllino.usb", "pc.usb1"]], "ordenes": []}).encode())
time.sleep(2.5)
ej = http("/api/hmi_ejemplo")
ver("descarga del proyecto de ejemplo en la HMI", http("/api/hmi_cargar?n=1", json.dumps(ej).encode()).get("ok"))
d = http("/api/subir_ejemplo?equipo=t1.controllino&ejemplo=controllino_stone_epc", b"")
ver("compila y sube el Listado L2.2", d.get("ok"), d.get("salida", "")[-200:] if not d.get("ok") else "")
time.sleep(3)
epc()
http("/api/hmi_toque?n=1&w=slider1&ev=set&v=50", b"")
for _ in range(6):
    time.sleep(1)
    epc()
h = http("/api/hmi?n=1")
rpm = h["textos"].get("label4", "")
ver("slider1 al 50 % -> label2 = 50", h["textos"].get("label2") == "50", h["textos"].get("label2"))
ver("…y label4 ~1600 rpm", rpm.isdigit() and 1400 <= int(rpm) <= 1800, rpm)
s2 = h["series"].get("line_series2", [])
ver("line_series2 recibe la velocidad", bool(s2) and s2[-1] > 1000, str(s2[-3:]))
ver("las ordenes llegan como JSON ST<{...}>ET", any((x.get("txt") or "").startswith('ST<{"cmd_code"') for x in h["log"]))
ver("los eventos salen en binario con cabecera ST<", any((x.get("hex") or "").startswith("53 54 3C") for x in h["log"]))
http("/api/hmi_toque?n=1&w=slider1&ev=set&v=0", b"")
for _ in range(5):
    time.sleep(1)
    epc()
ver("slider1 a 0 -> label4 = 0", http("/api/hmi?n=1")["textos"].get("label4") == "0")
http("/api/fabrica?equipo=t1.controllino", b"")
http("/api/montar", json.dumps({"limpiar": True, "cables": [], "ordenes": []}).encode())
print("FALLOS: %d" % fallos)
sys.exit(1 if fallos else 0)
