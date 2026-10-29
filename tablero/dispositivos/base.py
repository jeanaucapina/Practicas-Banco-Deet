"""Lo comun a todos los equipos simulados del tablero.

Cada equipo es un contenedor con tres redes posibles:

  tab_gestion  (siempre)      canal con la pasarela: estado hacia las gafas y
                              ordenes desde ellas. No es trafico "del alumno",
                              por eso va por su propio puente y no ensucia la
                              captura de tab-lan.
  tab_485      (siempre)      el bus RS-485. Cada trama viaja como un datagrama
                              UDP de difusion; el equipo solo transmite y escucha
                              si la pasarela le dice que sus bornes A/B estan
                              cableados a un bus.
  tab_lan      (segun cable)  la LAN de los switches. La pasarela hace
                              `docker network connect/disconnect` cuando en las
                              gafas se enchufa o se quita el latiguillo.

Varios buses: dos tableros que no estan cableados entre si tienen cada uno su
bus. La pasarela numera cada red electrica y cada una viaja por su propio
puerto UDP (4850, 4851, ...), asi que no se oyen.

Capa fisica (bus485.py): el datagrama lleva los bytes que el emisor puso en el
par, sin cabecera (Wireshark los decodifica como Modbus RTU). La pasarela reparte
la linea de cada nodo -baudios, formato y si tiene A/B cruzados- y cada receptor
reconstruye la onda y la lee con su propia UART: baudios distintos o A/B al reves
dan basura, dos emisores a la vez colisionan, y el bus puede tener ruido. Cada
trama ocupa el par lo que dura a sus baudios: el emisor la suelta al terminar.
"""

import asyncio
import json
import os
import socket
import time

import bus485
import rn2903
from modbus_mini import abrir_rtu, trama_rtu

PASARELA = os.environ.get("TAB_PASARELA", "172.30.99.1")
PUERTO_ESTADO = 9001      # equipo -> pasarela
PUERTO_ORDEN = 9000       # pasarela -> equipo
PUERTO_485 = 4850
BUS_485 = os.environ.get("TAB_BUS_485", "172.30.85.255")
ID = os.environ.get("TAB_ID", "")             # p. ej. "t1.controllino"
TABLERO = int(os.environ.get("TAB_TABLERO", "1"))


GUARDA = 0.001            # s que el receptor espera por si otra trama se solapa (colision)


class Equipo:
    nombre = "equipo"

    def __init__(self):
        self.bus = {"en_bus": False, "invertido": False, "puerto": PUERTO_485}
        self.log = []                 # ultimas lineas para la consola de las gafas
        self.tramas_485 = {"tx": 0, "rx": 0, "crc_mal": 0}
        self._sock_estado = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._t485 = None             # transporte del puerto UDP del bus actual
        self._mis_ips = {os.environ.get("TAB_IP_485", "")}
        self._espera = None           # respuesta RTU que un maestro esta esperando
        # Linea serie propia (la imitacion de fabrica: 19200 8N1) y la de los demas
        # nodos del bus, por IP, como la reparte la pasarela: [baudios, formato, cruzado]
        self.linea = [19200, bus485.FORMATO_DEFECTO]
        self.lineas = {}
        self._en_par = []             # tramas recientes en el par (propias y ajenas)

    # ── Registro ──────────────────────────────────────────────────────────────
    def anotar(self, txt: str):
        self.log.append(time.strftime("%H:%M:%S ") + txt)
        del self.log[:-12]
        print(txt, flush=True)

    # ── Estado hacia las gafas ────────────────────────────────────────────────
    def estado(self) -> dict:
        raise NotImplementedError

    async def _bucle_estado(self):
        while True:
            d = self.estado()
            d["equipo"] = ID or self.nombre
            d["bus"] = self.bus
            d["tramas_485"] = self.tramas_485
            d["linea485"] = self.linea
            d["log"] = self.log[-6:]
            if ID.endswith("esp32plc") and "lora" not in d:
                d["lora"] = rn2903.leer_publico(ID)      # antena y posicion del slot LORA
            try:
                self._sock_estado.sendto(json.dumps(d).encode(), (PASARELA, PUERTO_ESTADO))
            except OSError:
                pass
            await asyncio.sleep(0.1)

    # ── Ordenes desde las gafas ───────────────────────────────────────────────
    def orden(self, d: dict):
        """Las subclases la amplian; aqui lo del bus y el slot LORA."""
        if d.get("cmd") == "lora" and ID.endswith("esp32plc"):
            # Antena del slot LORA (las gafas), posicion en el edificio (portal) y
            # cambio del modulo averiado. Se guarda aunque corra el programa de fabrica.
            cambios = {k: d[k] for k in ("antena", "pos") if k in d}
            if d.get("reponer"):
                cambios["danado"] = False
            antes = rn2903.leer_publico(ID)
            rn2903.guardar_hw(ID, cambios)
            if "antena" in cambios and bool(cambios["antena"]) != antes["antena"]:
                self.anotar("antena de 915 MHz %s" % ("ATORNILLADA en el slot LORA" if cambios["antena"] else "retirada"))
            if "pos" in cambios and cambios["pos"] != antes["pos"]:
                self.anotar("nodo LoRa en la posición %s" % cambios["pos"])
            if d.get("reponer"):
                self.anotar("módulo RN2903 cambiado por uno nuevo")
        if d.get("cmd") == "bus":
            antes = dict(self.bus)
            self.bus["en_bus"] = bool(d.get("en_bus"))
            self.bus["invertido"] = bool(d.get("invertido"))
            self.bus["puerto"] = int(d.get("puerto", PUERTO_485))
            self.bus["ruido"] = float(d.get("ruido", 0.0))
            if isinstance(d.get("lineas"), dict):
                self.lineas = d["lineas"]
            if self.bus["puerto"] != antes["puerto"]:
                asyncio.ensure_future(self._abrir_485(self.bus["puerto"]))
            if antes != self.bus:
                if not self.bus["en_bus"]:
                    self.anotar("RS-485: bornes sin conectar al bus")
                else:
                    self.anotar("RS-485: en el bus %d%s" % (
                        self.bus["puerto"] - PUERTO_485,
                        " (A/B CRUZADOS)" if self.bus["invertido"] else ""))

    class _ProtoOrden(asyncio.DatagramProtocol):
        def __init__(self, eq):
            self.eq = eq

        def datagram_received(self, data, addr):
            try:
                self.eq.orden(json.loads(data))
            except (ValueError, TypeError, KeyError) as e:
                print("orden mala:", e, flush=True)

    # ── Bus RS-485 ────────────────────────────────────────────────────────────
    class _Proto485(asyncio.DatagramProtocol):
        def __init__(self, eq):
            self.eq = eq

        def datagram_received(self, data, addr):
            if addr[0] in self.eq._mis_ips or not self.eq.bus["en_bus"] or not data:
                return
            # La trama acaba de terminar en el par: empezo hace lo que dura a sus baudios.
            baud, fmt, cruzado = (self.eq.lineas.get(addr[0]) or [19200, bus485.FORMATO_DEFECTO, False])[:3]
            fin = time.time()
            seg = bus485.Segmento(fin - bus485.duracion(len(data), baud, fmt), data, baud, fmt, cruzado)
            self.eq._al_par(seg)
            asyncio.get_running_loop().call_later(GUARDA, self.eq._oir, seg)

    def _al_par(self, seg):
        ahora = time.time()
        self._en_par = [x for x in self._en_par if ahora - x.t1 < 1.0] + [seg]

    def _oir(self, seg):
        """Lo que entrega la UART de este equipo: su linea, su polaridad, colisiones y ruido."""
        if not self.bus["en_bus"]:
            return
        otras = [x for x in self._en_par if x is not seg and x.t0 < seg.t1 and seg.t0 < x.t1]
        if otras:
            self.tramas_485["colisiones"] = self.tramas_485.get("colisiones", 0) + 1
        data = bus485.leer([seg] + otras, self.linea[0], self.linea[1], self.bus["invertido"])
        # El ruido que reparte la pasarela (terminacion mal) es el de 38 400 baudios: a
        # 19 200 o menos un par corto funciona igual; por encima, peor (guia L3, V.4).
        p = self.bus.get("ruido", 0.0) * max(0.0, (self.linea[0] - 19200) / 19200.0)
        data = bus485.ruido(data, min(0.9, p))
        if data:
            self._recibir_485(data)

    def _recibir_485(self, data: bytes):
        if self.crudo_485(data):
            return
        r = abrir_rtu(data)
        if r is None:
            self.tramas_485["crc_mal"] += 1
            return
        self.tramas_485["rx"] += 1
        # Si un maestro de este equipo espera respuesta, es para el.
        if self._espera is not None and not self._espera.done():
            self._espera.set_result(r)
            return
        self.trama_485(r[0], r[1])

    async def _abrir_485(self, puerto):
        if self._t485 is not None:
            self._t485.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("0.0.0.0", puerto))
        self._t485, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: Equipo._Proto485(self), sock=s)

    def crudo_485(self, data: bytes) -> bool:
        """True si el equipo se queda la trama tal cual (programa del alumno,
        que hace su propio Modbus); si no, la abre aqui."""
        return False

    def enviar_485(self, unidad: int, pdu: bytes):
        self.enviar_485_crudo(trama_rtu(unidad, pdu))

    def enviar_485_crudo(self, t: bytes, ya_emitida: bool = False):
        """Pone la trama en el par. La imitacion de fabrica la empieza ahora y la
        suelta al terminar (lo que dura a sus baudios); el programa del alumno ya
        la emitio byte a byte a su ritmo (ya_emitida)."""
        if not self.bus["en_bus"] or self._t485 is None or not t:
            return
        dur = bus485.duracion(len(t), self.linea[0], self.linea[1])
        t0 = time.time() - (dur if ya_emitida else 0.0)
        self._al_par(bus485.Segmento(t0, t, self.linea[0], self.linea[1], self.bus["invertido"]))
        self.tramas_485["tx"] += 1
        tr, destino = self._t485, (BUS_485, self.bus["puerto"])
        if ya_emitida:
            tr.sendto(t, destino)
        else:
            asyncio.get_running_loop().call_later(dur, lambda: tr.is_closing() or tr.sendto(t, destino))

    async def preguntar_485(self, esclavo, pdu, timeout=0.3):
        """Maestro RTU: manda la peticion y espera la respuesta del esclavo."""
        self._espera = asyncio.get_running_loop().create_future()
        self.enviar_485(esclavo, pdu)
        try:
            u, r = await asyncio.wait_for(self._espera, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._espera = None
        return r if u == esclavo else None

    def trama_485(self, unidad: int, pdu: bytes):
        """Llega una trama valida del bus que nadie esperaba (el esclavo)."""

    # ── Arranque ──────────────────────────────────────────────────────────────
    async def iniciar(self):
        """Las subclases arrancan aqui sus servidores."""

    async def correr(self):
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(
            lambda: Equipo._ProtoOrden(self), local_addr=("0.0.0.0", PUERTO_ORDEN))
        await self._abrir_485(self.bus["puerto"])
        await self.iniciar()
        self.anotar("%s encendido" % (ID or self.nombre))
        await self._bucle_estado()
