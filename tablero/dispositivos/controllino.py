"""CONTROLLINO simulado (mapa de E/S del MEGA, que es el de las etiquetas del
tablero): esclavo Modbus TCP y RTU, y maestro para la practica entre tableros.

Mapa de registros (base 0, como en QModMaster con "offset 0"):

  Bobinas (FC 1/5/15)           0-23  D0..D23   salidas digitales 24 V
                               24-39  R0..R15   reles
  Entradas discretas (FC 2)     0-15  A0..A15   (leidas como digitales)
                               16-18  I16..I18  los tres pulsadores del panel
                               19-20  IN0, IN1  entradas de interrupcion
  Registros de entrada (FC 4)   0-15  A0..A15   valor ADC 0-1023
                                  16  segundos encendido (parte baja)
  Registros holding (FC 3/6/16)    0  MODO  0 esclavo puro
                                            1 espejo (A0..A15 -> D0..D15)
                                            2 secuencia en la matriz 3x3
                                            3 MAESTRO RS-485 (Modbus RTU)
                                            4 MAESTRO Ethernet (Modbus TCP)
                                   1  periodo de la secuencia [ms]
                                   2  mi direccion RTU (por defecto, n.º de tablero)
                                   3  esclavo remoto de los modos 3 y 4
                                      (tablero n -> RTU n, TCP 192.168.1.1n)
                                   4  peticiones OK del maestro
                                   5  peticiones sin respuesta
                                6-15  libres para las practicas

En el tablero (etiquetas superiores), la matriz 3x3 de luminarias es

        D0  D6  D12   [I16]
        D1  D7  D13   [I17]      [..] = pulsadores
        D2  D8  D14   [I18]

Practica de dos tableros: en MODO 3 o 4, el pulsador I16 enciende la fila de
arriba del tablero remoto (D0, D6, D12), I17 la del medio e I18 la de abajo.
El maestro manda un FC 15 (escribir bobinas 0-14) cada vez que cambia un
pulsador y, para refrescar, una vez por segundo.
"""

import asyncio
import os
import struct
import time

from base import TABLERO, Equipo
from modbus_mini import Mapa, servidor_tcp

N_DO, N_REL, N_AI = 24, 16, 16
I_PULS = 16                     # I16..I18 en las discretas 16-18
I_IN = 19                       # IN0, IN1
MATRIZ = [[0, 6, 12], [1, 7, 13], [2, 8, 14]]   # filas de la matriz 3x3
NOMBRE_DI = ["A%d" % i for i in range(16)] + ["I16", "I17", "I18", "IN0", "IN1"]


class Controllino(Equipo):
    nombre = "controllino"

    def __init__(self):
        super().__init__()
        self.mapa = Mapa(bobinas=N_DO + N_REL, discretas=21, holding=16,
                         entrada=17, al_escribir=self._escrito)
        h = self.mapa.holding
        h[1] = 400
        h[2] = TABLERO
        h[3] = 2 if TABLERO == 1 else 1
        self.t0 = time.time()
        self.peticiones = {"tcp": 0, "rtu": 0}
        self.maestro = {"ok": 0, "sin_respuesta": 0, "ultimo": ""}
        self._anotado = {}

    def _escrito(self, tabla, direccion, valor):
        # Solo los cambios: un maestro (OpenPLC, SCADA) reescribe las 24
        # salidas cada 100 ms y llenaria la consola de lineas iguales.
        if self._anotado.get((tabla, direccion)) == valor:
            return
        self._anotado[(tabla, direccion)] = valor
        if tabla == "bobina":
            nom = "D%d" % direccion if direccion < N_DO else "R%d" % (direccion - N_DO)
            self.anotar("Modbus escribe %s = %d" % (nom, valor))
        elif tabla == "holding" and direccion in (0, 2, 3):
            self.anotar("HR%d = %d" % (direccion, valor))

    # Un maestro en el bus pregunta a nuestra direccion: se contesta igual que
    # por TCP. La direccion 0 es difusion: se ejecuta pero no se responde.
    def trama_485(self, unidad, pdu):
        mia = self.mapa.holding[2] or TABLERO
        if unidad not in (mia, 0):
            return
        self.peticiones["rtu"] += 1
        resp = self.mapa.procesar(pdu)
        if unidad != 0:
            self.enviar_485(mia, resp)

    def orden(self, d):
        super().orden(d)
        c = d.get("cmd")
        m = self.mapa
        if c == "entrada":
            i, v = int(d["i"]), 1 if d.get("v") else 0
            if 0 <= i < len(m.discretas):
                m.discretas[i] = v
                if i < N_AI:
                    m.entrada[i] = 1023 if v else 0
                self.anotar("entrada %s = %d" % (NOMBRE_DI[i], v))
        elif c == "analogica":
            i = int(d["i"])
            if 0 <= i < N_AI:
                m.entrada[i] = max(0, min(1023, int(d["v"])))
                m.discretas[i] = 1 if m.entrada[i] > 512 else 0
        elif c == "salida":   # desde el HMI: el HMI habla con el PLC, no con Modbus
            i = int(d["i"])
            if 0 <= i < len(m.bobinas):
                m.bobinas[i] = 1 if d.get("v") else 0
        elif c == "modo":
            m.holding[0] = int(d["v"])
            self.anotar("MODO = %d (desde el HMI)" % m.holding[0])

    # ── Maestro de la practica entre tableros ─────────────────────────────────
    def _bits_remotos(self):
        bits = [0] * 15
        for fila in range(3):
            if self.mapa.discretas[I_PULS + fila]:
                for d in MATRIZ[fila]:
                    bits[d] = 1
        return bits

    @staticmethod
    def _pdu_fc15(bits):
        b = bytearray((len(bits) + 7) // 8)
        for i, v in enumerate(bits):
            if v:
                b[i // 8] |= 1 << (i % 8)
        return struct.pack(">BHHB", 15, 0, len(bits), len(b)) + bytes(b)

    async def _escribir_tcp(self, esclavo, pdu):
        ip = "192.168.1.%d" % (10 + esclavo)
        try:
            r, w = await asyncio.wait_for(asyncio.open_connection(ip, 502), 0.8)
        except (OSError, asyncio.TimeoutError):
            return None
        try:
            w.write(struct.pack(">HHHB", int(time.time()) & 0xFFFF, 0, len(pdu) + 1, esclavo) + pdu)
            await w.drain()
            cab = await asyncio.wait_for(r.readexactly(7), 0.8)
            return await asyncio.wait_for(r.readexactly(struct.unpack(">H", cab[4:6])[0] - 1), 0.8)
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            return None
        finally:
            w.close()

    async def _bucle_maestro(self):
        antes, t_ultimo = None, 0.0
        h = self.mapa.holding
        while True:
            await asyncio.sleep(0.05)
            modo = h[0]
            if modo not in (3, 4):
                antes = None
                continue
            bits = self._bits_remotos()
            if bits == antes and time.time() - t_ultimo < 1.0:
                continue
            esclavo = h[3] or 1
            pdu = self._pdu_fc15(bits)
            if modo == 3:
                r = await self.preguntar_485(esclavo, pdu) if self.bus["en_bus"] else None
            else:
                r = await self._escribir_tcp(esclavo, pdu)
            t_ultimo = time.time()
            if r is not None and not r[0] & 0x80:
                antes = bits
                h[4] = (h[4] + 1) & 0xFFFF
                self.maestro["ok"] += 1
                self.maestro["ultimo"] = "FC15 -> %s %d OK" % ("RTU" if modo == 3 else "TCP", esclavo)
            else:
                h[5] = (h[5] + 1) & 0xFFFF
                self.maestro["sin_respuesta"] += 1
                self.maestro["ultimo"] = "FC15 -> %s %d sin respuesta" % (
                    "RTU" if modo == 3 else "TCP", esclavo)

    async def _programa(self):
        """El 'loop()' del sketch: lo que corre el PLC entre peticiones."""
        paso = 0
        orden_sec = [d for fila in MATRIZ for d in fila]
        while True:
            m = self.mapa
            modo = m.holding[0]
            if modo == 1:
                for i in range(N_AI):
                    m.bobinas[i] = m.discretas[i]
            elif modo == 2:
                for d in orden_sec:
                    m.bobinas[d] = 1 if d == orden_sec[paso % 9] else 0
                paso += 1
            m.entrada[16] = int(time.time() - self.t0) & 0xFFFF
            per = m.holding[1] if modo == 2 else 100
            await asyncio.sleep(max(50, min(5000, per)) / 1000.0)

    async def iniciar(self):
        await servidor_tcp(self.mapa, TABLERO, 502, self.peticiones)
        asyncio.ensure_future(self._programa())
        asyncio.ensure_future(self._bucle_maestro())

    def estado(self):
        m = self.mapa
        return {
            "do": m.bobinas[:N_DO],
            "rele": m.bobinas[N_DO:],
            "di": m.discretas,
            "ai": m.entrada[:N_AI],
            "hr": m.holding[:8],
            "modo": m.holding[0],
            "unidad": m.holding[2],
            "remoto": m.holding[3],
            "maestro": self.maestro,
            "peticiones": self.peticiones,
        }


if __name__ == "__main__":
    asyncio.run(Controllino().correr())
