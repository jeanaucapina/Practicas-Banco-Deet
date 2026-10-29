"""S7-1200 (CPU 1214C) simulado con Snap7: S7comm de verdad (ISO-on-TCP,
puerto 102) en la LAN del tablero, 192.168.1.40. Desde el PC: 127.0.0.1:102
(rack 0, slot 1). Sirve para practicar con clientes S7 (Node-RED, python-snap7,
un SCADA/HMI) y para ver S7comm en Wireshark (-i tab-lan, filtro "s7comm").
No ejecuta programas de TIA Portal: el "programa" del PLC es el de abajo.

Programa: marcha/paro de un motor de cinta con contador de piezas y
temperatura con alarma.

Entradas (%IB0)                    Salidas (%QB0)
  I0.0  MARCHA (NA)                  Q0.0  motor
  I0.1  PARO (NC: 1 = sin pulsar)    Q0.1  luz verde (en marcha)
  I0.2  sensor de pieza (simulado)   Q0.2  luz roja (alarma, parpadea)
  I0.3  REARME de alarma

DB1 "Proceso" (acceso NO optimizado, como lo pide un cliente S7 externo)
  (escribir el byte DBB0 entero pisa los 8 bits: para un solo bit, escritura
   de bit, p. ej. write_area(Area.DB, 1, 0*8+1, ...) con WordLen.Bit)
  DBX0.0  MarchaRemota   Bool  pulso desde el SCADA (el PLC lo vuelve a 0)
  DBX0.1  ParoRemoto     Bool  pulso
  DBX0.2  Motor          Bool  estado (solo lectura)
  DBX0.3  Alarma         Bool  temperatura > Consigna (enclavada)
  DBX0.4  RearmeRemoto   Bool  pulso
  DBW2    Piezas         Int
  DBW4    Temperatura    Int   en decimas de grado (235 = 23,5 C)
  DBD6    Consigna       Real  C de alarma (45,0)
  DBD10   TiempoMarcha   DInt  s con el motor en marcha
  DBW14   Ciclo          Int   +1 cada 100 ms (vida del PLC)

Marcas: MB0..MB31 libres para las practicas.
"""

import json
import os
import struct
import threading
import time

from snap7.server import Server
from snap7.type import SrvArea

class ServidorS7(Server):
    """Snap7 3.2.1 pierde el numero de bit en los accesos Bool (WordLen.Bit):
    leer M20.1 devolvia el byte MB20 y escribirlo ponia MB20 = 0x01. Un S7 de
    verdad lee y escribe solo ese bit; aqui la direccion de bit viaja marcada
    en `start` hasta las dos funciones que tocan la memoria."""

    MARCA = 1 << 24

    def _parse_address_specification(self, spec):
        d = super()._parse_address_specification(spec)
        if d and d.get("word_len") == 0x01:          # BIT
            d["start"] = self.MARCA + int.from_bytes(spec[9:12], "big")
        return d

    def _read_from_memory_area(self, area, db, start, count):
        if start < self.MARCA:
            return super()._read_from_memory_area(area, db, start, count)
        dirb = start - self.MARCA
        rc, datos = super()._read_from_memory_area(area, db, dirb >> 3, 1)
        return (rc, bytearray([datos[0] >> (dirb & 7) & 1])) if rc == 0xFF and datos else (rc, datos)

    def _write_to_memory_area(self, area, db, start, datos):
        if start < self.MARCA:
            return super()._write_to_memory_area(area, db, start, datos)
        dirb = start - self.MARCA
        mem = self.memory_areas.get((area, db))
        if mem is None or (dirb >> 3) >= len(mem) or not datos:
            return False
        b = mem[dirb >> 3]
        b = b | (1 << (dirb & 7)) if datos[0] & 1 else b & ~(1 << (dirb & 7)) & 0xFF
        return super()._write_to_memory_area(area, db, dirb >> 3, bytearray([b]))


PE = bytearray(4)
PA = bytearray(4)
MK = bytearray(32)
DB1 = bytearray(16)

CICLO = 0.010
PERIODO_PIEZA = 2.0                 # s entre piezas con la cinta en marcha
T_AMBIENTE, T_MOTOR, TAU = 20.0, 70.0, 30.0


def bit(b: bytearray, byte: int, n: int) -> bool:
    return bool(b[byte] >> n & 1)


def poner(b: bytearray, byte: int, n: int, v: bool):
    b[byte] = b[byte] | (1 << n) if v else b[byte] & ~(1 << n) & 0xFF


class Plc:
    def __init__(self):
        self.srv = ServidorS7(log=False)
        for area, n, buf in ((SrvArea.PE, 0, PE), (SrvArea.PA, 0, PA),
                             (SrvArea.MK, 0, MK), (SrvArea.DB, 1, DB1)):
            self.srv.register_area(area, n, buf)
        poner(PE, 0, 1, True)                        # PARO es NC: sin pulsar = 1
        DB1[6:10] = struct.pack(">f", 45.0)
        self.temp = T_AMBIENTE
        self.t_pieza = 0.0
        self.sensor_antes = False
        self.t_marcha = 0.0
        self.t_ciclo = 0.0
        self.motor = False
        self.alarma = False                          # estado interno: el DB solo lo refleja
        self.motor_antes = None
        self.alarma_antes = None

    def anotar(self, txt):
        print(time.strftime("%H:%M:%S ") + txt, flush=True)

    def ciclo(self, dt: float):
        # ── Lectura de entradas y peticiones del SCADA ────────────────────────
        marcha = bit(PE, 0, 0) or bit(DB1, 0, 0)
        paro = not bit(PE, 0, 1) or bit(DB1, 0, 1)
        rearme = bit(PE, 0, 3) or bit(DB1, 0, 4)
        for n in (0, 1, 4):                          # los pulsos remotos se consumen
            poner(DB1, 0, n, False)
        consigna = struct.unpack(">f", bytes(DB1[6:10]))[0]

        # ── Alarma de temperatura (enclavada hasta rearmar ya frio) ───────────
        # El estado vive en el PLC, no en el DB: un SCADA que escribe el byte
        # entero de DBB0 (para dar un pulso) pisa tambien Motor/Alarma.
        alarma = self.alarma
        if self.temp > consigna:
            alarma = True
        elif rearme and self.temp < consigna - 2.0:
            alarma = False

        # ── Motor: enclavamiento marcha/paro clasico ──────────────────────────
        motor = (self.motor or marcha) and not paro and not alarma
        self.motor, self.alarma = motor, alarma

        # ── "Planta": piezas en la cinta y temperatura del motor ──────────────
        if motor:
            self.t_pieza += dt
            self.t_marcha += dt
        sensor = motor and (self.t_pieza % PERIODO_PIEZA) > PERIODO_PIEZA - 0.2
        poner(PE, 0, 2, sensor)
        if sensor and not self.sensor_antes:
            piezas = (struct.unpack(">h", bytes(DB1[2:4]))[0] + 1) & 0x7FFF
            DB1[2:4] = struct.pack(">h", piezas)
        self.sensor_antes = sensor
        objetivo = T_MOTOR if motor else T_AMBIENTE
        self.temp += (objetivo - self.temp) * dt / TAU

        # ── Escritura de salidas y DB ─────────────────────────────────────────
        poner(PA, 0, 0, motor)
        poner(PA, 0, 1, motor)
        poner(PA, 0, 2, alarma and int(time.time() * 2) % 2 == 0)
        poner(DB1, 0, 2, motor)
        poner(DB1, 0, 3, alarma)
        DB1[4:6] = struct.pack(">h", int(round(self.temp * 10)))
        DB1[10:14] = struct.pack(">i", int(self.t_marcha))
        self.t_ciclo += dt
        if self.t_ciclo >= 0.1:
            self.t_ciclo = 0.0
            DB1[14:16] = struct.pack(">h", (struct.unpack(">h", bytes(DB1[14:16]))[0] + 1) & 0x7FFF)

        if motor != self.motor_antes:
            self.anotar("motor %s" % ("EN MARCHA" if motor else "parado"))
            self.motor_antes = motor
        if alarma != self.alarma_antes:
            self.anotar("alarma de temperatura %s (%.1f C, consigna %.1f C)" % (
                "ACTIVA" if alarma else "rearmada", self.temp, consigna))
            self.alarma_antes = alarma

    def foto(self):
        """Estado para el panel del PC, por fichero: sin trafico S7 que
        ensucie la captura de tab-lan."""
        return {"t": time.time(), "I": PE[0], "Q": PA[0], "motor": self.motor, "alarma": self.alarma,
                "piezas": struct.unpack(">h", bytes(DB1[2:4]))[0],
                "temperatura": struct.unpack(">h", bytes(DB1[4:6]))[0] / 10,
                "consigna": round(struct.unpack(">f", bytes(DB1[6:10]))[0], 1),
                "t_marcha": struct.unpack(">i", bytes(DB1[10:14]))[0]}

    def volcar(self):
        try:
            os.makedirs("/panel", exist_ok=True)
            with open("/panel/s7.tmp", "w") as f:
                json.dump(self.foto(), f)
            os.replace("/panel/s7.tmp", "/panel/s7.json")
        except OSError:
            pass

    def correr(self):
        self.srv.start(tcp_port=102)
        self.anotar("S7-1200 simulado en marcha: 192.168.1.40:102 (rack 0, slot 1)")
        t = time.monotonic()
        while True:
            time.sleep(CICLO)
            ahora = time.monotonic()
            self.ciclo(ahora - t)
            t = ahora
            if int(ahora * 2) != int((ahora - CICLO) * 2):    # 2 veces por segundo
                self.volcar()


if __name__ == "__main__":
    threading.current_thread().name = "plc"
    Plc().correr()
