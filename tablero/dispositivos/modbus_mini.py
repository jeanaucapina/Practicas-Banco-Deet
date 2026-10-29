"""Modbus minimo, sin dependencias, para los equipos simulados del tablero.

Se escribe a mano (y no con pymodbus) por dos razones: el contenedor arranca
con la imagen python:slim tal cual, sin pip, y el alumno puede leer aqui mismo
como se arma cada trama que luego ve en Wireshark.

    PDU = codigo de funcion (1 B) + datos
    Modbus TCP = MBAP (7 B: transaccion, protocolo=0, longitud, unidad) + PDU
    Modbus RTU = direccion (1 B) + PDU + CRC16 (2 B, little endian)
"""

import asyncio
import struct

# Excepciones que devuelve el esclavo (codigo de funcion | 0x80, codigo)
EXC_FUNCION_ILEGAL = 0x01
EXC_DIRECCION_ILEGAL = 0x02
EXC_VALOR_ILEGAL = 0x03


def crc16(datos: bytes) -> int:
    crc = 0xFFFF
    for b in datos:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def trama_rtu(unidad: int, pdu: bytes) -> bytes:
    cuerpo = bytes([unidad]) + pdu
    return cuerpo + struct.pack("<H", crc16(cuerpo))


def abrir_rtu(trama: bytes):
    """Devuelve (unidad, pdu) o None si la trama es corta o el CRC no cuadra."""
    if len(trama) < 4:
        return None
    if crc16(trama[:-2]) != struct.unpack("<H", trama[-2:])[0]:
        return None
    return trama[0], trama[1:-2]


class Mapa:
    """Las cuatro tablas de Modbus. `al_escribir(tabla, dir, valor)` avisa al
    equipo cuando un maestro cambia una bobina o un registro."""

    def __init__(self, bobinas=0, discretas=0, holding=0, entrada=0, al_escribir=None):
        self.bobinas = [0] * bobinas
        self.discretas = [0] * discretas
        self.holding = [0] * holding
        self.entrada = [0] * entrada
        self.al_escribir = al_escribir or (lambda *a: None)

    @staticmethod
    def _exc(fc, codigo):
        return bytes([fc | 0x80, codigo])

    @staticmethod
    def _empaquetar_bits(bits):
        out = bytearray((len(bits) + 7) // 8)
        for i, b in enumerate(bits):
            if b:
                out[i // 8] |= 1 << (i % 8)
        return bytes(out)

    def procesar(self, pdu: bytes) -> bytes:
        if not pdu:
            return b""
        fc = pdu[0]
        try:
            if fc in (1, 2, 3, 4):
                inicio, n = struct.unpack(">HH", pdu[1:5])
                tabla = {1: self.bobinas, 2: self.discretas, 3: self.holding, 4: self.entrada}[fc]
                limite = 2000 if fc <= 2 else 125
                if not 1 <= n <= limite:
                    return self._exc(fc, EXC_VALOR_ILEGAL)
                if inicio + n > len(tabla):
                    return self._exc(fc, EXC_DIRECCION_ILEGAL)
                trozo = tabla[inicio:inicio + n]
                if fc <= 2:
                    datos = self._empaquetar_bits(trozo)
                else:
                    datos = b"".join(struct.pack(">H", v & 0xFFFF) for v in trozo)
                return bytes([fc, len(datos)]) + datos
            if fc == 5:
                dir_, val = struct.unpack(">HH", pdu[1:5])
                if val not in (0x0000, 0xFF00):
                    return self._exc(fc, EXC_VALOR_ILEGAL)
                if dir_ >= len(self.bobinas):
                    return self._exc(fc, EXC_DIRECCION_ILEGAL)
                self.bobinas[dir_] = 1 if val else 0
                self.al_escribir("bobina", dir_, self.bobinas[dir_])
                return pdu[:5]
            if fc == 6:
                dir_, val = struct.unpack(">HH", pdu[1:5])
                if dir_ >= len(self.holding):
                    return self._exc(fc, EXC_DIRECCION_ILEGAL)
                self.holding[dir_] = val
                self.al_escribir("holding", dir_, val)
                return pdu[:5]
            if fc == 15:
                inicio, n, nb = struct.unpack(">HHB", pdu[1:6])
                if inicio + n > len(self.bobinas):
                    return self._exc(fc, EXC_DIRECCION_ILEGAL)
                bits = pdu[6:6 + nb]
                for i in range(n):
                    self.bobinas[inicio + i] = (bits[i // 8] >> (i % 8)) & 1
                    self.al_escribir("bobina", inicio + i, self.bobinas[inicio + i])
                return pdu[:5]
            if fc == 16:
                inicio, n, nb = struct.unpack(">HHB", pdu[1:6])
                if inicio + n > len(self.holding) or nb != 2 * n:
                    return self._exc(fc, EXC_DIRECCION_ILEGAL)
                for i in range(n):
                    self.holding[inicio + i] = struct.unpack(">H", pdu[6 + 2 * i:8 + 2 * i])[0]
                    self.al_escribir("holding", inicio + i, self.holding[inicio + i])
                return pdu[:5]
        except (struct.error, IndexError):
            return self._exc(fc, EXC_VALOR_ILEGAL)
        return self._exc(fc, EXC_FUNCION_ILEGAL)


async def servidor_tcp(mapa: Mapa, unidad: int = 1, puerto: int = 502, contador=None):
    """Esclavo Modbus TCP. Responde a cualquier unidad (como hace casi todo
    equipo TCP real); `unidad` solo se usa para documentar."""

    async def atender(lector, escritor):
        try:
            while True:
                cab = await lector.readexactly(7)
                tid, proto, largo, uid = struct.unpack(">HHHB", cab)
                pdu = await lector.readexactly(largo - 1)
                if proto != 0:
                    continue
                resp = mapa.procesar(pdu)
                if contador is not None:
                    contador["tcp"] = contador.get("tcp", 0) + 1
                escritor.write(struct.pack(">HHHB", tid, 0, len(resp) + 1, uid) + resp)
                await escritor.drain()
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            escritor.close()

    srv = await asyncio.start_server(atender, "0.0.0.0", puerto, reuse_address=True)
    return srv


def pdu_leer(fc: int, inicio: int, n: int) -> bytes:
    return struct.pack(">BHH", fc, inicio, n)


def bits_de_respuesta(pdu: bytes, n: int):
    if not pdu or pdu[0] & 0x80:
        return None
    datos = pdu[2:2 + pdu[1]]
    return [(datos[i // 8] >> (i % 8)) & 1 for i in range(n)]


def regs_de_respuesta(pdu: bytes):
    if not pdu or pdu[0] & 0x80:
        return None
    return [struct.unpack(">H", pdu[2 + 2 * i:4 + 2 * i])[0] for i in range(pdu[1] // 2)]
