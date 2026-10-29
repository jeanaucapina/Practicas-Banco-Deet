"""Capturas de muestra del Taller U4 (comparacion de tramas): los protocolos del curso que
no se montan en el banco, construidos byte a byte segun su norma para que Wireshark los
diseccione como si vinieran de una planta.

  u4_goose.pcap      IEC 61850-8-1 GOOSE (EtherType 0x88B8, 802.1Q prioridad 4): dos IED de
                     una subestacion. Latido cada 1 s; a los 2,5 s una falta: el rele de
                     proteccion publica el disparo (stNum+1, sqNum 0) y lo repite a 4, 4, 8,
                     16... ms; 60 ms despues el interruptor publica su apertura.
  u4_dnp3.pcap       DNP3 (IEEE 1815) sobre TCP 20000: sondeo de integridad (clases 0-3),
                     respuesta con 4 entradas binarias y 4 analogicas, un evento NO solicitado
                     (RBE) de la analogica 2 con su confirmacion, y otro sondeo de clase 1.
  u4_devicenet.pcap  DeviceNet sobre CAN (SocketCAN): el maestro (MAC 0) sondea los esclavos
                     MAC 10, 11 y 12 cada 10 ms (grupo 2, mensaje 5) y cada uno responde con
                     sus entradas (grupo 1, mensaje 15). Wireshark: Decode As CAN -> DeviceNet.

    python herramientas/u4_capturas.py <carpeta | carpeta/u4_goose.pcap>
"""
import os
import struct
import sys

T0 = 1793001600.0          # 2026-10-26 00:00:00 UTC


def pcap(ruta, linktype, paquetes):
    with open(ruta, "wb") as f:
        f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, linktype))
        for t, datos in paquetes:
            s = int(t)
            us = int(round((t - s) * 1e6))
            if us >= 1000000:
                s, us = s + 1, us - 1000000
            f.write(struct.pack("<IIII", s, us, len(datos), len(datos)) + datos)


# ── GOOSE ────────────────────────────────────────────────────────────────────
def tlv(tag, valor):
    n = len(valor)
    if n < 0x80:
        return bytes([tag, n]) + valor
    if n < 0x100:
        return bytes([tag, 0x81, n]) + valor
    return bytes([tag, 0x82, n >> 8, n & 0xFF]) + valor


def entero(v):
    n = 1
    while not -(1 << (8 * n - 1)) <= v < (1 << (8 * n - 1)):
        n += 1
    return v.to_bytes(n, "big", signed=True)


def utc(t):
    s = int(t)
    frac = int((t - s) * (1 << 24))
    return struct.pack(">I", s) + frac.to_bytes(3, "big") + b"\x0a"     # 10 bits de precision


def goose(src, appid, gocb, datset, goid, t, st, sq, tal, datos):
    pdu = b"".join([
        tlv(0x80, gocb.encode()), tlv(0x81, entero(tal)), tlv(0x82, datset.encode()),
        tlv(0x83, goid.encode()), tlv(0x84, utc(t)), tlv(0x85, entero(st)), tlv(0x86, entero(sq)),
        tlv(0x87, b"\x00"), tlv(0x88, entero(1)), tlv(0x89, b"\x00"), tlv(0x8A, entero(len(datos))),
        tlv(0xAB, b"".join(datos))])
    apdu = tlv(0x61, pdu)
    cuerpo = struct.pack(">HHHH", appid, 8 + len(apdu), 0, 0) + apdu
    eth = bytes.fromhex("010ccd010001") + bytes.fromhex(src) + b"\x81\x00" + struct.pack(">H", 4 << 13) + \
        b"\x88\xb8" + cuerpo
    return eth + bytes(max(0, 60 - len(eth)))


def captura_goose(ruta):
    calidad = tlv(0x84, b"\x03\x00\x00")                     # Quality: 13 bits a 0 (good)
    dbpos = {"cerrado": tlv(0x84, b"\x06\x80"), "abierto": tlv(0x84, b"\x06\x40")}

    def rele(t, st, sq, tal, disparo):
        return goose("0030a7010101", 0x0001, "PROT_P1/LLN0$GO$gcbDisparo", "PROT_P1/LLN0$dsDisparo",
                     "PROT_P1_PTOC", t, st, sq, tal, [tlv(0x83, b"\x01" if disparo else b"\x00"), calidad])

    def interruptor(t, st, sq, tal, estado):
        return goose("0030a7020202", 0x0002, "CTRL_P1/LLN0$GO$gcbPosicion", "CTRL_P1/LLN0$dsPosicion",
                     "CTRL_P1_XCBR", t, st, sq, tal, [dbpos[estado], calidad])

    paq = []
    # latidos de los dos IED (estado estable): cada 1 s, TAL 2 s
    for k in range(7):
        t = T0 + k * 1.0
        if t < T0 + 2.5:
            paq.append((t, rele(t, 1, k, 2000, False)))
        paq.append((t + 0.37, interruptor(t + 0.37, 1, k, 2000, "cerrado") if t + 0.37 < T0 + 2.56 else None))
    paq = [p for p in paq if p[1] is not None]

    # falta a los 2,5 s: disparo y repeticiones 4, 4, 8, 16, 32, 64, 128, 256, 512 ms, luego 1 s
    def rafaga(t_ev, fabrica, st, n_latidos=3):
        out, t, sq = [], t_ev, 0
        pasos = [0.004, 0.004, 0.008, 0.016, 0.032, 0.064, 0.128, 0.256, 0.512] + [1.0] * n_latidos
        out.append((t, fabrica(t, st, sq, int(2 * pasos[0] * 1000))))
        for i, d in enumerate(pasos):
            t += d
            sq += 1
            sig = pasos[i + 1] if i + 1 < len(pasos) else 1.0
            out.append((t, fabrica(t, st, sq, int(2 * sig * 1000))))
        return out

    paq += rafaga(T0 + 2.5, lambda t, st, sq, tal: rele(t, st, sq, tal, True), 2)
    paq += rafaga(T0 + 2.56, lambda t, st, sq, tal: interruptor(t, st, sq, tal, "abierto"), 2)
    paq.sort(key=lambda p: p[0])
    pcap(ruta, 1, paq)


# ── DNP3 sobre TCP ───────────────────────────────────────────────────────────
def _tabla_crc_dnp():
    tab = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xA6BC if c & 1 else c >> 1
        tab.append(c)
    return tab


TAB_DNP = _tabla_crc_dnp()


def crc_dnp(b):
    c = 0
    for x in b:
        c = (c >> 8) ^ TAB_DNP[(c ^ x) & 0xFF]
    return struct.pack("<H", ~c & 0xFFFF)


def trama_dnp(ctrl, dst, src, usuario):
    cab = b"\x05\x64" + bytes([5 + len(usuario), ctrl]) + struct.pack("<HH", dst, src)
    out = cab + crc_dnp(cab)
    for i in range(0, len(usuario), 16):
        blq = usuario[i:i + 16]
        out += blq + crc_dnp(blq)
    return out


def suma16(b):
    if len(b) % 2:
        b += b"\x00"
    s = sum(struct.unpack("!%dH" % (len(b) // 2), b))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


class Tcp:
    """Una conexion TCP real (SYN, numeros de secuencia, ACK, sumas) entre dos hosts."""

    def __init__(self, cli, srv, pcli, psrv, mac_cli, mac_srv):
        self.ext = {"c": (cli, pcli, mac_cli), "s": (srv, psrv, mac_srv)}
        self.seq = {"c": 1000, "s": 50000}
        self.paq = []
        self.ip_id = 1

    def _seg(self, t, de, flags, datos=b""):
        a = "s" if de == "c" else "c"
        (ip_o, p_o, mac_o), (ip_d, p_d, mac_d) = self.ext[de], self.ext[a]
        ack = self.seq[a] if flags & 0x10 else 0
        o, d = bytes(map(int, ip_o.split("."))), bytes(map(int, ip_d.split(".")))
        tcp = struct.pack("!HHIIBBHHH", p_o, p_d, self.seq[de], ack, 5 << 4, flags, 64240, 0, 0) + datos
        pseudo = o + d + struct.pack("!BBH", 0, 6, len(tcp))
        tcp = tcp[:16] + struct.pack("!H", suma16(pseudo + tcp)) + tcp[18:]
        ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), self.ip_id, 0x4000, 64, 6, 0, o, d)
        ip = ip[:10] + struct.pack("!H", suma16(ip)) + ip[12:]
        self.ip_id += 1
        eth = bytes.fromhex(mac_d) + bytes.fromhex(mac_o) + b"\x08\x00" + ip + tcp
        self.paq.append((t, eth + bytes(max(0, 60 - len(eth)))))
        self.seq[de] = (self.seq[de] + len(datos) + (1 if flags & 0x03 else 0)) & 0xFFFFFFFF

    def abrir(self, t):
        self._seg(t, "c", 0x02)
        self._seg(t + 0.0004, "s", 0x12)
        self._seg(t + 0.0005, "c", 0x10)

    def datos(self, t, de, b, ack_tras=0.0003):
        self._seg(t, de, 0x18, b)
        self._seg(t + ack_tras, "s" if de == "c" else "c", 0x10)


def captura_dnp3(ruta):
    MAESTRO, ESTACION = 1, 10
    c = Tcp("192.168.1.100", "192.168.1.30", 51022, 20000, "02420a000064", "00e0b1300a1e")
    c.abrir(T0)

    def pide(t, seq_t, seq_a, fc, objetos):
        apl = bytes([0xC0 | seq_a, fc]) + objetos
        c.datos(t, "c", trama_dnp(0xC4, ESTACION, MAESTRO, bytes([0xC0 | seq_t]) + apl))

    def responde(t, seq_t, ctrl_apl, fc, iin, objetos):
        apl = bytes([ctrl_apl, fc]) + iin + objetos
        c.datos(t, "s", trama_dnp(0x44, MAESTRO, ESTACION, bytes([0xC0 | seq_t]) + apl))

    clases = b"\x3c\x02\x06\x3c\x03\x06\x3c\x04\x06\x3c\x01\x06"            # clases 1, 2, 3 y 0
    # entradas binarias (g1v2: con flags) 0..3 y analogicas (g30v1: 32 bits con flags) 0..3
    bi = b"\x01\x02\x00\x00\x03" + bytes([0x81, 0x01, 0x81, 0x01])
    ai_val = [13800, 245, 61, 6000]          # tension 13,8 kV (V), corriente (A), temperatura (C), frecuencia (cHz)
    ai = b"\x1e\x01\x00\x00\x03" + b"".join(b"\x01" + struct.pack("<i", v) for v in ai_val)
    iin = b"\x00\x00"
    pide(T0 + 0.010, 0, 0, 0x01, clases)
    responde(T0 + 0.032, 0, 0xC0, 0x81, iin, bi + ai)
    # evento no solicitado (RBE): la temperatura del transformador (AI2) sube a 74 C
    ev = b"\x20\x01\x17\x01\x02" + b"\x01" + struct.pack("<i", 74)           # g32v1, indice 2
    responde(T0 + 3.200, 1, 0xF0, 0x82, b"\x02\x00", ev)                      # IIN1.1: hay eventos de clase 1
    pide(T0 + 3.215, 1, 0, 0x00, b"")                                         # confirmacion (UNS)
    # sondeo de eventos de clase 1 a los 5 s: ya no queda ninguno
    pide(T0 + 5.000, 2, 1, 0x01, b"\x3c\x02\x06")
    responde(T0 + 5.018, 2, 0xC1, 0x81, iin, b"")
    pcap(ruta, 1, c.paq)


# ── DeviceNet sobre CAN ──────────────────────────────────────────────────────
def captura_devicenet(ruta):
    paq = []
    entradas = {10: 0x0005, 11: 0x0102, 12: 0x0000}
    t = T0
    for ciclo in range(30):
        for mac in (10, 11, 12):
            pid = 0x400 | (mac << 3) | 5                     # grupo 2, mensaje 5: sondeo del maestro
            paq.append((t, struct.pack(">IB3x", pid, 1) + b"\x01" + bytes(7)))
            t += 0.00025
            rid = (0xF << 6) | mac                           # grupo 1, mensaje 15: respuesta de E/S
            v = entradas[mac] ^ (0x0100 if (mac == 11 and ciclo >= 15) else 0)
            paq.append((t, struct.pack(">IB3x", rid, 2) + struct.pack("<H", v) + bytes(6)))
            t += 0.00030
        t = T0 + (ciclo + 1) * 0.010
    pcap(ruta, 227, paq)                                     # LINKTYPE_CAN_SOCKETCAN


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    if d.endswith(".pcap"):                 # montaje de la practica: la ruta de uno de los tres
        d = os.path.dirname(d)
    os.makedirs(d, exist_ok=True)
    captura_goose(os.path.join(d, "u4_goose.pcap"))
    captura_dnp3(os.path.join(d, "u4_dnp3.pcap"))
    captura_devicenet(os.path.join(d, "u4_devicenet.pcap"))
    print("capturas en", d)


if __name__ == "__main__":
    main()
