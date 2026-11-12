#!/usr/bin/env python3
"""Flujo de referencia de la practica L10, Parte V (Listado L10.6) para un Node-RED del banco.

    python l10_flujo_referencia.py [poner|quitar] [http://127.0.0.1:1890]

Despliega la pestana «L10 referencia» por la API de administracion de Node-RED:
mqtt in  application/+/device/+/event/up  (broker 192.168.1.50, JSON)
  -> function (practicas/L10/pc/funcion_nodered_l10.js, una salida con [[m1..m4]])
  -> mqtt out (sin tema fijo)  ->  planta/lorawan/{temperatura,nivel,alarma,calidad}
Es lo que hace el alumno a mano; sirve a la demostracion del docente («MONTAR SOLUCION COMPLETA»)
y a probar el autocorrector. «quitar» borra la pestana. El panel lo importa (desplegar()).
"""
import json
import os
import sys
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
TAB = "l10ref"
BROKER = "192.168.1.50"


def flujo(broker: str = BROKER) -> dict:
    with open(os.path.join(AQUI, "..", "practicas", "L10", "pc", "funcion_nodered_l10.js"), encoding="utf-8") as f:
        funcion = f.read()
    return {
        "id": TAB, "label": "L10 referencia",
        "configs": [{"id": "l10ref_broker", "type": "mqtt-broker", "name": "broker_banco", "broker": broker,
                     "port": "1883", "clientid": "", "autoConnect": True, "usetls": False, "protocolVersion": "4",
                     "keepalive": "60", "cleansession": True}],
        "nodes": [
            {"id": "l10ref_in", "type": "mqtt in", "z": TAB, "name": "ChirpStack up", "topic": "application/+/device/+/event/up",
             "qos": "0", "datatype": "json", "broker": "l10ref_broker", "nl": False, "rap": True, "rh": 0, "inputs": 0,
             "x": 160, "y": 80, "wires": [["l10ref_fun"]]},
            {"id": "l10ref_fun", "type": "function", "z": TAB, "name": "L10.6 a planta/lorawan", "func": funcion,
             "outputs": 1, "x": 400, "y": 80, "wires": [["l10ref_out"]]},
            {"id": "l10ref_out", "type": "mqtt out", "z": TAB, "name": "", "topic": "", "qos": "", "retain": "",
             "respTopic": "", "contentType": "", "userProps": "", "correl": "", "expiry": "",
             "broker": "l10ref_broker", "x": 640, "y": 80, "wires": []},
        ]}


def _pedir(nr, metodo, ruta, cuerpo=None):
    rq = urllib.request.Request(nr + ruta, method=metodo, data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                headers={"Content-Type": "application/json", "Node-RED-API-Version": "v2"})
    with urllib.request.urlopen(rq, timeout=20) as r:
        t = r.read()
        return json.loads(t) if t else {}


def desplegar(nr: str, accion: str = "poner", broker: str = BROKER):
    nr = nr.rstrip("/")
    try:
        _pedir(nr, "DELETE", "/flow/" + TAB)
    except Exception:
        pass
    if accion == "quitar":
        return {}
    return _pedir(nr, "POST", "/flow", flujo(broker))


if __name__ == "__main__":
    accion = sys.argv[1] if len(sys.argv) > 1 else "poner"
    print(desplegar(sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:1890", accion) or "quitado")
