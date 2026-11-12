"""Pruebas sin Docker de los equipos simulados: Modbus (PDU, RTU, TCP con MBAP roto), MQTT
minimo (reconexion, paquetes mal formados), vigilante de tareas y decodificador de tramas.

    python3 tablero/herramientas/prueba_dispositivos.py        (sale con 1 si algo falla)
"""
import asyncio
import os
import random
import struct
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "dispositivos"))
sys.path.insert(0, os.path.join(RAIZ, "pasarela"))
os.environ.setdefault("TAB_ID", "t1.controllino")

import modbus_mini as mb  # noqa: E402
from modbus_mini import Mapa  # noqa: E402
from mqtt_mini import ClienteMQTT  # noqa: E402

fallos = []


def ok(cond, nombre, det=""):
    print(("  ok    " if cond else "  FALLA ") + nombre + (" · %s" % det if det and not cond else ""))
    if not cond:
        fallos.append(nombre)


def exc(r, fc, cod):
    return r == bytes([fc | 0x80, cod])


def prueba_pdu():
    print("Modbus PDU")
    escritas = []
    m = Mapa(bobinas=40, discretas=21, holding=16, entrada=17, al_escribir=lambda *a: escritas.append(a))
    ok(m.procesar(b"") == b"", "PDU vacia -> sin respuesta")
    ok(exc(m.procesar(bytes([0x2B, 0, 0])), 0x2B, 1), "funcion 0x2B -> excepcion 1")
    ok(exc(m.procesar(bytes([0x00])), 0x00, 1), "funcion 0 -> excepcion 1")
    for fc in (1, 2, 3, 4):
        ok(exc(m.procesar(bytes([fc, 0, 0])), fc, 3), "FC%d truncada -> excepcion 3" % fc)
        ok(exc(m.procesar(struct.pack(">BHH", fc, 0, 0)), fc, 3), "FC%d cantidad 0 -> excepcion 3" % fc)
        ok(exc(m.procesar(struct.pack(">BHH", fc, 0, 0xFFFF)), fc, 3), "FC%d cantidad 65535 -> excepcion 3" % fc)
        ok(exc(m.procesar(struct.pack(">BHH", fc, 0xFFFF, 1)), fc, 2), "FC%d direccion 65535 -> excepcion 2" % fc)
    ok(exc(m.procesar(struct.pack(">BHH", 5, 0, 0x1234)), 5, 3), "FC5 valor 0x1234 -> excepcion 3")
    ok(exc(m.procesar(struct.pack(">BHH", 5, 999, 0xFF00)), 5, 2), "FC5 dir fuera -> excepcion 2")
    ok(exc(m.procesar(struct.pack(">BHH", 6, 999, 1)), 6, 2), "FC6 dir fuera -> excepcion 2")
    # FC15/16: nada se escribe si la PDU es incoherente
    escritas.clear()
    antes = list(m.bobinas), list(m.holding)
    casos = {
        "FC15 nb no cuadra": struct.pack(">BHHB", 15, 0, 16, 1) + b"\xff",
        "FC15 truncada": struct.pack(">BHHB", 15, 0, 16, 2) + b"\xff",
        "FC15 n=0": struct.pack(">BHHB", 15, 0, 0, 0),
        "FC15 n enorme": struct.pack(">BHHB", 15, 0, 5000, 0),
        "FC15 sin cuerpo": b"\x0f\x00",
        "FC16 nb != 2n": struct.pack(">BHHB", 16, 0, 2, 2) + b"\0\1",
        "FC16 truncada": struct.pack(">BHHB", 16, 0, 2, 4) + b"\0\1",
        "FC16 n=0": struct.pack(">BHHB", 16, 0, 0, 0),
        "FC16 n=124": struct.pack(">BHHB", 16, 0, 124, 248) + bytes(248),
    }
    for nom, pdu in casos.items():
        r = m.procesar(pdu)
        ok(len(r) == 2 and r[0] & 0x80 and r[1] in (2, 3), nom + " -> excepcion", repr(r))
    ok(antes == (m.bobinas, m.holding) and not escritas, "PDU incoherente no escribe nada (sin escritura a medias)")
    r = m.procesar(struct.pack(">BHHB", 15, 0, 10, 2) + b"\xff\x01")
    ok(r == struct.pack(">BHH", 15, 0, 10) and m.bobinas[:10] == [1] * 9 + [1] if False else r == struct.pack(">BHH", 15, 0, 10), "FC15 valida contesta eco")
    ok(m.bobinas[:10] == [1] * 8 + [1, 0], "FC15 valida escribe bien")
    r = m.procesar(struct.pack(">BHHB", 16, 2, 2, 4) + b"\x12\x34\x56\x78")
    ok(m.holding[2:4] == [0x1234, 0x5678] and r == struct.pack(">BHH", 16, 2, 2), "FC16 valida")
    # Fuzz: ninguna PDU aleatoria debe lanzar excepcion
    rnd = random.Random(1)
    malas = 0
    for _ in range(20000):
        pdu = bytes(rnd.getrandbits(8) for _ in range(rnd.randint(0, 20)))
        if rnd.random() < 0.7 and pdu:
            pdu = bytes([rnd.choice((1, 2, 3, 4, 5, 6, 15, 16))]) + pdu[1:]
        try:
            m.procesar(pdu)
        except Exception:
            malas += 1
    ok(malas == 0, "fuzz de 20000 PDU sin excepciones", "%d lanzaron" % malas)


def prueba_rtu():
    print("Modbus RTU / respuestas")
    ok(mb.crc16(b"\x01\x03\x00\x00\x00\x0a") == 0xCDC5, "CRC16 de referencia (01 03 00 00 00 0A -> C5 CD)")
    t = mb.trama_rtu(1, b"\x03\x00\x00\x00\x0a")
    ok(mb.abrir_rtu(t) == (1, b"\x03\x00\x00\x00\x0a"), "ida y vuelta")
    ok(mb.abrir_rtu(t[:-1] + bytes([t[-1] ^ 1])) is None, "CRC roto -> None")
    for n in range(0, 4):
        ok(mb.abrir_rtu(t[:n]) is None, "trama de %d B -> None" % n)
    for pdu in (b"", b"\x01", b"\x01\x05", b"\x03\x04\x00", b"\x81\x02"):
        try:
            a, b = mb.bits_de_respuesta(pdu, 12), mb.regs_de_respuesta(pdu)
            ok(True, "respuesta truncada %r no revienta" % pdu)
            if pdu[:1] in (b"\x01", b"\x03"):
                ok(a is None or len(a) == 12, "bits de %r coherentes" % pdu)
        except Exception as e:
            ok(False, "respuesta truncada %r" % pdu, repr(e))
    ok(mb.bits_de_respuesta(b"\x02\x01\xff", 12) is None, "bits_de_respuesta con menos datos que n -> None")


async def pet_tcp(puerto, crudo, espera=0.5):
    r, w = await asyncio.open_connection("127.0.0.1", puerto)
    w.write(crudo)
    await w.drain()
    try:
        datos = await asyncio.wait_for(r.read(300), espera)
    except asyncio.TimeoutError:
        datos = None
    w.close()
    return datos


async def prueba_tcp():
    print("Modbus TCP (MBAP roto)")
    m = Mapa(bobinas=8, holding=4, entrada=2, discretas=2)
    contador = {}
    srv = await mb.servidor_tcp(m, 1, 0, contador)
    puerto = srv.sockets[0].getsockname()[1]
    loop = asyncio.get_running_loop()
    errores = []
    loop.set_exception_handler(lambda l, c: errores.append(c.get("message")))
    r = await pet_tcp(puerto, struct.pack(">HHHB", 1, 0, 6, 1) + struct.pack(">BHH", 3, 0, 2))
    ok(r is not None and r[7] == 3 and r[8] == 4, "lectura valida contesta", repr(r))
    r = await pet_tcp(puerto, struct.pack(">HHHB", 1, 0, 0, 1))
    ok(r in (b"", None), "MBAP con longitud 0: conexion cerrada, sin respuesta", repr(r))
    r = await pet_tcp(puerto, struct.pack(">HHHB", 1, 0, 65535, 1) + b"x")
    ok(r in (b"", None), "MBAP con longitud 65535: se corta", repr(r))
    r = await pet_tcp(puerto, b"\x00\x01\x00")
    ok(r in (b"", None), "cabecera corta y cierre")
    r = await pet_tcp(puerto, struct.pack(">HHHB", 1, 0, 2, 1) + b"\xee")
    ok(r is not None and r[7:9] == bytes([0xEE | 0x80, 1]), "FC desconocida -> excepcion 1 por TCP", repr(r))
    # Dos peticiones pegadas en un mismo segmento TCP
    p1 = struct.pack(">HHHB", 7, 0, 6, 1) + struct.pack(">BHH", 3, 0, 1)
    p2 = struct.pack(">HHHB", 8, 0, 6, 1) + struct.pack(">BHH", 3, 1, 1)
    r = await pet_tcp(puerto, p1 + p2)
    ok(r is not None and len(r) == 2 * 11, "dos peticiones pegadas -> dos respuestas", repr(r and len(r)))
    # Una callback que revienta no debe tumbar la conexion
    def malo(*a):
        raise RuntimeError("fallo del equipo")
    m.al_escribir = malo
    r = await pet_tcp(puerto, struct.pack(">HHHB", 9, 0, 6, 1) + struct.pack(">BHH", 6, 0, 5))
    ok(r is not None and r[7:9] == bytes([0x86, 4]), "fallo interno -> excepcion 4 (fallo del esclavo)", repr(r))
    await asyncio.sleep(0.1)
    ok(not errores, "ninguna excepcion sin atender en el bucle", str(errores))
    srv.close()


async def prueba_mqtt():
    print("MQTT minimo")
    conexiones = []
    recibido = []

    async def broker(lector, escritor):
        conexiones.append(escritor)
        try:
            cab = await lector.readexactly(1)
            n = (await lector.readexactly(1))[0]
            await lector.readexactly(n)
            escritor.write(b"\x20\x02\x00\x00")
            # PUBLISH mal formado (cuerpo de 1 B) y otro bueno despues
            escritor.write(b"\x30\x01\x00")
            escritor.write(b"\x30" + bytes([2 + 1 + 2]) + b"\x00\x01t" + b"hi")
            await escritor.drain()
            await asyncio.sleep(0.3)
            if len(conexiones) == 1:
                escritor.close()                    # cae el broker: el cliente tiene que enterarse
            else:
                await asyncio.sleep(1)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        del cab

    srv = await asyncio.start_server(broker, "127.0.0.1", 0)
    puerto = srv.sockets[0].getsockname()[1]
    c = ClienteMQTT("prueba", keepalive=1)
    c.al_mensaje = lambda t, p: recibido.append((t, p))
    ok(await c.conectar("127.0.0.1", puerto), "conecta")
    await asyncio.sleep(0.15)
    ok(recibido == [("t", b"hi")], "ignora el PUBLISH truncado y entrega el siguiente", repr(recibido))
    await asyncio.sleep(0.6)
    ok(not c.conectado, "detecta la caida del broker")
    ok(await c.conectar("127.0.0.1", puerto), "reconecta")
    await asyncio.sleep(0.15)
    ok(recibido.count(("t", b"hi")) == 2, "tras reconectar sigue recibiendo", repr(recibido))
    tareas = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    ok(len(tareas) <= 5, "no se acumulan tareas lectoras/ping viejas", "%d" % len(tareas))
    # al_mensaje que falla no mata al lector
    c.al_mensaje = lambda t, p: 1 / 0
    c.cerrar()
    ok(await c.conectar("127.0.0.1", puerto), "reconecta con al_mensaje roto")
    await asyncio.sleep(0.2)
    ok(c.conectado, "al_mensaje que lanza no cierra la conexion")
    c.cerrar()
    srv.close()
    ok(not await c.conectar("127.0.0.1", 1, timeout=0.5), "broker ausente -> False (sin excepcion)")


async def prueba_base():
    print("Vigilante de tareas (base.Equipo.lanzar)")
    import base
    eq = base.Equipo()
    n = {"v": 0}

    async def inestable():
        n["v"] += 1
        if n["v"] < 3:
            raise ValueError("trama rara")
        n["fin"] = True

    t = eq.lanzar(inestable, "inestable")
    for _ in range(50):
        await asyncio.sleep(0.1)
        if n.get("fin"):
            break
    ok(n.get("fin") and n["v"] == 3, "una tarea que lanza excepcion se relanza (3 intentos)", str(n))
    ok(any("se reinicia" in l for l in eq.log), "el fallo queda anotado en la consola del equipo")
    t.cancel()
    # Equipo real: HR3 (esclavo remoto) fuera de rango en el maestro del Controllino
    import controllino
    c = controllino.Controllino()
    c.mapa.holding[0] = 4
    c.mapa.holding[3] = 300
    c._escribir_tcp = lambda esclavo, pdu: asyncio.sleep(0, result=None)
    tarea = c.lanzar(c._bucle_maestro)
    await asyncio.sleep(0.3)
    ok(not tarea.done(), "maestro del Controllino sigue vivo con HR3=300")
    ok(not any("fallo" in l for l in c.log), "sin fallos al armar la trama con HR3=300", str(c.log[-2:]))
    tarea.cancel()
    c.trama_485(c.mapa.holding[2], b"")      # PDU vacia por RS-485
    c.trama_485(c.mapa.holding[2], b"\x03")  # truncada
    ok(True, "trama RS-485 vacia / truncada no revienta")


def prueba_tramas():
    print("Decodificador de tramas")
    import tramas
    rnd = random.Random(2)
    malas = 0
    for _ in range(5000):
        pdu = bytes(rnd.getrandbits(8) for _ in range(rnd.randint(0, 16)))
        if pdu and rnd.random() < 0.8:
            pdu = bytes([rnd.choice((1, 2, 3, 4, 5, 6, 15, 16, 0x81, 0x83))]) + pdu[1:]
        for pet in (True, False):
            try:
                tramas.pdu_modbus(pdu, pet)
            except Exception:
                malas += 1
    ok(malas == 0, "pdu_modbus con 10000 PDU aleatorias sin excepciones", "%d" % malas)


def prueba_verificador():
    print("Autocorrector (practica.json incompleto)")
    sys.path.insert(0, os.path.join(RAIZ, "panel"))
    import verificador

    class Ctx(verificador.Contexto):
        def equipo(self, n): return {"do": [0, 1], "di": [], "ai": []}
        def orden(self, n, o): pass
        def serie(self, n): return ""
        def mqtt(self): return []

    p = {"verificacion": [
        {"txt": "falta i", "hacer": [{"tipo": "entrada", "equipo": "t1.controllino", "v": 1}]},
        {"txt": "regex rota", "hacer": [{"tipo": "serie", "equipo": "x", "regex": "([", "max_ms": 10}]},
        {"txt": "tipo raro", "hacer": [{"tipo": "volar"}]},
        {"txt": "indice no numerico", "hacer": [{"tipo": "esperar", "equipo": "x", "do": {"a": 1}, "max_ms": 10}]},
        {"hacer": [{"tipo": "pausa", "ms": 1}]},
        {"txt": "bien", "hacer": [{"tipo": "esperar", "equipo": "x", "do": {"1": 1}, "max_ms": 10}]}]}
    try:
        r = verificador.correr(p, Ctx(), dormir=lambda s: None)
        ok(len(r) == 6, "los 6 pasos dan resultado aunque haya pasos mal definidos", str(len(r)))
        ok([x["ok"] for x in r] == [False, False, False, False, True, True], "solo fallan los mal definidos", str([x["ok"] for x in r]))
    except Exception as e:
        ok(False, "correr() no debe lanzar con pasos mal definidos", repr(e))
    ok(verificador.correr({}, Ctx()) == [], "practica sin «verificacion» -> lista vacia")


def main():
    prueba_verificador()
    prueba_pdu()
    prueba_rtu()
    prueba_tramas()
    asyncio.run(prueba_tcp())
    asyncio.run(prueba_mqtt())
    asyncio.run(prueba_base())
    print("\n%s" % ("TODO BIEN" if not fallos else "FALLOS %d: %s" % (len(fallos), fallos)))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
