"""Pasarela LoRaWAN del laboratorio (8 canales US915, tipo Heltec HT-M7603) y el aire.

Contenedor tab-lora. Dos papeles:

  El aire (UDP 1690 en la red de gestion). Cada RN2903 (rn2903.py) avisa de su
  posicion y su antena ("hola") y manda cada emision ("tx": frecuencia, SF, BW, bytes,
  inicio, tiempo en el aire, potencia). Aqui se calcula lo que llega a cada receptor:
  perdida de trayecto segun la posicion (P1 laboratorio con linea de vista ~5 m, P2
  otro piso con dos losas ~40 m, P3 exterior sin linea de vista ~300 m), antenas,
  sombra aleatoria, ruido termico, y la SNR minima de cada SF. Dos emisiones en la
  misma frecuencia y SF que se solapan chocan (salvo captura, 6 dB). Lo recibido se
  entrega al acabar la emision: a los otros nodos (radio rx) y a esta pasarela.

  La pasarela. Escucha una sub-banda (FSB 2 por defecto: canales 8-15 a SF7-SF10 y el
  65 de 500 kHz a SF8, como un concentrador SX1302 configurado para US915) y reenvia
  lo que demodula con el protocolo Semtech UDP (packet forwarder, puerto 1700) al
  servidor de red: PUSH_DATA con rxpk, PULL_DATA cada 10 s, stat cada 30 s, y emite los
  PULL_RESP (txpk) en el instante tmst que pida el servidor (RX1/RX2), con TX_ACK.
  No descifra nada: es transparente. Su RJ45 se cablea al switch del tablero en las
  gafas; sin ese cable (sin IP 192.168.1.70) no hay backhaul y lo que oye se pierde.

Configuracion (FSB, servidor) en /lora/config.json, que escribe su pagina local del
panel (http://localhost:8090/lora); el registro de tramas en /lora/pasarela.json.
"""

import asyncio
import base64
import json
import math
import os
import random
import socket
import struct
import subprocess
import time

from rn2903 import t_aire_ms

DIR = os.environ.get("TAB_LORA_DIR", "/lora")
IP_LAN = os.environ.get("TAB_LORA_LAN", "192.168.1.70")
EUI = os.environ.get("TAB_LORA_EUI", "A84041FFFE1F7603")
NODOS_IP = {"t1.esp32plc": "172.30.99.21", "t2.esp32plc": "172.30.99.22"}
PUERTO_AIRE, PUERTO_NODO = 1690, 1691

# Perdida de trayecto pasarela <-> nodo [dB] por posicion: espacio libre a 915 MHz
# (32,45 + 20 log f + 20 log d) mas el exceso del edificio.
PERDIDA = {"P1": 45.7,                  # 5 m, linea de vista
           "P2": 63.7 + 44.0,           # 40 m, dos losas de hormigon (~22 dB cada una)
           "P3": 81.2 + 66.0}           # 300 m, exterior del bloque sin linea de vista
PERDIDA_VECINO = 41.0                   # dos bancos del mismo laboratorio (~3 m)
G_ANT = 2.0                             # dBi de cada antena
SIN_ANTENA = 30.0                       # dB que se pierden sin antena (desadaptacion)
AVERIA = 35.0                           # etapa de potencia danada
SOMBRA = 3.0                            # sigma [dB] de la sombra aleatoria por trama
FIGURA_RUIDO = 6.0
SNR_MIN = {7: -7.5, 8: -10.0, 9: -12.5, 10: -15.0, 11: -17.5, 12: -20.0}
POT_PASARELA = 26.0                     # dBm maximos de la pasarela (los limita powe)


def frec_canal(ch):
    return 902300000 + 200000 * ch if ch < 64 else 903000000 + 1600000 * (ch - 64)


def escucha(fsb: int) -> dict:
    """Frecuencia -> (BW, SF admitidos) de la sub-banda fsb (1-8)."""
    out = {frec_canal(8 * (fsb - 1) + k): (125, (7, 8, 9, 10)) for k in range(8)}
    out[frec_canal(64 + fsb - 1)] = (500, (8,))
    return out


def ruido_dbm(bw_khz):
    return -174.0 + 10 * math.log10(bw_khz * 1000.0) + FIGURA_RUIDO


def demodula(snr, sf) -> bool:
    return random.random() < 1.0 / (1.0 + math.exp(-(snr - SNR_MIN.get(sf, -7.5)) / 0.6))


def tipo_trama(b: bytes) -> str:
    if not b:
        return "?"
    mt = b[0] >> 5
    nombre = ["JoinRequest", "JoinAccept", "UnconfirmedDataUp", "UnconfirmedDataDown",
              "ConfirmedDataUp", "ConfirmedDataDown", "RejoinRequest", "Proprietary"][mt]
    if mt == 0 and len(b) >= 23:
        return "%s DevEUI %s" % (nombre, b[9:17][::-1].hex().upper())
    if mt in (2, 3, 4, 5) and len(b) >= 8:
        return "%s DevAddr %s FCnt %d" % (nombre, b[1:5][::-1].hex().upper(), struct.unpack("<H", b[6:8])[0])
    return nombre


class Aire(asyncio.DatagramProtocol):
    def __init__(self, gw):
        self.gw = gw

    def datagram_received(self, data, addr):
        try:
            d = json.loads(data)
        except ValueError:
            return
        self.gw.del_nodo(d, addr)


class Servidor(asyncio.DatagramProtocol):
    def __init__(self, gw):
        self.gw = gw

    def datagram_received(self, data, addr):
        self.gw.del_servidor(data)


class Pasarela:
    def __init__(self):
        os.makedirs(DIR, exist_ok=True)
        self.nodos = {}                 # id -> {"pos","antena","danado","ip"}
        self.en_curso = []              # emisiones en el aire: dicts con t0, t1, freq, sf, choque
        self.log = []                   # ultimas tramas vistas por la pasarela
        self.cuenta = {"rxnb": 0, "rxok": 0, "rxfw": 0, "dwnb": 0, "txnb": 0, "ack": 0, "push": 0}
        self.backhaul = False
        self.ult_ack = None
        self.config = {"fsb": 2, "servidor": "192.168.1.80", "puerto": 1700}
        self.t0 = time.time()
        self.aire = None
        self.srv = None
        self.token = random.randint(0, 0xFFFF)
        self._pendientes = {}           # token -> que era (push/pull)

    # ── Utilidades ────────────────────────────────────────────────────────────
    def tmst(self, t: float) -> int:
        return int((t - self.t0) * 1e6) & 0xFFFFFFFF

    def de_tmst(self, tm: int) -> float:
        base = int((time.time() - self.t0) * 1e6)
        vuelta = base - (base & 0xFFFFFFFF)
        t = vuelta + tm
        if t < base - 2 ** 31:
            t += 2 ** 32
        return self.t0 + t / 1e6

    def anotar(self, entrada: dict):
        entrada.setdefault("hora", time.strftime("%H:%M:%S"))
        self.log.append(entrada)
        del self.log[:-60]
        print(json.dumps(entrada, ensure_ascii=False), flush=True)

    def guardar(self):
        d = {"eui": EUI, "modelo": "HT-M7603 (8 canales, US915)", "config": self.config,
             "escucha": "FSB %d: canales %d-%d (125 kHz, SF7-10) y %d (500 kHz, SF8)" % (
                 self.config["fsb"], 8 * (self.config["fsb"] - 1), 8 * self.config["fsb"] - 1,
                 63 + self.config["fsb"]),
             "backhaul": self.backhaul, "ip": IP_LAN if self.backhaul else "",
             "ult_ack": self.ult_ack, "cuenta": self.cuenta, "tramas": self.log[-60:],
             "nodos": self.nodos, "t": time.time()}
        try:
            with open(os.path.join(DIR, "pasarela.json.tmp"), "w") as f:
                json.dump(d, f, ensure_ascii=False)
            os.replace(os.path.join(DIR, "pasarela.json.tmp"), os.path.join(DIR, "pasarela.json"))
        except OSError:
            pass

    def leer_config(self):
        try:
            with open(os.path.join(DIR, "config.json")) as f:
                c = json.load(f)
            fsb = int(c.get("fsb", 2))
            nuevo = {"fsb": fsb if 1 <= fsb <= 8 else 2, "servidor": str(c.get("servidor", "192.168.1.80")),
                     "puerto": int(c.get("puerto", 1700))}
        except (OSError, ValueError, TypeError):
            return
        if nuevo != self.config:
            self.config = nuevo
            self.anotar({"dir": "-", "estado": "configuración: FSB %d, servidor %s:%d" % (
                nuevo["fsb"], nuevo["servidor"], nuevo["puerto"])})

    def tengo_lan(self) -> bool:
        try:
            out = subprocess.run(["ip", "-o", "-4", "addr"], capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return (" %s/" % IP_LAN) in out

    # ── Perdidas ──────────────────────────────────────────────────────────────
    def _perdida_nodo(self, n: dict, tx: bool) -> float:
        p = PERDIDA.get(n.get("pos", "P1"), PERDIDA["P1"])
        if not n.get("antena"):
            p += SIN_ANTENA
        if tx and n.get("danado"):
            p += AVERIA
        return p

    def _llega(self, pot, perdida, bw):
        s = pot + 2 * G_ANT - perdida + random.gauss(0.0, SOMBRA)
        n = ruido_dbm(bw)
        snr = s - n
        rssi = 10 * math.log10(10 ** (s / 10.0) + 10 ** (n / 10.0))
        # La SNR que estima el demodulador LoRa satura hacia +10 dB con senal fuerte.
        snr_inf = min(snr, 9.5 + random.gauss(0.0, 0.4))
        return rssi, snr_inf, s

    # ── Del aire ──────────────────────────────────────────────────────────────
    def del_nodo(self, d: dict, addr):
        de = str(d.get("de", ""))
        if not de:
            return
        n = self.nodos.setdefault(de, {})
        for k in ("pos", "antena", "danado"):
            if k in d:
                n[k] = d[k]
        n["ip"] = addr[0]
        if d.get("t") == "tx":
            asyncio.ensure_future(self.emision(de, d))

    async def emision(self, de: str, d: dict):
        n = self.nodos[de]
        freq, sf, bw = int(d["freq"]), int(d["sf"]), int(d["bw"])
        t0 = float(d["t0"])
        toa = float(d["toa"])
        datos = bytes.fromhex(d["datos"])
        iq = bool(d.get("iq"))
        perd_gw = self._perdida_nodo(n, tx=True)
        rssi, snr, s = self._llega(float(d["pot"]), perd_gw, bw)
        yo = {"t0": t0, "t1": t0 + toa / 1000.0, "freq": freq, "sf": sf, "s": s, "choque": False}
        for o in self.en_curso:
            if o["freq"] == freq and o["sf"] == sf and o["t0"] < yo["t1"] and yo["t0"] < o["t1"]:
                if abs(o["s"] - s) < 6.0:
                    o["choque"] = yo["choque"] = True
                elif o["s"] > s:
                    yo["choque"] = True
                else:
                    o["choque"] = True
        self.en_curso.append(yo)
        await asyncio.sleep(max(0.0, yo["t1"] - time.time()))
        self.en_curso.remove(yo)
        # A los otros nodos (radio rx del banco vecino): el RN2903 decide si escuchaba.
        for otro, m in self.nodos.items():
            if otro == de or "ip" not in m:
                continue
            perd = PERDIDA_VECINO if m.get("pos", "P1") == n.get("pos", "P1") else \
                max(PERDIDA.get(m.get("pos", "P1"), 0), PERDIDA.get(n.get("pos", "P1"), 0))
            perd += (0 if n.get("antena") else SIN_ANTENA) + (0 if m.get("antena") else SIN_ANTENA)
            perd += AVERIA if n.get("danado") else 0
            r2, snr2, _ = self._llega(float(d["pot"]), perd, bw)
            if yo["choque"] or not demodula(snr2, sf):
                continue
            self._a_nodo(m["ip"], {"t": "rx", "freq": freq, "sf": sf, "bw": bw, "iq": iq, "t0": t0,
                                   "datos": d["datos"], "rssi": round(r2), "snr": round(snr2)})
        # A la pasarela: solo lo de su sub-banda, SF7-SF10 (la radio no demodula SF11/12) e IQ normal.
        canales = escucha(self.config["fsb"])
        if freq not in canales or canales[freq][0] != bw or sf not in canales[freq][1] or iq:
            return
        self.cuenta["rxnb"] += 1
        ch = sorted(canales).index(freq)
        ch_us = round((freq - 902300000) / 200000) if bw == 125 else 64 + round((freq - 903000000) / 1600000)
        e = {"dir": "subida", "freq": freq / 1e6, "canal": ch_us, "datr": "SF%dBW%d" % (sf, bw),
             "toa_ms": round(toa, 1), "rssi": round(rssi), "snr": round(snr, 1), "bytes": len(datos),
             "tipo": tipo_trama(datos)}
        if yo["choque"]:
            e["estado"] = "colisión (CRC mal)"
            self.anotar(e)
            return
        if not demodula(snr, sf):
            e["estado"] = "perdida: SNR por debajo del mínimo de SF%d (%.1f dB)" % (sf, SNR_MIN[sf])
            self.anotar(e)
            return
        self.cuenta["rxok"] += 1
        if not self.backhaul:
            e["estado"] = "oída, pero SIN BACKHAUL (RJ45 sin cablear): se pierde"
            self.anotar(e)
            return
        rxpk = {"tmst": self.tmst(yo["t1"]), "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t0)) +
                ".%06dZ" % int((t0 % 1) * 1e6), "chan": ch, "rfch": 0, "freq": round(freq / 1e6, 6), "stat": 1,
                "modu": "LORA", "datr": "SF%dBW%d" % (sf, bw), "codr": "4/5", "rssi": round(rssi),
                "lsnr": round(snr, 1), "size": len(datos), "data": base64.b64encode(datos).decode()}
        self._enviar(0x00, json.dumps({"rxpk": [rxpk]}).encode())
        self.cuenta["push"] += 1
        self.cuenta["rxfw"] += 1
        e["estado"] = "reenviada al servidor"
        self.anotar(e)

    def _a_nodo(self, ip, d):
        try:
            self.aire.sendto(json.dumps(d).encode(), (ip, PUERTO_NODO))
        except OSError:
            pass

    # ── Semtech UDP ───────────────────────────────────────────────────────────
    def _enviar(self, ident: int, carga: bytes = b""):
        if self.srv is None or not self.backhaul:
            return
        self.token = (self.token + 1) & 0xFFFF
        self._pendientes[self.token] = ident
        pkt = bytes([2]) + struct.pack(">H", self.token) + bytes([ident]) + bytes.fromhex(EUI) + carga
        try:
            self.srv.sendto(pkt, (self.config["servidor"], self.config["puerto"]))
        except OSError:
            pass

    def del_servidor(self, data: bytes):
        if len(data) < 4 or data[0] != 2:
            return
        token, ident = data[1:3], data[3]
        if ident in (0x01, 0x04):               # PUSH_ACK / PULL_ACK
            self.ult_ack = time.strftime("%H:%M:%S")
            if ident == 0x01:
                self.cuenta["ack"] += 1
        elif ident == 0x03:                     # PULL_RESP: un descendente
            try:
                txpk = json.loads(data[4:])["txpk"]
            except (ValueError, KeyError):
                return
            asyncio.ensure_future(self.descendente(token, txpk))

    async def descendente(self, token: bytes, txpk: dict):
        self.cuenta["dwnb"] += 1
        datos = base64.b64decode(txpk.get("data", ""))
        datr = str(txpk.get("datr", "SF12BW500"))
        sf = int(datr[2:datr.index("BW")])
        bw = int(datr[datr.index("BW") + 2:])
        freq = int(round(float(txpk.get("freq", 923.3)) * 1e6))
        toa = t_aire_ms(len(datos), sf, bw, crc=False, prlen=int(txpk.get("prea", 8)))
        cuando = time.time() if txpk.get("imme") else self.de_tmst(int(txpk.get("tmst", 0)))
        error = "NONE"
        if cuando < time.time() - 0.005:
            error = "TOO_LATE"
        elif cuando > time.time() + 30:
            error = "TOO_EARLY"
        ack = {"txpk_ack": {"error": error}}
        try:
            self.srv.sendto(bytes([2]) + token + bytes([0x05]) + bytes.fromhex(EUI) + json.dumps(ack).encode(),
                            (self.config["servidor"], self.config["puerto"]))
        except OSError:
            pass
        e = {"dir": "bajada", "freq": freq / 1e6, "datr": datr, "toa_ms": round(toa, 1), "bytes": len(datos),
             "tipo": tipo_trama(datos), "pot": txpk.get("powe")}
        if error != "NONE":
            e["estado"] = "rechazada por la pasarela: %s" % error
            self.anotar(e)
            return
        await asyncio.sleep(max(0.0, cuando - time.time()))
        await asyncio.sleep(toa / 1000.0)
        self.cuenta["txnb"] += 1
        pot = min(POT_PASARELA, float(txpk.get("powe", 20)))
        for nid, n in self.nodos.items():
            if "ip" not in n:
                continue
            perd = PERDIDA.get(n.get("pos", "P1"), PERDIDA["P1"]) + (0 if n.get("antena") else SIN_ANTENA)
            _, snr, _ = self._llega(pot, perd, bw)
            rssi = round(10 * math.log10(10 ** ((snr + ruido_dbm(bw)) / 10.0) + 10 ** (ruido_dbm(bw) / 10.0)))
            if demodula(snr, sf):
                self._a_nodo(n["ip"], {"t": "rx", "freq": freq, "sf": sf, "bw": bw,
                                       "iq": bool(txpk.get("ipol", True)), "t0": cuando,
                                       "datos": datos.hex(), "rssi": rssi, "snr": round(snr)})
        e["estado"] = "emitida (%s)" % ("inmediata" if txpk.get("imme") else "en tmst")
        self.anotar(e)

    # ── Bucles ────────────────────────────────────────────────────────────────
    async def bucle_backhaul(self):
        t_pull = t_stat = 0.0
        while True:
            self.leer_config()
            lan = await asyncio.to_thread(self.tengo_lan)
            if lan != self.backhaul:
                self.backhaul = lan
                self.anotar({"dir": "-", "estado": "backhaul %s" % ("ARRIBA (192.168.1.70)" if lan else
                                                                     "caído: RJ45 sin cablear al switch")})
                t_pull = 0.0
            if lan and time.time() - t_pull > 10:
                t_pull = time.time()
                self._enviar(0x02)              # PULL_DATA: keepalive, abre el camino de bajada
            if lan and time.time() - t_stat > 30:
                t_stat = time.time()
                c = self.cuenta
                stat = {"stat": {"time": time.strftime("%Y-%m-%d %H:%M:%S GMT", time.gmtime()),
                                 "rxnb": c["rxnb"], "rxok": c["rxok"], "rxfw": c["rxfw"],
                                 "ackr": 100.0 if c["rxfw"] == 0 else round(100.0 * c["ack"] / max(1, c["push"]), 1),
                                 "dwnb": c["dwnb"], "txnb": c["txnb"]}}
                self._enviar(0x00, json.dumps(stat).encode())
            self.guardar()
            await asyncio.sleep(1.0)

    async def correr(self):
        loop = asyncio.get_running_loop()
        self.aire, _ = await loop.create_datagram_endpoint(lambda: Aire(self), local_addr=("0.0.0.0", PUERTO_AIRE))
        self.srv, _ = await loop.create_datagram_endpoint(lambda: Servidor(self), local_addr=("0.0.0.0", 0),
                                                          family=socket.AF_INET)
        self.anotar({"dir": "-", "estado": "pasarela LoRaWAN %s en marcha (FSB %d)" % (EUI, self.config["fsb"])})
        await self.bucle_backhaul()


if __name__ == "__main__":
    asyncio.run(Pasarela().correr())
