"""Modulo LoRa RN2903 (Microchip, US915) del slot LORA del ESP32 PLC 14, emulado.

El programa del alumno le habla por loraSerial con los comandos de texto del modulo
(RN2903 Command Reference, DS40001811): sys, mac y radio, con sus respuestas ("ok",
"accepted", "mac_tx_ok", "radio_rx  <hex>", "busy", "not_joined"...). Dentro:

  - MAC LoRaWAN 1.0.x de clase A de verdad: JoinRequest/JoinAccept OTAA (AES-128 y
    CMAC), claves de sesion derivadas, FCnt, MIC, cifrado de FRMPayload, ventanas RX1
    (1 s, o 5 s en la union) y RX2 (923,3 MHz, DR8) y comandos MAC (LinkADRReq,
    DevStatusReq...). Un ChirpStack o un The Things Stack real entienden sus tramas.
  - Radio US915: 64 canales de 125 kHz + 8 de 500 kHz, DR0 (SF10) a DR4, carga util
    maxima por DR, tiempo en el aire con la formula de Semtech y modo radio directo
    (mac pause / radio tx / radio rx) para SF11-SF12, que la MAC no admite.

El aire es UDP por la red de gestion: cada emision va al medio (pasarela_lora.py),
que la entrega a la pasarela LoRaWAN del laboratorio y a los otros nodos con la
potencia que les llega segun la posicion (P1/P2/P3), la antena y el modulo. Emitir
sin antena dana la etapa de potencia (como en el real: el modulo sigue respondiendo,
pero su alcance cae a pocos metros) hasta que se cambia el modulo.

Lo que no se ve desde fuera (antena, posicion, averia, contador DevNonce y la
configuracion guardada con "mac save") vive en /programas/<equipo>/rn2903.json.
"""

import asyncio
import json
import math
import os
import random
import socket
import struct
import time

AIRE = (os.environ.get("TAB_LORA_IP", "172.30.99.70"), 1690)
PUERTO_NODO = 1691
VERSION = "RN2903 1.0.5 Nov 06 2018 10:45:27"

# US915 (RP002-1.0.x): DR -> (SF, BW kHz) y carga util maxima N sin FOpts
DR_SUBIDA = {0: (10, 125), 1: (9, 125), 2: (8, 125), 3: (7, 125), 4: (8, 500)}
DR_BAJADA = {8: (12, 500), 9: (11, 500), 10: (10, 500), 11: (9, 500), 12: (8, 500), 13: (7, 500)}
N_MAX = {0: 11, 1: 53, 2: 125, 3: 242, 4: 242}
RX1_DR = {0: 10, 1: 11, 2: 12, 3: 13, 4: 13}
MAC_LEN = {0x02: 2, 0x03: 4, 0x04: 1, 0x05: 4, 0x06: 0, 0x07: 5, 0x08: 1, 0x09: 1, 0x0A: 4, 0x0D: 5}


def frec_subida(ch: int) -> int:
    return 902300000 + 200000 * ch if ch < 64 else 903000000 + 1600000 * (ch - 64)


def frec_rx1(ch: int) -> int:
    return 923300000 + 600000 * (ch % 8)


def t_aire_ms(pl: int, sf: int, bw_khz: int, cr: int = 1, crc: bool = True, prlen: int = 8) -> float:
    """Tiempo en el aire (Semtech, AN1200.13). cr=1 es 4/5; cabecera explicita."""
    ts = (2 ** sf) / (bw_khz * 1000.0) * 1000.0
    de = 1 if (bw_khz == 125 and sf >= 11) else 0
    n = 8 + max(math.ceil((8 * pl - 4 * sf + 28 + 16 * (1 if crc else 0)) / (4.0 * (sf - 2 * de))) * (cr + 4), 0)
    return (prlen + 4.25 + n) * ts


def _aes(k: bytes, b: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    e = Cipher(algorithms.AES(k), modes.ECB()).encryptor()
    return e.update(b) + e.finalize()


def _cmac(k: bytes, b: bytes) -> bytes:
    from cryptography.hazmat.primitives import cmac
    from cryptography.hazmat.primitives.ciphers import algorithms
    c = cmac.CMAC(algorithms.AES(k))
    c.update(b)
    return c.finalize()


def _cifrar(k: bytes, devaddr_le: bytes, fcnt: int, sentido: int, datos: bytes) -> bytes:
    """FRMPayload (LoRaWAN 1.0.x, 4.3.3): XOR con AES(k, A_i). Cifra y descifra."""
    out = bytearray()
    for i in range(0, len(datos), 16):
        a = bytes([1, 0, 0, 0, 0, sentido]) + devaddr_le + struct.pack("<I", fcnt) + bytes([0, i // 16 + 1])
        s = _aes(k, a)
        out += bytes(x ^ y for x, y in zip(datos[i:i + 16], s))
    return bytes(out)


def _mic(k: bytes, devaddr_le: bytes, fcnt: int, sentido: int, msg: bytes) -> bytes:
    b0 = bytes([0x49, 0, 0, 0, 0, sentido]) + devaddr_le + struct.pack("<I", fcnt) + bytes([0, len(msg)])
    return _cmac(k, b0 + msg)[:4]


def _hex_ok(v: str, n: int) -> bool:
    try:
        return len(v) == n and bytes.fromhex(v) is not None
    except ValueError:
        return False


def rangos(chs) -> str:
    """[8, 9, ..., 15, 64, ...] -> "8-15,64-71"."""
    out, ini, ant = [], None, None
    for c in sorted(chs):
        if ini is None:
            ini = ant = c
        elif c == ant + 1:
            ant = c
        else:
            out.append("%d-%d" % (ini, ant) if ant != ini else str(ini))
            ini = ant = c
    if ini is not None:
        out.append("%d-%d" % (ini, ant) if ant != ini else str(ini))
    return ",".join(out)


def ruta_hw(ident: str) -> str:
    return "/programas/%s/rn2903.json" % ident


def leer_hw(ident: str) -> dict:
    try:
        with open(ruta_hw(ident)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def leer_publico(ident: str) -> dict:
    d = leer_hw(ident)
    return {"antena": bool(d.get("antena", False)), "pos": d.get("pos", "P1"), "danado": bool(d.get("danado", False))}


def guardar_hw(ident: str, cambios: dict):
    """Antena, posicion, averia... (tambien con el programa de fabrica corriendo)."""
    d = leer_hw(ident)
    d.update(cambios)
    try:
        os.makedirs(os.path.dirname(ruta_hw(ident)), exist_ok=True)
        with open(ruta_hw(ident) + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(ruta_hw(ident) + ".tmp", ruta_hw(ident))
    except OSError:
        pass


class RN2903:
    def __init__(self, ident: str, al_programa, anotar):
        self.id = ident
        self.al_programa = al_programa          # bytes -> loraSerial del programa
        self.anotar = anotar
        n = ident[1:2] if ident[1:2].isdigit() else "1"
        self.hweui = "0004A30B001F7A0" + n      # OUI de Microchip
        self.buf = b""
        self.cola = asyncio.Queue()
        self.ocupado = False                    # union, tx o radio en curso
        self.pausado = False
        self.escuchas = []                      # ventanas de recepcion abiertas
        self.sock = None
        self.ult_rx = {"rssi": -128, "snr": -128}
        self.ultima = leer_hw(ident).get("ultima")
        self.ultima_union = None
        self.unido = False
        self._defecto_mac()
        self._cargar_eeprom()
        self._defecto_radio()

    # ── Configuracion ─────────────────────────────────────────────────────────
    def _defecto_mac(self):
        self.mac = {"deveui": self.hweui, "appeui": "0000000000000000", "appkey": "0" * 32,
                    "devaddr": "00000000", "nwkskey": "0" * 32, "appskey": "0" * 32,
                    "pwridx": 5, "dr": 0, "adr": False, "ar": False, "retx": 7, "rxdelay1": 1000,
                    "rx2": [8, 923300000], "upctr": 0, "dnctr": 0, "bat": 0, "linkchk": 0,
                    "ch": [True] * 72, "sync": "34"}
        self.claves_ok = {"deveui": True, "appeui": False, "appkey": False,
                          "devaddr": False, "nwkskey": False, "appskey": False}
        self.unido = False
        self.resp_mac = b""                     # respuestas MAC para el proximo ascendente
        self.ack_pendiente = False

    def _defecto_radio(self):
        self.radio = {"mod": "lora", "freq": 923300000, "pwr": 2, "sf": 12, "bw": 125, "cr": "4/5",
                      "prlen": 8, "crc": True, "iqi": False, "sync": "34", "wdt": 15000}

    def _cargar_eeprom(self):
        e = leer_hw(self.id).get("eeprom")
        if e:
            self.mac.update(e.get("mac", {}))
            self.claves_ok.update(e.get("claves", {}))

    def _guardar_eeprom(self):
        guardar_hw(self.id, {"eeprom": {"mac": self.mac, "claves": self.claves_ok}})

    def hw(self) -> dict:
        d = leer_hw(self.id)
        return {"antena": bool(d.get("antena", False)), "pos": d.get("pos", "P1"),
                "danado": bool(d.get("danado", False))}

    def resumen(self) -> dict:
        h = self.hw()
        chs = [i for i, on in enumerate(self.mac["ch"]) if on]
        return {**h, "unido": self.unido, "devaddr": self.mac["devaddr"] if self.unido else "",
                "deveui": self.mac["deveui"], "canales": rangos(chs), "dr": self.mac["dr"],
                "adr": self.mac["adr"], "fcnt": self.mac["upctr"], "pausado": self.pausado,
                "ultima": self.ultima, "union": self.ultima_union}

    # ── Aire ──────────────────────────────────────────────────────────────────
    async def iniciar(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setblocking(False)
        s.bind(("0.0.0.0", PUERTO_NODO))
        self.sock = s
        asyncio.get_running_loop().add_reader(s.fileno(), self._del_aire)
        asyncio.ensure_future(self._bucle_comandos())
        asyncio.ensure_future(self._bucle_hola())

    async def _bucle_hola(self):
        while True:
            self._al_aire({"t": "hola", **self.hw()})
            await asyncio.sleep(3.0)

    def _al_aire(self, d: dict):
        if self.sock is None:
            return
        d["de"] = self.id
        try:
            self.sock.sendto(json.dumps(d).encode(), AIRE)
        except OSError:
            pass

    def _del_aire(self):
        try:
            while True:
                datos, _ = self.sock.recvfrom(8192)
                try:
                    self._llega(json.loads(datos))
                except (ValueError, KeyError, TypeError):
                    pass
        except (BlockingIOError, OSError):
            pass

    def _llega(self, d: dict):
        """Una emision ajena acaba de terminar: se recibe si hay una ventana abierta con
        la misma frecuencia, SF, ancho de banda y polaridad, y su preambulo empezo dentro."""
        if d.get("t") != "rx":
            return
        for v in list(self.escuchas):
            if v["fut"].done():
                continue
            if (int(d["freq"]) == v["freq"] and int(d["sf"]) == v["sf"] and int(d["bw"]) == v["bw"]
                    and bool(d.get("iq")) == v["iq"] and v["desde"] <= float(d["t0"]) <= v["hasta"]):
                v["fut"].set_result(d)
                return

    async def _escuchar(self, freq, sf, bw, iq, desde, hasta, fin):
        """Abre una ventana: preambulos que empiecen entre `desde` y `hasta` (tiempo de
        reloj); espera como mucho hasta `fin`. Devuelve la recepcion o None."""
        v = {"freq": freq, "sf": sf, "bw": bw, "iq": iq, "desde": desde, "hasta": hasta,
             "fut": asyncio.get_running_loop().create_future()}
        self.escuchas.append(v)
        try:
            return await asyncio.wait_for(v["fut"], max(0.0, fin - time.time()))
        except asyncio.TimeoutError:
            return None
        finally:
            self.escuchas.remove(v)

    async def _emitir(self, freq, sf, bw, datos: bytes, pot_dbm: float, iq=False, crc=True, prlen=8):
        h = self.hw()
        toa = t_aire_ms(len(datos), sf, bw, crc=crc, prlen=prlen)
        t0 = time.time()
        if not h["antena"] and not h["danado"]:
            guardar_hw(self.id, {"danado": True})
            self.anotar("RN2903: ¡EMITISTE SIN ANTENA! La etapa de potencia se ha dañado: el módulo "
                        "responde, pero su alcance cae a pocos metros. Hay que cambiar el módulo.")
        self._al_aire({"t": "tx", "freq": freq, "sf": sf, "bw": bw, "datos": datos.hex(), "t0": t0,
                       "toa": toa, "pot": pot_dbm, "iq": iq, **self.hw()})
        await asyncio.sleep(toa / 1000.0)
        return t0, t0 + toa / 1000.0, toa

    # ── Serie ─────────────────────────────────────────────────────────────────
    def recibir(self, b: bytes):
        self.buf += b
        while b"\n" in self.buf:
            linea, self.buf = self.buf.split(b"\n", 1)
            # autobaud: 0x00 (break) + 0x55 antes de la linea
            linea = linea.rstrip(b"\r").lstrip(b"\x00").lstrip(b"\x55")
            if linea:
                self.cola.put_nowait(linea.decode("latin-1").strip())

    def _resp(self, txt: str):
        self.al_programa((txt + "\r\n").encode("latin-1"))

    async def _bucle_comandos(self):
        while True:
            linea = await self.cola.get()
            await asyncio.sleep(0.002)          # lo que tarda el modulo en contestar
            try:
                self._comando(linea)
            except (ValueError, IndexError, KeyError):
                self._resp("invalid_param")

    def _comando(self, linea: str):
        p = linea.split()
        if not p:
            return
        g = p[0].lower()
        if g == "sys":
            self._sys(p[1:])
        elif g == "mac":
            self._mac(p[1:])
        elif g == "radio":
            self._radio(p[1:])
        else:
            self._resp("invalid_param")

    # ── sys ───────────────────────────────────────────────────────────────────
    def _sys(self, p):
        c = p[0].lower() if p else ""
        if c == "get":
            q = p[1].lower()
            r = {"ver": VERSION, "hweui": self.hweui, "vdd": "3312"}.get(q)
            self._resp(r if r else ("FF" if q == "nvm" else "invalid_param"))
        elif c in ("reset", "factoryreset"):
            if c == "factoryreset":
                guardar_hw(self.id, {"eeprom": None})
            self._defecto_mac()
            self._cargar_eeprom()
            self._defecto_radio()
            self.pausado = False
            self._resp(VERSION)
        elif c == "sleep":
            ms = int(p[1])
            if not 100 <= ms <= 4294967296:
                self._resp("invalid_param")
                return

            async def despertar():
                await asyncio.sleep(ms / 1000.0)
                self._resp("ok")
            asyncio.ensure_future(despertar())
        elif c == "set":
            self._resp("ok")
        else:
            self._resp("invalid_param")

    # ── mac ───────────────────────────────────────────────────────────────────
    def _mac(self, p):
        c = p[0].lower() if p else ""
        m = self.mac
        if c == "reset":
            if len(p) > 1:
                self._resp("invalid_param")     # "mac reset 868" es del RN2483
                return
            ee = leer_hw(self.id).get("eeprom")
            self._defecto_mac()
            if ee:                               # las claves guardadas se mantienen
                for k in ("deveui", "appeui", "appkey", "devaddr", "nwkskey", "appskey"):
                    if k in ee.get("mac", {}):
                        m = self.mac
                        m[k] = ee["mac"][k]
                        self.claves_ok[k] = ee.get("claves", {}).get(k, False)
            self._resp("ok")
        elif c == "save":
            self._guardar_eeprom()
            self._resp("ok")
        elif c == "forceenable":
            self._resp("ok")
        elif c == "pause":
            if self.ocupado:
                self._resp("0")
            else:
                self.pausado = True
                self._resp("4294967245")
        elif c == "resume":
            self.pausado = False
            self._resp("ok")
        elif c == "set":
            self._resp("ok" if self._mac_set(p[1:]) else "invalid_param")
        elif c == "get":
            self._resp(self._mac_get(p[1:]))
        elif c == "join":
            self._join(p[1].lower() if len(p) > 1 else "")
        elif c == "tx":
            self._tx(p[1:])
        else:
            self._resp("invalid_param")

    def _mac_set(self, p) -> bool:
        q, v = p[0].lower(), p[1:]
        m = self.mac
        largo = {"deveui": 16, "appeui": 16, "appkey": 32, "devaddr": 8, "nwkskey": 32, "appskey": 32}
        if q in largo:
            if not v or not _hex_ok(v[0], largo[q]):
                return False
            m[q] = v[0].upper()
            self.claves_ok[q] = True
            return True
        if q == "pwridx":
            n = int(v[0])
            if n not in (5, 7, 8, 9, 10):
                return False
            m["pwridx"] = n
        elif q == "dr":
            n = int(v[0])
            if n not in DR_SUBIDA:
                return False
            m["dr"] = n
        elif q in ("adr", "ar"):
            if v[0].lower() not in ("on", "off"):
                return False
            m[q] = v[0].lower() == "on"
        elif q in ("retx", "bat"):
            m[q] = max(0, min(255, int(v[0])))
        elif q in ("linkchk", "rxdelay1"):
            m[q] = max(0, min(65535, int(v[0])))
        elif q in ("upctr", "dnctr"):
            m[q] = int(v[0]) & 0xFFFFFFFF
        elif q == "sync":
            m["sync"] = v[0]
        elif q == "rx2":
            dr, f = int(v[0]), int(v[1])
            if dr not in DR_BAJADA or not 923300000 <= f <= 927500000:
                return False
            m["rx2"] = [dr, f]
        elif q == "ch":
            sub, ch = v[0].lower(), int(v[1])
            if not 0 <= ch < 72:
                return False
            if sub == "status":
                if v[2].lower() not in ("on", "off"):
                    return False
                m["ch"][ch] = v[2].lower() == "on"
            elif sub == "drrange":
                pass
            else:
                return False
        else:
            return False
        return True

    def _mac_get(self, p) -> str:
        q = p[0].lower() if p else ""
        m = self.mac
        if q in ("deveui", "appeui", "devaddr"):
            return m[q]
        if q in ("dr", "pwridx", "retx", "rxdelay1", "upctr", "dnctr", "bat"):
            return str(m[q])
        if q == "rxdelay2":
            return str(m["rxdelay1"] + 1000)
        if q in ("adr", "ar"):
            return "on" if m[q] else "off"
        if q == "rx2":
            return "%d %d" % tuple(m["rx2"])
        if q == "sync":
            return m["sync"]
        if q == "status":
            st = (1 if self.ocupado else 0) | (int(self.unido) << 4) | (int(m["ar"]) << 5) | \
                 (int(m["adr"]) << 6) | (int(self.pausado) << 8)
            return "%04X" % st
        if q == "mrgn":
            return str(max(0, int(self.ult_rx["snr"]) + 20))
        if q == "gwnb":
            return "1" if self.unido else "0"
        if q == "ch" and len(p) >= 3:
            ch = int(p[2])
            if p[1].lower() == "status":
                return "on" if m["ch"][ch] else "off"
            if p[1].lower() == "freq":
                return str(frec_subida(ch))
            if p[1].lower() == "drrange":
                return "4 4" if ch >= 64 else "0 3"
        return "invalid_param"

    def _pot_mac(self) -> float:
        # pwridx 5 = maxima (18,5 dBm en el ESP32 PLC 14 con su antena); 2 dB por paso
        return 18.5 - 2.0 * (self.mac["pwridx"] - 5)

    def _canal(self, dr: int):
        m = self.mac["ch"]
        lista = [c for c in (range(64, 72) if dr == 4 else range(64)) if m[c]]
        return random.choice(lista) if lista else None

    # ── Union ─────────────────────────────────────────────────────────────────
    def _join(self, modo: str):
        if modo not in ("otaa", "abp"):
            self._resp("invalid_param")
            return
        if self.pausado:
            self._resp("mac_paused")
            return
        if self.ocupado:
            self._resp("busy")
            return
        if modo == "abp":
            if not all(self.claves_ok[k] for k in ("devaddr", "nwkskey", "appskey")):
                self._resp("keys_not_init")
                return
            self._resp("ok")
            self.unido = True
            self.ultima_union = {"hora": time.strftime("%H:%M:%S"), "modo": "ABP", "resultado": "accepted"}
            self._resp("accepted")
            return
        if not all(self.claves_ok[k] for k in ("deveui", "appeui", "appkey")):
            self._resp("keys_not_init")
            return
        if self._canal(0) is None and self._canal(4) is None:
            self._resp("no_free_ch")
            return
        self._resp("ok")
        self.ocupado = True
        asyncio.ensure_future(self._union_otaa())

    async def _union_otaa(self):
        m = self.mac
        try:
            self.unido = False
            hw = leer_hw(self.id)
            devnonce = (int(hw.get("devnonce", random.randint(0, 200))) + 1) & 0xFFFF
            guardar_hw(self.id, {"devnonce": devnonce})
            appkey = bytes.fromhex(m["appkey"])
            msg = b"\x00" + bytes.fromhex(m["appeui"])[::-1] + bytes.fromhex(m["deveui"])[::-1] + \
                struct.pack("<H", devnonce)
            trama = msg + _cmac(appkey, msg)[:4]
            # El JoinRequest alterna 125 kHz (DR0) y 500 kHz (DR4) entre los canales activos.
            self._n_union = getattr(self, "_n_union", 0) + 1
            dr = 4 if (self._n_union % 2 == 0 and self._canal(4) is not None) or self._canal(0) is None else 0
            ch = self._canal(dr)
            sf, bw = DR_SUBIDA[dr]
            _, t_fin, toa = await self._emitir(frec_subida(ch), sf, bw, trama, self._pot_mac())
            self.ultima_union = {"hora": time.strftime("%H:%M:%S"), "modo": "OTAA", "canal": ch,
                                 "dr": dr, "devnonce": devnonce, "resultado": "..."}
            ja = await self._ventanas(t_fin, ch, dr, 5.0, 6.0)
            if ja is not None and self._aceptar_union(bytes.fromhex(ja["datos"]), appkey, devnonce):
                self.ultima_union["resultado"] = "accepted"
                self.ultima_union["devaddr"] = m["devaddr"]
                self._resp("accepted")
            else:
                self.ultima_union["resultado"] = "denied"
                self._resp("denied")
        finally:
            self.ocupado = False

    def _aceptar_union(self, d: bytes, appkey: bytes, devnonce: int) -> bool:
        if len(d) not in (17, 33) or d[0] != 0x20:
            return False
        claro = _aes(appkey, d[1:])                 # el servidor cifro con AES-decrypt
        if _cmac(appkey, d[:1] + claro[:-4])[:4] != claro[-4:]:
            return False
        joinnonce, netid, devaddr = claro[0:3], claro[3:6], claro[6:10]
        dl, rxdelay = claro[10], claro[11]
        resto = joinnonce + netid + struct.pack("<H", devnonce) + bytes(7)
        m = self.mac
        m["nwkskey"] = _aes(appkey, b"\x01" + resto).hex().upper()
        m["appskey"] = _aes(appkey, b"\x02" + resto).hex().upper()
        m["devaddr"] = devaddr[::-1].hex().upper()
        m["rxdelay1"] = 1000 * (rxdelay & 0x0F or 1)
        if (dl & 0x0F) in DR_BAJADA:             # DLSettings: RX2DataRate (DR8 en US915)
            m["rx2"] = [dl & 0x0F, m["rx2"][1]]
        m["upctr"] = m["dnctr"] = 0
        if len(claro) == 32 and claro[27] == 1:   # CFList tipo 1 (US915): mascara de canales
            for blk in range(5):
                masc = struct.unpack("<H", claro[12 + 2 * blk:14 + 2 * blk])[0]
                for b in range(16):
                    if 16 * blk + b < 72:
                        m["ch"][16 * blk + b] = bool(masc >> b & 1)
        self.claves_ok.update({"devaddr": True, "nwkskey": True, "appskey": True})
        self.unido = True
        self.resp_mac = b""
        return True

    async def _ventanas(self, t_fin, ch, dr, d1, d2):
        """RX1 y RX2 de clase A tras un ascendente que acabo en t_fin. Devuelve lo recibido."""
        sf1, bw1 = DR_BAJADA[RX1_DR[dr]]
        a1 = t_fin + d1
        r = await self._escuchar(frec_rx1(ch), sf1, bw1, True, a1 - 0.02, a1 + 0.1,
                                 a1 + 0.12 + t_aire_ms(64, sf1, bw1, crc=False) / 1000.0)
        if r is not None:
            return r
        sf2, bw2 = DR_BAJADA[self.mac["rx2"][0]]
        a2 = t_fin + d2
        return await self._escuchar(self.mac["rx2"][1], sf2, bw2, True, a2 - 0.02, a2 + 0.1,
                                    a2 + 0.12 + t_aire_ms(64, sf2, bw2, crc=False) / 1000.0)

    # ── Ascendentes ───────────────────────────────────────────────────────────
    def _tx(self, p):
        if len(p) < 3 or p[0].lower() not in ("cnf", "uncnf"):
            self._resp("invalid_param")
            return
        puerto, datos = int(p[1]), p[2]
        if not 1 <= puerto <= 223 or len(datos) % 2 or not _hex_ok(datos, len(datos)):
            self._resp("invalid_param")
            return
        if self.pausado:
            self._resp("mac_paused")
            return
        if not self.unido:
            self._resp("not_joined")
            return
        if self.ocupado:
            self._resp("busy")
            return
        carga = bytes.fromhex(datos)
        if len(carga) + len(self.resp_mac) > N_MAX[self.mac["dr"]]:
            self._resp("invalid_data_len")
            return
        if self._canal(self.mac["dr"]) is None:
            self._resp("no_free_ch")
            return
        if self.mac["upctr"] >= 0xFFFFFFFF:
            self._resp("frame_counter_err_rejoin_needed")
            return
        self._resp("ok")
        self.ocupado = True
        asyncio.ensure_future(self._ascendente(p[0].lower() == "cnf", puerto, carga))

    def _trama_subida(self, conf: bool, puerto: int, carga: bytes) -> bytes:
        m = self.mac
        da = bytes.fromhex(m["devaddr"])[::-1]
        fopts = self.resp_mac[:15]
        fctrl = (0x80 if m["adr"] else 0) | (0x20 if self.ack_pendiente else 0) | len(fopts)
        fcnt = m["upctr"]
        msg = bytes([0x80 if conf else 0x40]) + da + bytes([fctrl]) + struct.pack("<H", fcnt & 0xFFFF) + fopts
        msg += bytes([puerto]) + _cifrar(bytes.fromhex(m["appskey"]), da, fcnt, 0, carga)
        return msg + _mic(bytes.fromhex(m["nwkskey"]), da, fcnt, 0, msg)

    async def _ascendente(self, conf: bool, puerto: int, carga: bytes):
        m = self.mac
        try:
            intentos = (m["retx"] + 1) if conf else 1
            for _ in range(intentos):
                trama = self._trama_subida(conf, puerto, carga)
                self.resp_mac = b""
                self.ack_pendiente = False
                dr = m["dr"]
                ch = self._canal(dr)
                sf, bw = DR_SUBIDA[dr]
                _, t_fin, toa = await self._emitir(frec_subida(ch), sf, bw, trama, self._pot_mac())
                self.ultima = {"hora": time.strftime("%H:%M:%S"), "t": time.time(), "fcnt": m["upctr"],
                               "fport": puerto, "hex": carga.hex(), "canal": ch, "dr": dr, "sf": sf,
                               "toa_ms": round(toa, 1), "phy": len(trama), "conf": conf}
                guardar_hw(self.id, {"ultima": self.ultima})
                m["upctr"] = (m["upctr"] + 1) & 0xFFFFFFFF
                d = m["rxdelay1"] / 1000.0
                r = await self._ventanas(t_fin, ch, dr, d, d + 1.0)
                res = self._bajada(bytes.fromhex(r["datos"])) if r is not None else None
                if r is not None:
                    self.ult_rx = {"rssi": r.get("rssi", -128), "snr": r.get("snr", -128)}
                if conf and not (res and res["ack"]):
                    await asyncio.sleep(1.0 + random.random())
                    continue
                if res and res["fport"]:
                    self._resp("mac_rx %d %s" % (res["fport"], res["datos"].hex().upper()))
                else:
                    self._resp("mac_tx_ok")
                return
            self._resp("mac_err")
        finally:
            self.ocupado = False

    # ── Descendentes ──────────────────────────────────────────────────────────
    def _bajada(self, d: bytes):
        """Trama de bajada recibida en RX1/RX2: MIC, FCnt, comandos MAC y datos."""
        m = self.mac
        if len(d) < 12 or d[0] not in (0x60, 0xA0):
            return None
        da = bytes.fromhex(m["devaddr"])[::-1]
        if d[1:5] != da:
            return None                         # para otro nodo
        fctrl = d[5]
        f16 = struct.unpack("<H", d[6:8])[0]
        fcnt = (m["dnctr"] & 0xFFFF0000) | f16
        if fcnt < m["dnctr"]:
            fcnt += 0x10000
        if _mic(bytes.fromhex(m["nwkskey"]), da, fcnt, 1, d[:-4]) != d[-4:]:
            self.anotar("RN2903: bajada con MIC inválido (descartada)")
            return None
        m["dnctr"] = fcnt + 1
        nf = fctrl & 0x0F
        fopts = d[8:8 + nf]
        resto = d[8 + nf:-4]
        fport, datos = 0, b""
        if resto:
            fport = resto[0]
            clave = m["appskey"] if fport else m["nwkskey"]
            datos = _cifrar(bytes.fromhex(clave), da, fcnt, 1, resto[1:])
        self._comandos_mac(fopts + (datos if fport == 0 else b""))
        self.ack_pendiente = d[0] == 0xA0
        return {"ack": bool(fctrl & 0x20), "fport": fport, "datos": datos if fport else b""}

    def _comandos_mac(self, c: bytes):
        m = self.mac
        i, resp = 0, b""
        while i < len(c):
            cid = c[i]
            n = MAC_LEN.get(cid)
            if n is None:
                break
            a = c[i + 1:i + 1 + n]
            i += 1 + n
            if cid == 0x03:                     # LinkADRReq
                drp, masc, red = a[0], struct.unpack("<H", a[1:3])[0], a[3]
                cntl = (red >> 4) & 0x07
                ch = m["ch"]
                if cntl <= 4:
                    for b in range(16):
                        if 16 * cntl + b < 72:
                            ch[16 * cntl + b] = bool(masc >> b & 1)
                elif cntl in (6, 7):
                    for k in range(64):
                        ch[k] = cntl == 6
                    for b in range(8):
                        ch[64 + b] = bool(masc >> b & 1)
                if m["adr"] and (drp >> 4) in DR_SUBIDA:
                    m["dr"] = drp >> 4
                resp += b"\x03\x07"
            elif cid == 0x04:
                resp += b"\x04"
            elif cid == 0x05:                   # RXParamSetupReq
                rx2dr = a[0] & 0x0F
                f = int.from_bytes(a[1:4], "little") * 100
                if rx2dr in DR_BAJADA:
                    m["rx2"] = [rx2dr, f]
                resp += b"\x05\x07"
            elif cid == 0x06:                   # DevStatusReq: alimentacion externa (0)
                margen = max(-32, min(31, int(self.ult_rx["snr"])))
                resp += b"\x06\x00" + bytes([margen & 0x3F])
            elif cid == 0x08:
                m["rxdelay1"] = 1000 * ((a[0] & 0x0F) or 1)
                resp += b"\x08"
            elif cid in (0x07, 0x0A):
                resp += bytes([cid, 0x03])
        self.resp_mac = (self.resp_mac + resp)[:15]

    # ── radio (con la MAC en pausa) ───────────────────────────────────────────
    def _radio(self, p):
        c = p[0].lower() if p else ""
        r = self.radio
        if c == "set":
            q, v = p[1].lower(), p[2:]
            ok = True
            if q == "mod":
                ok = v[0].lower() in ("lora", "fsk")
                r["mod"] = v[0].lower()
            elif q == "freq":
                f = int(v[0])
                ok = 902000000 <= f <= 928000000
                if ok:
                    r["freq"] = f
            elif q == "sf":
                ok = v[0].lower() in ["sf%d" % k for k in range(7, 13)]
                if ok:
                    r["sf"] = int(v[0][2:])
            elif q == "bw":
                ok = v[0] in ("125", "250", "500")
                if ok:
                    r["bw"] = int(v[0])
            elif q == "cr":
                ok = v[0] in ("4/5", "4/6", "4/7", "4/8")
                if ok:
                    r["cr"] = v[0]
            elif q == "pwr":
                ok = 2 <= int(v[0]) <= 20
                if ok:
                    r["pwr"] = int(v[0])
            elif q in ("prlen", "wdt"):
                r[q] = int(v[0])
            elif q in ("crc", "iqi"):
                ok = v[0].lower() in ("on", "off")
                r[q] = v[0].lower() == "on"
            elif q in ("sync", "rxbw", "bitrate", "fdev", "afcbw", "bt"):
                pass
            else:
                ok = False
            self._resp("ok" if ok else "invalid_param")
        elif c == "get":
            q = p[1].lower()
            if q == "snr":
                self._resp(str(int(self.ult_rx["snr"])))
            elif q in ("rssi", "pktrssi"):
                self._resp(str(int(self.ult_rx["rssi"])))
            elif q == "sf":
                self._resp("sf%d" % r["sf"])
            elif q in ("crc", "iqi"):
                self._resp("on" if r[q] else "off")
            elif q in r:
                self._resp(str(r[q]))
            else:
                self._resp("invalid_param")
        elif c == "tx":
            datos = p[1] if len(p) > 1 else ""
            if not datos or len(datos) % 2 or len(datos) > 510 or not _hex_ok(datos, len(datos)):
                self._resp("invalid_param")
            elif not self.pausado or self.ocupado:
                self._resp("busy")
            else:
                self._resp("ok")
                self.ocupado = True
                asyncio.ensure_future(self._radio_tx(bytes.fromhex(datos)))
        elif c == "rx":
            ventana = int(p[1])
            if not self.pausado or self.ocupado:
                self._resp("busy")
            else:
                self._resp("ok")
                self.ocupado = True
                asyncio.ensure_future(self._radio_rx(ventana))
        elif c == "rxstop":
            for v in self.escuchas:
                if not v["fut"].done():
                    v["fut"].set_result(None)
            self._resp("ok")
        else:
            self._resp("invalid_param")

    async def _radio_tx(self, datos: bytes):
        r = self.radio
        try:
            cr = int(r["cr"][2]) - 4
            toa = t_aire_ms(len(datos), r["sf"], r["bw"], cr=cr, crc=r["crc"], prlen=r["prlen"])
            await self._emitir(r["freq"], r["sf"], r["bw"], datos, float(r["pwr"]), iq=r["iqi"],
                               crc=r["crc"], prlen=r["prlen"])
            self.ultima_radio = {"hora": time.strftime("%H:%M:%S"), "sf": r["sf"], "toa_ms": round(toa, 1)}
            self._resp("radio_tx_ok")
        finally:
            self.ocupado = False

    async def _radio_rx(self, ventana: int):
        """radio rx 0: continua hasta el perro guardian (radio set wdt; 0 = sin limite);
        radio rx N: N simbolos."""
        r = self.radio
        try:
            ahora = time.time()
            if ventana == 0:
                fin = ahora + (r["wdt"] / 1000.0 if r["wdt"] > 0 else 10 ** 7)
            else:
                fin = ahora + ventana * (2 ** r["sf"]) / (r["bw"] * 1000.0)
                if r["wdt"] > 0:
                    fin = min(fin, ahora + r["wdt"] / 1000.0)
            d = await self._escuchar(r["freq"], r["sf"], r["bw"], r["iqi"], ahora, fin, fin + 2.0)
            if d is None:
                self._resp("radio_err")
            else:
                self.ult_rx = {"rssi": d.get("rssi", -128), "snr": d.get("snr", -128)}
                self._resp("radio_rx  " + d["datos"].upper())
        finally:
            self.ocupado = False
