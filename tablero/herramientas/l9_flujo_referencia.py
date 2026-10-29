#!/usr/bin/env python3
"""Flujo de referencia de la practica L9 (Listados L9.5 y L9.6) para el Node-RED del banco.

    python l9_flujo_referencia.py [poner|quitar] [http://127.0.0.1:1890]

Lo despliega como una pestana aparte («L9 referencia») por la API de administracion:
Modbus-Read FC3 x8 cada 500 ms -> function (L9.5) -> mqtt out, y mqtt in DCMD/KA-104 ->
function (L9.6 B) -> Modbus-Flex-Write FC6 sobre [4]. Sirve para probar el autocorrector
de L9 sin hacer la practica a mano; «quitar» borra la pestana.
"""
import json
import os
import sys
import urllib.request

ACCION = sys.argv[1] if len(sys.argv) > 1 else "poner"
NR = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:1890"
AQUI = os.path.dirname(os.path.abspath(__file__))
TAB = "l9ref"


def pedir(metodo, ruta, cuerpo=None):
    rq = urllib.request.Request(NR + ruta, method=metodo, data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                headers={"Content-Type": "application/json", "Node-RED-API-Version": "v2"})
    with urllib.request.urlopen(rq, timeout=20) as r:
        t = r.read()
        return json.loads(t) if t else {}


if ACCION == "quitar":
    try:
        pedir("DELETE", "/flow/" + TAB)
        print("quitado")
    except Exception as e:
        print("no estaba:", e)
    sys.exit(0)

with open(os.path.join(AQUI, "..", "practicas", "L9", "pc", "funcion_pasarela.js"), encoding="utf-8") as f:
    funcion = f.read()
nodo_b = """const orden = JSON.parse(msg.payload);
if (orden.v !== 0 && orden.v !== 1) { node.warn("Mando fuera de rango, descartado: " + msg.payload); return null; }
msg.payload = { value: orden.v, fc: 6, unitid: 1, address: 4, quantity: 1 };
return msg;"""

flujo = {
    "id": TAB, "label": "L9 referencia",
    "configs": [
        {"id": "l9ref_plc", "type": "modbus-client", "name": "PLC01", "clienttype": "tcp", "bufferCommands": True,
         "stateLogEnabled": False, "queueLogEnabled": False, "failureLogEnabled": True, "tcpHost": "192.168.1.10",
         "tcpPort": "502", "tcpType": "DEFAULT", "serialPort": "/dev/ttyUSB", "serialType": "RTU-BUFFERD",
         "serialBaudrate": "9600", "serialDatabits": "8", "serialStopbits": "1", "serialParity": "none",
         "serialConnectionDelay": "100", "serialAsciiResponseStartDelimiter": "0x3A", "unit_id": "1",
         "commandDelay": "1", "clientTimeout": "1000", "reconnectOnTimeout": True, "reconnectTimeout": "2000",
         "parallelUnitIdsAllowed": True, "showErrors": False, "showWarnings": True, "showLogs": False},
        {"id": "l9ref_broker", "type": "mqtt-broker", "name": "mosquitto_broker", "broker": "mosquitto_broker",
         "port": "1883", "clientid": "pasarela-l9ref", "autoConnect": True, "usetls": False, "protocolVersion": "4",
         "keepalive": "60", "cleansession": True},
    ],
    "nodes": [
        {"id": "l9ref_leer", "type": "modbus-read", "z": TAB, "name": "FC3 x8 / 500 ms", "topic": "",
         "showStatusActivities": False, "logIOActivities": False, "showErrors": False, "showWarnings": True,
         "unitid": "1", "dataType": "HoldingRegister", "adr": "0", "quantity": "8", "rate": "500",
         "rateUnit": "ms", "delayOnStart": False, "startDelayTime": "", "server": "l9ref_plc", "useIOFile": False,
         "ioFile": "", "useIOForPayload": False, "emptyMsgOnFail": False, "x": 150, "y": 80,
         "wires": [["l9ref_fun"], []]},
        {"id": "l9ref_fun", "type": "function", "z": TAB, "name": "L9.5 pasarela", "func": funcion, "outputs": 3,
         "x": 380, "y": 80, "wires": [["l9ref_pub"], ["l9ref_pub"], ["l9ref_pub"]]},
        {"id": "l9ref_pub", "type": "mqtt out", "z": TAB, "name": "", "topic": "", "qos": "", "retain": "",
         "broker": "l9ref_broker", "x": 600, "y": 80, "wires": []},
        {"id": "l9ref_dcmd", "type": "mqtt in", "z": TAB, "name": "DCMD KA-104", "topic": "spBv1.0/Planta1/DCMD/PLC01/KA-104",
         "qos": "1", "datatype": "utf8", "broker": "l9ref_broker", "inputs": 0, "x": 150, "y": 180,
         "wires": [["l9ref_b"]]},
        {"id": "l9ref_b", "type": "function", "z": TAB, "name": "L9.6 B", "func": nodo_b, "outputs": 1,
         "x": 380, "y": 180, "wires": [["l9ref_esc"]]},
        {"id": "l9ref_esc", "type": "modbus-flex-write", "z": TAB, "name": "FC6 [4]", "showStatusActivities": False,
         "showErrors": False, "server": "l9ref_plc", "emptyMsgOnFail": False, "keepMsgProperties": False,
         "x": 600, "y": 180, "wires": [[], []]},
    ],
}
try:
    pedir("DELETE", "/flow/" + TAB)
except Exception:
    pass
print(pedir("POST", "/flow", flujo))
