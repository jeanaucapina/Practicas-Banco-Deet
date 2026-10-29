#!/usr/bin/env python3
"""Servidor OPC UA del banco: la pasarela entre el PLC (Modbus TCP) y los clientes OPC UA.

El ESP32 PLC de la L7 habla Modbus TCP: registros de 16 bits sin nombre ni unidad. Este
servidor publica los que tu modelo.json declara como NODOS OPC UA con nombre, tipo y
permisos, para que UaExpert, Ignition, FUXA o un script con asyncua los naveguen,
se suscriban y escriban. Es una pasarela Modbus <-> OPC UA, como las de planta.

Tu modelo (modelo.json, en esta carpeta; reinicia el contenedor tras editarlo):

    {"objeto": "Tablero1", "nodeid": "numerico" | "texto", "interbloqueo": "Remote",
     "variables": [{"nombre": "Potenciometro", "nodeid": 1011, "tipo": "UInt16",
                    "registro": 0, "escribible": false, "valor": 0}, ...]}

  nodeid     "numerico": ns=2;i=<nodeid de cada variable>.  "texto": ns=2;s=<objeto>.<nombre>.
  registro   holding del ESP32 PLC (0-9; 8 y 9 = pulsadores). Sin registro, la variable vive solo en el servidor.
  escribible el cliente puede escribirla; si tiene registro, la escritura baja al PLC.
  interbloqueo  variable booleana de «control remoto»: mientras valga false, el servidor
             RECHAZA las escrituras de los clientes hacia el PLC (las deshace).
  tipo       Boolean | UInt16 | Int32 | Double.   Un Boolean con registro: 0 = false, otro = true.

Endpoints: opc.tcp://localhost:4841/banco/  con None, Basic256Sha256 Sign y
Basic256Sha256 Sign&Encrypt (certificado autofirmado en pki/: UaExpert pide confiar en él).
Los contadores del autocorrector salen en http://192.168.1.64:8096/api/estado.
"""
import asyncio
import json
import os
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from asyncua import Server, ua
from pymodbus.client import AsyncModbusTcpClient

AQUI = pathlib.Path(__file__).resolve().parent
MODELO = AQUI / os.environ.get("OPCUA_MODELO", "modelo.json")
PLC_HOST, PLC_PORT = (os.environ.get("OPCUA_PLC", "192.168.1.10:502").split(":") + ["502"])[:2]
PLC_PORT = int(PLC_PORT)
PERIODO_S = 0.5
APP_URI = "urn:ucuenca:banco:opcua"
TIPOS = {"Boolean": ua.VariantType.Boolean, "UInt16": ua.VariantType.UInt16,
         "Int32": ua.VariantType.Int32, "Double": ua.VariantType.Double}

ESTADO = {"ok": True, "plc": False, "sesiones_max": 0, "suscripciones_max": 0,
          "escrituras": 0, "rechazadas": 0, "nodos": []}


class Estado(BaseHTTPRequestHandler):
    def do_GET(self):
        cuerpo = json.dumps(ESTADO).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *a):
        pass


def cargar_modelo():
    try:
        m = json.loads(MODELO.read_text(encoding="utf-8-sig"))
        assert isinstance(m["variables"], list)
        for v in m["variables"]:
            assert v["tipo"] in TIPOS, "tipo %r no valido (usa Boolean, UInt16, Int32 o Double)" % v["tipo"]
            assert re_nombre(v["nombre"]), "nombre %r no valido" % v["nombre"]
            if "registro" in v:
                assert 0 <= int(v["registro"]) <= 9, "registro fuera de 0-9 en %s" % v["nombre"]
            if m.get("nodeid", "numerico") == "numerico":
                assert isinstance(v.get("nodeid"), int), "falta el nodeid numerico de %s" % v["nombre"]
        return m
    except (OSError, ValueError, KeyError, AssertionError) as e:
        print("ERROR en %s: %s" % (MODELO.name, e), flush=True)
        sys.exit(2)


def re_nombre(s):
    return isinstance(s, str) and s.replace("_", "a").isalnum()


def a_variant(valor, tipo):
    t = TIPOS[tipo]
    if tipo == "Boolean":
        valor = bool(valor)
    elif tipo == "Double":
        valor = float(valor)
    else:
        valor = int(valor)
    return ua.Variant(valor, t)


def _contar(srv):
    """Conexiones y suscripciones de clientes (internos de asyncua; si cambian, queda en 0)."""
    try:
        ses = len(srv.bserver.clients)
    except Exception:
        ses = 0
    try:
        sus = len(srv.iserver.subscription_service.subscriptions)
    except Exception:
        sus = 0
    ESTADO["sesiones_max"] = max(ESTADO["sesiones_max"], ses)
    ESTADO["suscripciones_max"] = max(ESTADO["suscripciones_max"], sus)


async def preparar_seguridad(srv):
    """Certificado autofirmado y los tres endpoints de la guia: None, Sign y Sign&Encrypt."""
    try:
        from asyncua.crypto.cert_gen import setup_self_signed_certificate
        from cryptography.x509.oid import ExtendedKeyUsageOID
        pki = AQUI / "pki"
        pki.mkdir(exist_ok=True)
        clave, cert = pki / "servidor_clave.pem", pki / "servidor.der"
        await setup_self_signed_certificate(clave, cert, APP_URI, "localhost",
                                            [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH],
                                            {"countryName": "EC", "organizationName": "Universidad de Cuenca"})
        await srv.load_certificate(cert)
        await srv.load_private_key(clave)
        srv.set_security_policy([ua.SecurityPolicyType.NoSecurity,
                                 ua.SecurityPolicyType.Basic256Sha256_Sign,
                                 ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt])
    except Exception as e:                     # sin certificado, solo el endpoint sin seguridad
        print("AVISO: sin endpoints seguros (%s)" % e, flush=True)


async def main():
    m = cargar_modelo()
    threading.Thread(target=lambda: ThreadingHTTPServer(("0.0.0.0", 8096), Estado).serve_forever(),
                     daemon=True).start()
    srv = Server()
    await srv.init()
    srv.set_endpoint("opc.tcp://0.0.0.0:4841/banco/")
    srv.set_server_name("Banco DEET · OPC UA")
    await srv.set_application_uri(APP_URI)
    await preparar_seguridad(srv)
    ns = await srv.register_namespace("http://ucuenca.edu.ec/banco")

    objeto = m.get("objeto", "Tablero1")
    numerico = m.get("nodeid", "numerico") == "numerico"
    obj = await srv.nodes.objects.add_object(f"ns={ns};s={objeto}", f"{ns}:{objeto}")
    nodos = {}                                   # nombre -> (nodo, definicion)
    for v in m["variables"]:
        nid = f"ns={ns};i={v['nodeid']}" if numerico else f"ns={ns};s={objeto}.{v['nombre']}"
        ini = a_variant(v.get("valor", 0), v["tipo"])
        n = await obj.add_variable(nid, f"{ns}:{v['nombre']}", ini)
        if v.get("escribible"):
            await n.set_writable()
        nodos[v["nombre"]] = (n, v)
        ESTADO["nodos"].append({"nombre": v["nombre"], "nodeid": nid.split(";", 1)[1], "tipo": v["tipo"]})

    inter = nodos.get(m.get("interbloqueo", "Remote"))
    plc_c = AsyncModbusTcpClient(PLC_HOST, port=PLC_PORT, timeout=2)
    ultimo, marcas = {}, {}                      # por variable escribible con registro
    async with srv:
        print("Servidor OPC UA en opc.tcp://0.0.0.0:4841/banco/ con %d variables" % len(nodos), flush=True)
        while True:
            try:
                if not plc_c.connected:
                    await plc_c.connect()
                rr = await plc_c.read_holding_registers(0, 10, slave=1)
                if rr.isError():
                    raise RuntimeError("Modbus: %s" % rr)
                regs = list(rr.registers)
                ESTADO["plc"] = True
                for nombre, (n, v) in nodos.items():
                    if "registro" not in v:
                        continue
                    r = int(v["registro"])
                    if not v.get("escribible"):
                        await n.write_value(a_variant(regs[r], v["tipo"]))
                        continue
                    dv = await n.read_data_value()
                    actual, marca = dv.Value.Value, dv.ServerTimestamp
                    if nombre not in ultimo:                         # primera vuelta: el PLC manda
                        ultimo[nombre] = regs[r]
                        await n.write_value(a_variant(regs[r], v["tipo"]))
                        marcas[nombre] = (await n.read_data_value()).ServerTimestamp
                    elif marca != marcas[nombre] or int(actual) != ultimo[nombre]:   # un cliente escribio
                        permitido = inter is None or bool((await inter[0].read_value()))
                        if not permitido:                             # control remoto desactivado
                            ESTADO["rechazadas"] += 1
                            await n.write_value(a_variant(ultimo[nombre], v["tipo"]))
                            marcas[nombre] = (await n.read_data_value()).ServerTimestamp
                            continue
                        w = await plc_c.write_register(r, int(actual) & 0xFFFF, slave=1)
                        if not w.isError():
                            ultimo[nombre], marcas[nombre] = int(actual), marca
                            ESTADO["escrituras"] += 1
                    elif regs[r] != ultimo[nombre]:                  # lo cambio otro (Modbus a mano, el MES)
                        ultimo[nombre] = regs[r]
                        await n.write_value(a_variant(regs[r], v["tipo"]))
                        marcas[nombre] = (await n.read_data_value()).ServerTimestamp
            except Exception as e:
                ESTADO["plc"] = False
                plc_c.close()
            _contar(srv)
            await asyncio.sleep(PERIODO_S)


asyncio.run(main())
