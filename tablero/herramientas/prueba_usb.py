#!/usr/bin/env python3
"""Programar un PLC exige el cable USB del PC (como en el laboratorio).

    python prueba_usb.py [panel_url]

Sin cable: subir, fabrica y monitor serie se niegan. Con el cable pc.usbN <-> tN.<plc>.usb
se sube. Un USB entre dos PLC o entre dos puertos del PC no se acepta. Deja el banco sin cables.
"""
import json
import sys
import urllib.request

PANEL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090"
fallos = 0


def http(ruta, cuerpo=None):
    rq = urllib.request.Request(PANEL + ruta, data=cuerpo, method="POST" if cuerpo is not None else "GET")
    with urllib.request.urlopen(rq, timeout=180) as r:
        return json.load(r)


def montar(cables):
    import time
    http("/api/montar", json.dumps({"limpiar": True, "cables": cables, "ordenes": []}).encode())
    time.sleep(2.5)


def ver(texto, ok, extra=""):
    global fallos
    fallos += 0 if ok else 1
    print("  %-4s %s  %s" % ("OK" if ok else "FALLO", texto, extra))


def usb(eq):
    return bool(((http("/api/estado")["pasarela"]["equipos"] or {}).get(eq) or {}).get("usb"))


for eq, ej in [("t1.controllino", "controllino_modbus_tcp"), ("t1.esp32plc", "esp32plc_mqtt")]:
    montar([])
    d = http("/api/subir_ejemplo?equipo=%s&ejemplo=%s" % (eq, ej), b"")
    ver("%s sin USB: no sube" % eq, not d.get("ok") and "USB" in json.dumps(d, ensure_ascii=False),
        str(d.get("error") or d.get("salida", ""))[:90])
    s = http("/api/serie?equipo=" + eq)
    ver("%s sin USB: monitor serie avisa" % eq, "USB" in json.dumps(s, ensure_ascii=False))
    montar([["pc.usb1", eq + ".usb"]])
    ver("%s: la pasarela ve el USB" % eq, usb(eq))
    d = http("/api/subir_ejemplo?equipo=%s&ejemplo=%s" % (eq, ej), b"")
    ver("%s con USB: sube" % eq, bool(d.get("ok")), str(d.get("error") or "")[:90])
    http("/api/fabrica?equipo=" + eq, b"")

montar([["t1.controllino.usb", "t2.controllino.usb"]])
ver("USB entre dos PLC: rechazado", not usb("t1.controllino") and not usb("t2.controllino"))
montar([])
print("FALLOS:", fallos)
sys.exit(1 if fallos else 0)
