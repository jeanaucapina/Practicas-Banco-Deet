"""ESP32 PLC 14 (Industrial Shields) simulado.

Lo que trae el equipo real: entradas I0.x, 4 salidas digitales Q0.0-Q0.3 +
1 rele, Ethernet (W5500), WiFi, RS-485 semiduplex e I2C. En el tablero (etiquetas
inferiores) llegan a las bananas I0.1..I0.8 y Q0.0..Q0.3.

Aqui hace tres papeles a la vez, cada uno para una practica:

  - Esclavo Modbus TCP (L7): mismo estilo de mapa que el Controllino.
  - Maestro Modbus RTU sobre RS-485 (L6): si HR0 = 1 sondea al esclavo HR1
    cada HR2 ms (FC 02 entradas y FC 01 salidas) y guarda lo que lee.
  - Cliente MQTT (L9): publica su estado cada segundo en
        <tablero>/esp32plc/estado
    y obedece a  <tablero>/esp32plc/set/<Q0.0..Q0.3|R0>  con "1" o "0".
    Busca el broker primero por Ethernet y, si no, por WiFi.
  - Pasarela Modbus TCP -> MQTT: lee al Controllino de su tablero
    (192.168.1.1n) dos veces por segundo y publica en
        <tablero>/controllino/estado
    pulsadores I16-I18, entradas A0-A15, salidas D0-D23 y MODO, al momento
    de cada cambio y cada 2 s. Necesita a los dos en la LAN.

Mapa Modbus (base 0):
  Bobinas            0-3  Q0.0..Q0.3     4  R0 (rele)
  Entradas discretas 0-7  I0.1..I0.8
  Registros entrada  0-3  entradas analogicas en cuentas ADC 0-4095
                        0  lleva un sensor 4-20 mA de temperatura simulado
  Holding             0  maestro RTU (0 apagado / 1 encendido)
                      1  direccion del esclavo a sondear (1 = Controllino)
                      2  periodo de sondeo [ms]
                   3-9  libres
                  10-21  espejo de lo que el maestro leyo del esclavo:
                         10 = entradas (bits), 11 = salidas D0..D11 (bits),
                         12 = sondeos OK, 13 = sin respuesta, 14 = excepciones
"""

import asyncio
import json
import math
import os
import struct
import time

from base import TABLERO, Equipo
from modbus_mini import Mapa, bits_de_respuesta, pdu_leer, regs_de_respuesta, servidor_tcp
from mqtt_mini import ClienteMQTT

NOMBRE = os.environ.get("TAB_NOMBRE", "tablero%d" % TABLERO)
BROKERS = [b for b in (os.environ.get("TAB_BROKER_LAN", "192.168.1.50"),) if b]
SALIDAS = ["Q0.0", "Q0.1", "Q0.2", "Q0.3", "R0"]


class Esp32Plc(Equipo):
    nombre = "esp32plc"

    def __init__(self):
        super().__init__()
        self.mapa = Mapa(bobinas=5, discretas=8, holding=24, entrada=4,
                         al_escribir=self._escrito)
        self.mapa.holding[1] = TABLERO      # sondea al Controllino de su tablero
        self.mapa.holding[2] = 1000
        self.peticiones = {"tcp": 0}
        self.mqtt = ClienteMQTT("esp32plc-" + NOMBRE)
        self.mqtt.al_mensaje = self._mqtt_mensaje
        self.broker = ""
        self.t0 = time.time()

    def _escrito(self, tabla, direccion, valor):
        if tabla == "bobina":
            self.anotar("Modbus escribe %s = %d" % (SALIDAS[direccion], valor))
        elif tabla == "holding" and direccion == 0:
            self.anotar("maestro RTU %s" % ("ENCENDIDO" if valor else "apagado"))

    # ── Ordenes de las gafas ──────────────────────────────────────────────────
    def orden(self, d):
        super().orden(d)
        c = d.get("cmd")
        if c == "entrada":
            i = int(d["i"])
            if 0 <= i < 8:
                self.mapa.discretas[i] = 1 if d.get("v") else 0
        elif c == "analogica":
            i = int(d["i"])
            if 0 <= i < 4:
                self.mapa.entrada[i] = max(0, min(4095, int(d["v"])))
                self.mapa.discretas[4 + i] = 1 if self.mapa.entrada[i] > 2048 else 0
        elif c == "maestro":
            self.mapa.holding[0] = 1 if d.get("v") else 0
            self._escrito("holding", 0, self.mapa.holding[0])

    # ── MQTT ──────────────────────────────────────────────────────────────────
    def _mqtt_mensaje(self, tema, carga):
        nombre = tema.rsplit("/", 1)[-1]
        if nombre in SALIDAS:
            v = 1 if carga.strip() in (b"1", b"true", b"on", b"ON") else 0
            self.mapa.bobinas[SALIDAS.index(nombre)] = v
            self.anotar("MQTT %s = %d" % (nombre, v))

    async def _bucle_mqtt(self):
        while True:
            if not self.mqtt.conectado:
                self.broker = ""
                for b in BROKERS:
                    if await self.mqtt.conectar(b, timeout=1.5):
                        self.broker = b
                        self.anotar("MQTT conectado a %s" % b)
                        self.mqtt.suscribir("%s/esp32plc/set/#" % NOMBRE)
                        break
                if not self.mqtt.conectado:
                    await asyncio.sleep(3)
                    continue
            m = self.mapa
            self.mqtt.publicar("%s/esp32plc/estado" % NOMBRE, json.dumps({
                "entradas": m.discretas, "salidas": m.bobinas[:4], "rele": m.bobinas[4],
                "temperatura": round(m.entrada[0] / 4095 * 100, 1),
                "t": int(time.time() - self.t0)}).encode())
            if m.holding[0]:
                self.mqtt.publicar("%s/controllino/entradas" % NOMBRE,
                                   json.dumps({"bits": m.holding[10], "ok": m.holding[12],
                                               "sin_respuesta": m.holding[13]}).encode())
            await asyncio.sleep(1.0)

    # ── Maestro RTU ───────────────────────────────────────────────────────────
    async def _bucle_maestro(self):
        h = self.mapa.holding
        while True:
            if h[0] and self.bus["en_bus"]:
                esclavo = h[1] or 1
                r = await self.preguntar_485(esclavo, pdu_leer(2, 0, 12))
                bits = bits_de_respuesta(r, 12) if r else None
                if r is None:
                    h[13] = (h[13] + 1) & 0xFFFF
                elif bits is None:
                    h[14] = (h[14] + 1) & 0xFFFF
                else:
                    h[10] = sum(b << i for i, b in enumerate(bits))
                    await asyncio.sleep(0.02)   # silencio entre tramas
                    r2 = await self.preguntar_485(esclavo, pdu_leer(1, 0, 12))
                    salidas = bits_de_respuesta(r2, 12) if r2 else None
                    if salidas is not None:
                        h[11] = sum(b << i for i, b in enumerate(salidas))
                        h[12] = (h[12] + 1) & 0xFFFF
            await asyncio.sleep(max(100, min(10000, h[2])) / 1000.0)

    # ── Pasarela Modbus TCP -> MQTT ───────────────────────────────────────────
    async def _pasarela_mqtt(self):
        ip = "192.168.1.%d" % (10 + TABLERO)
        conn, tid, ultimo, t_pub = None, 0, None, 0.0
        while True:
            await asyncio.sleep(0.5)
            if not self.mqtt.conectado:
                continue
            try:
                if conn is None:
                    conn = await asyncio.wait_for(asyncio.open_connection(ip, 502), 1.0)
                r, w = conn
                res = []
                for pdu in (pdu_leer(2, 0, 21), pdu_leer(1, 0, 24), pdu_leer(3, 0, 1)):
                    tid = (tid + 1) & 0xFFFF
                    w.write(struct.pack(">HHHB", tid, 0, len(pdu) + 1, TABLERO) + pdu)
                    await w.drain()
                    cab = await asyncio.wait_for(r.readexactly(7), 1.0)
                    res.append(await asyncio.wait_for(
                        r.readexactly(struct.unpack(">H", cab[4:6])[0] - 1), 1.0))
            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                if conn is not None:
                    conn[1].close()
                conn = None
                continue
            di = bits_de_respuesta(res[0], 21)
            do = bits_de_respuesta(res[1], 24)
            hr = regs_de_respuesta(res[2])
            if di is None or do is None or hr is None:
                continue
            estado = {"pulsadores": {"I16": di[16], "I17": di[17], "I18": di[18]},
                      "entradas": di[:16], "IN": di[19:21], "salidas": do, "modo": hr[0]}
            if estado != ultimo or time.time() - t_pub > 2.0:
                self.mqtt.publicar("%s/controllino/estado" % NOMBRE, json.dumps(estado).encode())
                if ultimo is not None and estado["pulsadores"] != ultimo["pulsadores"]:
                    self.anotar("MQTT: pulsadores %s" % estado["pulsadores"])
                ultimo, t_pub = estado, time.time()

    async def _sensor(self):
        # Temperatura de un horno que sube y baja: 4-20 mA sobre 20..80 °C.
        while True:
            temp = 50 + 25 * math.sin((time.time() - self.t0) / 20.0)
            self.mapa.entrada[0] = int(temp / 100 * 4095)
            await asyncio.sleep(0.5)

    async def iniciar(self):
        await servidor_tcp(self.mapa, 1, 502, self.peticiones)
        for f in (self._bucle_mqtt, self._bucle_maestro, self._sensor, self._pasarela_mqtt):
            asyncio.ensure_future(f())

    def estado(self):
        m = self.mapa
        return {
            "do": m.bobinas[:4], "rele": m.bobinas[4:5], "di": m.discretas,
            "ai": m.entrada, "hr": m.holding[:3] + m.holding[10:15],
            "maestro": m.holding[0], "broker": self.broker,
            "peticiones": self.peticiones,
        }


if __name__ == "__main__":
    asyncio.run(Esp32Plc().correr())
