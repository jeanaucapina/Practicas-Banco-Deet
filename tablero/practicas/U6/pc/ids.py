#!/usr/bin/env python3
"""Taller U6 - Reto (Listado U6.9): IDS minimo por COMPORTAMIENTO (no por firma). Vigila el
segmento con tshark y publica una alarma en planta/seguridad/incidente (por el broker
endurecido, con TLS) cuando detecta: (i) una escritura FC6/FC16 anomala sobre el registro
critico [4] a cadencia de replay; o (ii) una tormenta de difusion. Ejerce el FR6 (respuesta
oportuna a eventos). Es defensa: observa y avisa, no ataca.

    sudo python3 ids.py            # necesita la captura en vivo del segmento
"""
import json
import subprocess
import time

import paho.mqtt.publish as publish

BROKER = "192.168.1.52"
UMBRAL_FC6 = 4            # mas de 4 escrituras/s sobre [4] = anomalo (replay)
CERT = "server.crt"      # el del broker endurecido (misma carpeta)


def alarma(tipo, detalle):
    t = time.time()
    try:
        publish.single("planta/seguridad/incidente", json.dumps({"tipo": tipo, "detalle": detalle, "ts": t}),
                        hostname=BROKER, port=8883, auth={"username": "operador", "password": "banco"},
                        tls={"ca_certs": CERT})
    except Exception as e:
        print("no se pudo publicar la alarma:", e)
    print("[%.3f] ALARMA %s: %s" % (t, tipo, detalle))


def main():
    proc = subprocess.Popen(
        ["tshark", "-i", "eth0", "-l", "-Y", "modbus.func_code==6 && modbus.reference_num==4",
         "-T", "fields", "-e", "frame.time_epoch"],
        stdout=subprocess.PIPE, text=True)
    ventana, cuenta = int(time.time()), 0
    for linea in proc.stdout:
        try:
            seg = int(float(linea))
        except ValueError:
            continue
        cuenta += 1
        if seg != ventana:
            if cuenta > UMBRAL_FC6:
                alarma("escritura_anomala", "%d FC6/s sobre [4]" % cuenta)
            ventana, cuenta = seg, 0


if __name__ == "__main__":
    main()
