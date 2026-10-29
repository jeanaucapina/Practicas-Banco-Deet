"""Cliente MQTT 3.1.1 minimo (QoS 0), sin dependencias.

Solo lo que usa el ESP32 PLC simulado: CONNECT, PUBLISH, SUBSCRIBE y PINGREQ.
Cada paquete es cabecera fija (tipo<<4 | flags, longitud restante en varint)
+ cabecera variable + carga, igual que se ve en Wireshark con el filtro `mqtt`.
"""

import asyncio
import struct


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _cadena(s: str) -> bytes:
    b = s.encode()
    return struct.pack(">H", len(b)) + b


class ClienteMQTT:
    def __init__(self, id_cliente: str, keepalive: int = 30):
        self.id = id_cliente
        self.keepalive = keepalive
        self.lector = None
        self.escritor = None
        self.al_mensaje = lambda tema, carga: None
        self._pid = 1

    @property
    def conectado(self) -> bool:
        return self.escritor is not None and not self.escritor.is_closing()

    async def conectar(self, host: str, puerto: int = 1883, timeout: float = 2.0) -> bool:
        try:
            self.lector, self.escritor = await asyncio.wait_for(
                asyncio.open_connection(host, puerto), timeout)
        except (OSError, asyncio.TimeoutError):
            self.escritor = None
            return False
        var = _cadena("MQTT") + bytes([4, 0x02]) + struct.pack(">H", self.keepalive)
        carga = _cadena(self.id)
        self.escritor.write(bytes([0x10]) + _varint(len(var) + len(carga)) + var + carga)
        try:
            connack = await asyncio.wait_for(self.lector.readexactly(4), timeout)
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            self.cerrar()
            return False
        if connack[0] != 0x20 or connack[3] != 0:
            self.cerrar()
            return False
        asyncio.ensure_future(self._leer())
        asyncio.ensure_future(self._ping())
        return True

    def cerrar(self):
        if self.escritor is not None:
            self.escritor.close()
        self.escritor = None

    def publicar(self, tema: str, carga: bytes, retener: bool = False):
        if not self.conectado:
            return
        var = _cadena(tema)
        self.escritor.write(bytes([0x30 | (1 if retener else 0)])
                            + _varint(len(var) + len(carga)) + var + carga)

    def suscribir(self, filtro: str):
        if not self.conectado:
            return
        self._pid = self._pid % 65535 + 1
        cuerpo = struct.pack(">H", self._pid) + _cadena(filtro) + b"\x00"
        self.escritor.write(bytes([0x82]) + _varint(len(cuerpo)) + cuerpo)

    async def _ping(self):
        while self.conectado:
            await asyncio.sleep(self.keepalive / 2)
            if self.conectado:
                self.escritor.write(b"\xc0\x00")

    async def _leer(self):
        try:
            while True:
                cab = await self.lector.readexactly(1)
                largo, mult = 0, 1
                while True:
                    b = (await self.lector.readexactly(1))[0]
                    largo += (b & 0x7F) * mult
                    mult *= 128
                    if not b & 0x80:
                        break
                cuerpo = await self.lector.readexactly(largo)
                if cab[0] >> 4 == 3:
                    n = struct.unpack(">H", cuerpo[:2])[0]
                    tema = cuerpo[2:2 + n].decode(errors="replace")
                    off = 2 + n + (2 if cab[0] & 0x06 else 0)
                    self.al_mensaje(tema, cuerpo[off:])
        except (asyncio.IncompleteReadError, OSError):
            pass
        self.cerrar()
