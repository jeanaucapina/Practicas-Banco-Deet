#!/usr/bin/env python3
"""Genera l8_planta.pcapng, la captura «provista» de la practica L8 (PROFINET).

    python l8_captura_planta.py salida.pcapng [segundos]

Linea LB-3 (la de la Practica L5): 1 IO-Controller y 4 IO-Devices en linea, ciclo de
4 ms (RT Clase 1). La captura la hizo un TAP agregador de cuatro enlaces:
  interfaz 0  tap-lb3-l1  enlace PLC <-> ET200SP (pasa TODO el trafico de la linea)
  interfaz 1..3           enlaces siguientes, filtrados a LLDP (para el Reto de topologia)
Arranque en los primeros 2 s (LLDP, DCP Identify All, DCP Identify por nombre, DCP Set IP,
ARP, RPC Connect / PrmEnd / ApplicationReady) y despues el regimen permanente: salidas
FrameID 0x8000-0x8003 del controlador y entradas 0x8100-0x8103 de los dispositivos, con
etiqueta 802.1Q PCP 6, contador de ciclo +128 por ciclo y DataStatus 0x35. Dos alarmas
(0xFC01 alta y 0xFE01 baja) con su confirmacion. Todo construido byte a byte (struct),
sin scapy, y determinista (misma semilla = mismo archivo).
"""
import random
import struct
import sys
import uuid

SALIDA = sys.argv[1] if len(sys.argv) > 1 else "l8_planta.pcapng"
DURACION = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
CICLO = 0.004
INICIO_RT = 2.05                      # el regimen ciclico arranca tras el establecimiento
rnd = random.Random(8892)

# ── La planta ───────────────────────────────────────────────────────────────
#            nombre de estacion   tipo (DeviceVendorValue)     MAC base             IP            vendor dev  in  out
CTRL = dict(nombre="plc-lb3", tipo="S7-1500 CPU 1515-2 PN", mac="00:1b:1b:6a:31:01", ip="192.168.0.1",
            vendor=0x002A, dev=0x0110, rol=0x02)
DISPOSITIVOS = [
    dict(nombre="et200sp-lb3-01", tipo="ET 200SP IM155-6 PN ST", mac="28:63:36:a1:07:21", ip="192.168.0.11",
         vendor=0x002A, dev=0x0313, n_in=40, n_out=40),
    dict(nombre="axl-f-lb3-02", tipo="AXL F BK PN TPS", mac="00:a0:45:9c:12:40", ip="192.168.0.12",
         vendor=0x00B0, dev=0x0161, n_in=32, n_out=40),
    dict(nombre="wago-750-lb3-03", tipo="750-375 PROFINET IO", mac="00:30:de:41:5e:83", ip="192.168.0.13",
         vendor=0x011D, dev=0x02EE, n_in=16, n_out=40),
    dict(nombre="cpx-ap-lb3-04", tipo="CPX-AP-I-PN-M12", mac="00:0e:f0:7b:22:9a", ip="192.168.0.14",
         vendor=0x014D, dev=0x0102, n_in=8, n_out=40),
]
MASCARA, PUERTA = "255.255.255.0", "0.0.0.0"


def mac(t: str, mas: int = 0) -> bytes:
    b = bytearray(int(x, 16) for x in t.split(":"))
    b[5] = (b[5] + mas) & 0xFF
    return bytes(b)


def ip4(t: str) -> bytes:
    return bytes(int(x) for x in t.split("."))


def rellenar(trama: bytes, minimo: int = 60) -> bytes:
    return trama + b"\x00" * max(0, minimo - len(trama))


# ── Ethernet / VLAN ─────────────────────────────────────────────────────────
def eth(dst: bytes, src: bytes, etype: int, carga: bytes, pcp: int = None) -> bytes:
    if pcp is None:
        return rellenar(dst + src + struct.pack("!H", etype) + carga)
    # 802.1Q: TPID 0x8100 + TCI (PCP en los 3 bits altos, VID 0); minimo 64 B etiquetada
    return rellenar(dst + src + struct.pack("!HHH", 0x8100, pcp << 13, etype) + carga, 64)


# ── DCP ─────────────────────────────────────────────────────────────────────
DCP_MC = mac("01:0e:cf:00:00:00")


def bloque(op: int, sub: int, datos: bytes) -> bytes:
    b = struct.pack("!BBH", op, sub, len(datos)) + datos
    return b + (b"\x00" if len(datos) % 2 else b"")      # los bloques van alineados a 2


def dcp(frame_id: int, servicio: int, tipo: int, xid: int, retardo: int, bloques: bytes) -> bytes:
    return struct.pack("!HBBIHH", frame_id, servicio, tipo, xid, retardo, len(bloques)) + bloques


def bloques_identidad(d: dict, rol: int = 0x01) -> bytes:
    info = struct.pack("!H", 0)
    return (bloque(2, 1, info + d["tipo"].encode())                       # TypeOfStation
            + bloque(2, 2, info + d["nombre"].encode())                   # NameOfStation
            + bloque(2, 3, info + struct.pack("!HH", d["vendor"], d["dev"]))   # DeviceID
            + bloque(2, 4, info + struct.pack("!BB", rol, 0))             # DeviceRole
            + bloque(2, 5, info + bytes([1, 1, 1, 2, 2, 1, 2, 2, 2, 3, 2, 4, 2, 5, 5, 3]))  # DeviceOptions
            + bloque(1, 2, struct.pack("!H", 1) + ip4(d["ip"]) + ip4(MASCARA) + ip4(PUERTA)))  # IP


# ── LLDP ────────────────────────────────────────────────────────────────────
LLDP_MC = mac("01:80:c2:00:00:0e")


def tlv(t: int, v: bytes) -> bytes:
    return struct.pack("!H", (t << 9) | len(v)) + v


def lldp(d: dict, puerto: int, n_puertos: int) -> bytes:
    nombre = d["nombre"].encode()
    port_id = ("port-%03d" % puerto).encode()
    cuerpo = (tlv(1, b"\x07" + nombre)                          # Chassis ID (local = NameOfStation)
              + tlv(2, b"\x07" + port_id)                       # Port ID (local)
              + tlv(3, struct.pack("!H", 20))                   # TTL 20 s
              + tlv(4, ("%s, Port %d (%d)" % (d["tipo"], puerto, n_puertos)).encode())   # Port Description
              + tlv(5, nombre)                                  # System Name
              + tlv(6, ("%s; PROFINET IO" % d["tipo"]).encode())                        # System Description
              + tlv(7, struct.pack("!HH", 0x0080, 0x0080))      # Capabilities: station only
              + tlv(8, struct.pack("!BB", 5, 1) + ip4(d["ip"]) + struct.pack("!BIB", 2, 1, 0))  # Mgmt address
              # IEEE 802.3 MAC/PHY: autonegociacion activa, 100BASE-TX full duplex (MAU 16)
              + tlv(127, bytes([0x00, 0x12, 0x0f, 0x01, 0x03]) + struct.pack("!HH", 0x6C00, 16))
              # PROFINET (OUI 00-0e-cf) subtipo 2 Port Status: RTClass2/3 sin uso
              + tlv(127, bytes([0x00, 0x0e, 0xcf, 0x02]) + struct.pack("!HH", 0, 0))
              # PROFINET subtipo 5 Chassis MAC
              + tlv(127, bytes([0x00, 0x0e, 0xcf, 0x05]) + mac(d["mac"]))
              + tlv(0, b""))
    return eth(LLDP_MC, mac(d["mac"], puerto), 0x88CC, cuerpo)


# ── ARP ─────────────────────────────────────────────────────────────────────
def arp(op: int, smac: bytes, sip: str, tmac: bytes, tip: str, dst: bytes) -> bytes:
    a = struct.pack("!HHBBH", 1, 0x0800, 6, 4, op) + smac + ip4(sip) + tmac + ip4(tip)
    return eth(dst, smac, 0x0806, a)


# ── IPv4 / UDP / DCE-RPC (PNIO-CM) ──────────────────────────────────────────
def csum(b: bytes) -> int:
    if len(b) % 2:
        b += b"\x00"
    s = sum(struct.unpack("!%dH" % (len(b) // 2), b))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


_ip_id = [0x3100]


def udp_ip(smac, dmac, sip, dip, sport, dport, carga):
    u = struct.pack("!HHHH", sport, dport, 8 + len(carga), 0) + carga
    _ip_id[0] += 1
    cab = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(u), _ip_id[0] & 0xFFFF, 0x4000, 64, 17, 0, ip4(sip), ip4(dip))
    cab = cab[:10] + struct.pack("!H", csum(cab)) + cab[12:]
    return eth(dmac, smac, 0x0800, cab + u)


IF_DEVICE = uuid.UUID("dea00001-6c97-11d1-8271-00a02442df7d")       # PNIO-Device interface
IF_CONTROLLER = uuid.UUID("dea00002-6c97-11d1-8271-00a02442df7d")   # PNIO-Controller interface


def objeto(instancia: int, d: dict) -> uuid.UUID:
    return uuid.UUID("dea00000-6c97-11d1-8271-%04x%04x%04x" % (instancia, d["dev"], d["vendor"]))


def dcerpc(ptype: int, obj: uuid.UUID, iface: uuid.UUID, act: uuid.UUID, seq: int, opnum: int, ndr: bytes) -> bytes:
    flags1 = 0x20 if ptype == 0 else 0x0A          # idempotent / last frag + no fack
    return (struct.pack("<BBBB", 4, ptype, flags1, 0) + bytes([0x10, 0, 0]) + b"\x00"
            + obj.bytes_le + iface.bytes_le + act.bytes_le
            + struct.pack("<IIIHHHHHBB", 0, 1, seq, opnum, 0xFFFF, 0xFFFF, len(ndr), 0, 0, 0) + ndr)


def ndr_peticion(bloques: bytes) -> bytes:
    return struct.pack("<IIIII", 0x4000, len(bloques), 0x4000, 0, len(bloques)) + bloques


def ndr_respuesta(bloques: bytes) -> bytes:
    return b"\x00\x00\x00\x00" + struct.pack("<IIII", len(bloques), 0x4000, 0, len(bloques)) + bloques


def pn_bloque(tipo: int, cuerpo: bytes) -> bytes:
    return struct.pack("!HHBB", tipo, len(cuerpo) + 2, 1, 0) + cuerpo


def ar_block_req(ar: uuid.UUID, d: dict) -> bytes:
    nombre = CTRL["nombre"].encode()
    return pn_bloque(0x0101, struct.pack("!H", 0x0001) + ar.bytes + struct.pack("!H", 1) + mac(CTRL["mac"])
                     + objeto(1, CTRL).bytes + struct.pack("!IHHH", 0x00000131, 100, 0x8892, len(nombre)) + nombre)


def iocr_block_req(tipo: int, ref: int, frame_id: int, largo: int) -> bytes:
    # IOCRType (1 entrada / 2 salida), referencia, LT 0x8892, propiedades RT_CLASS_1,
    # DataLength, FrameID, SendClockFactor 32, ReductionRatio 4 (=> 4 ms), Phase 1,
    # Sequence 0, FrameSendOffset 0xFFFFFFFF, WatchdogFactor 3, DataHoldFactor 3,
    # IOCRTagHeader (PCP 6), multicast MAC 0 y ninguna API.
    return pn_bloque(0x0102, struct.pack("!HHHIHHHHHHIHHH6sH", tipo, ref, 0x8892, 0x00000001, largo, frame_id,
                                         32, 4, 1, 0, 0xFFFFFFFF, 3, 3, 0xC000, b"\x00" * 6, 0))


def alarm_cr_block_req() -> bytes:
    # AlarmCRType, LT, propiedades, RTATimeoutFactor, RTARetries, LocalAlarmReference,
    # MaxAlarmDataLength y las etiquetas 802.1Q de alta (PCP 6) y baja (PCP 5) prioridad
    return pn_bloque(0x0103, struct.pack("!HHIHHHHHH", 1, 0x8892, 0, 100, 3, 1, 200, 0xC000, 0xA000))


def ar_block_res(ar: uuid.UUID, d: dict) -> bytes:
    return pn_bloque(0x8101, struct.pack("!H", 0x0001) + ar.bytes + struct.pack("!H", 1) + mac(d["mac"])
                     + struct.pack("!H", 0x8892))


def control_req(tipo: int, ar: uuid.UUID, comando: int) -> bytes:
    # Reserved, ARUUID, SessionKey, Reserved, ControlCommand, ControlBlockProperties
    return pn_bloque(tipo, b"\x00\x00" + ar.bytes + struct.pack("!HHHH", 1, 0, comando, 0))


# ── RT ciclico y alarmas ────────────────────────────────────────────────────
def rt(dst, src, frame_id, datos, contador, data_status=0x35, pcp=6):
    return eth(dst, src, 0x8892, struct.pack("!H", frame_id) + datos
               + struct.pack("!HBB", contador & 0xFFFF, data_status, 0), pcp)


def rta(dst, src, frame_id, pdu_tipo, envio, ack, cuerpo=b"", pcp=6):
    return eth(dst, src, 0x8892, struct.pack("!HHHBBHHH", frame_id, 1, 1, pdu_tipo, 0x01, envio, ack, len(cuerpo))
               + cuerpo, pcp)


# ── Montaje de la captura ───────────────────────────────────────────────────
tramas = []   # (t, interfaz, bytes)


def poner(t, trama, interfaz=0):
    tramas.append((t, interfaz, trama))


mc = mac(CTRL["mac"], 1)          # puerto 1 del controlador: el que emite el trafico de E/S

# LLDP: cada puerto enlazado cada 5 s. Linea: PLC p1 - D1 p1 | D1 p2 - D2 p1 | ... | D3 p2 - D4 p1
enlaces = [(CTRL, 1, DISPOSITIVOS[0], 1)] + [(DISPOSITIVOS[i], 2, DISPOSITIVOS[i + 1], 1) for i in range(3)]
for k, (a, pa, b, pb) in enumerate(enlaces):
    for t0 in [0.020 + 0.011 * k + 5.0 * j for j in range(int(DURACION // 5) + 1)]:
        if t0 < DURACION:
            poner(t0, lldp(a, pa, 1 if a is CTRL else 2), k)
            poner(t0 + 0.0031, lldp(b, pb, 2), k)

t = 0.150
# DCP Identify All (multidifusion) y las cuatro respuestas, cada una tras su ResponseDelay
xid = 0x01000001
poner(t, eth(DCP_MC, mc, 0x8892, dcp(0xFEFE, 5, 0, xid, 0x0080, bloque(0xFF, 0xFF, b""))))
for i, d in enumerate(DISPOSITIVOS):
    poner(t + 0.0021 + 0.0137 * i, eth(mc, mac(d["mac"]), 0x8892, dcp(0xFEFF, 5, 1, xid, 0, bloques_identidad(d))))

contadores = {}
t = 0.420
for i, d in enumerate(DISPOSITIVOS):
    dm = mac(d["mac"])
    xid += 1
    # Identify por NameOfStation: el controlador busca a cada dispositivo por su nombre
    poner(t, eth(DCP_MC, mc, 0x8892, dcp(0xFEFE, 5, 0, xid, 0x0001, bloque(2, 2, d["nombre"].encode()))))
    poner(t + 0.0009, eth(mc, dm, 0x8892, dcp(0xFEFF, 5, 1, xid, 0, bloques_identidad(d))))
    # Set IP (temporal): la direccion la decide el controlador por el nombre
    xid += 1
    poner(t + 0.0040, eth(dm, mc, 0x8892, dcp(0xFEFD, 4, 0, xid, 0,
                                              bloque(1, 2, struct.pack("!H", 0) + ip4(d["ip"]) + ip4(MASCARA)
                                                     + ip4(PUERTA)))))
    poner(t + 0.0061, eth(mc, dm, 0x8892, dcp(0xFEFD, 4, 1, xid, 0, bloque(5, 4, bytes([1, 2, 0])))))
    # ARP: comprobacion de duplicado y resolucion antes del RPC
    poner(t + 0.0300, arp(1, mc, CTRL["ip"], b"\x00" * 6, d["ip"], mac("ff:ff:ff:ff:ff:ff")))
    poner(t + 0.0304, arp(2, dm, d["ip"], mc, CTRL["ip"], mc))
    # RPC Connect (opnum 0): ARBlockReq + 2 IOCRBlockReq + AlarmCRBlockReq
    ar = uuid.UUID(int=rnd.getrandbits(128))
    act = uuid.UUID(int=rnd.getrandbits(128))
    sport = 0xC001 + i
    con = (ar_block_req(ar, d) + iocr_block_req(1, 1, 0x8100 + i, d["n_in"])
           + iocr_block_req(2, 2, 0x8000 + i, d["n_out"]) + alarm_cr_block_req())
    poner(t + 0.0500, udp_ip(mc, dm, CTRL["ip"], d["ip"], sport, 34964,
                             dcerpc(0, objeto(1, d), IF_DEVICE, act, 0, 0, ndr_peticion(con))))
    poner(t + 0.0587, udp_ip(dm, mc, d["ip"], CTRL["ip"], 34964, sport,
                             dcerpc(2, objeto(1, d), IF_DEVICE, act, 0, 0, ndr_respuesta(ar_block_res(ar, d)))))
    # Control PrmEnd (opnum 4) y su respuesta
    poner(t + 0.1200, udp_ip(mc, dm, CTRL["ip"], d["ip"], sport, 34964,
                             dcerpc(0, objeto(1, d), IF_DEVICE, act, 1, 4, ndr_peticion(control_req(0x0110, ar, 0x0001)))))
    poner(t + 0.1241, udp_ip(dm, mc, d["ip"], CTRL["ip"], 34964, sport,
                             dcerpc(2, objeto(1, d), IF_DEVICE, act, 1, 4, ndr_respuesta(control_req(0x8110, ar, 0x0008)))))
    # ApplicationReady: lo pide el DISPOSITIVO al controlador (interfaz de controlador)
    act2 = uuid.UUID(int=rnd.getrandbits(128))
    poner(t + 0.2900, udp_ip(dm, mc, d["ip"], CTRL["ip"], 0xC101 + i, 34964,
                             dcerpc(0, objeto(1, CTRL), IF_CONTROLLER, act2, 0, 4,
                                    ndr_peticion(control_req(0x0112, ar, 0x0002)))))
    poner(t + 0.2933, udp_ip(mc, dm, CTRL["ip"], d["ip"], 34964, 0xC101 + i,
                             dcerpc(2, objeto(1, CTRL), IF_CONTROLLER, act2, 0, 4,
                                    ndr_respuesta(control_req(0x8112, ar, 0x0008)))))
    contadores[i] = [rnd.randrange(0, 0x10000, 32), rnd.randrange(0, 0x10000, 32)]
    t += 0.360

# Regimen permanente: en cada ciclo, salidas del controlador a cada dispositivo
# (desfasadas 20 us entre si) y entradas de cada dispositivo. Jitter: controlador
# ~3 us, dispositivos ~12 us (sellado por el TAP, no por software).
n_ciclos = int((DURACION - INICIO_RT) / CICLO)
alarmas = {int((17.30 - INICIO_RT) / CICLO): ("alta", 2), int((23.10 - INICIO_RT) / CICLO): ("baja", 2)}
for c in range(n_ciclos):
    base = INICIO_RT + c * CICLO
    for i, d in enumerate(DISPOSITIVOS):
        dm = mac(d["mac"])
        # Salidas: imagen de proceso con un byte que cambia (contador de piezas) y IOCS 0x80
        q = bytearray(d["n_out"])
        q[0] = (c // 250) & 0xFF
        q[1] = 0x05 if (c // 500) % 2 else 0x01
        for k in range(3, d["n_out"], 4):
            q[k] = 0x80
        poner(base + 0.000020 * i + rnd.gauss(0, 3e-6),
              rt(dm, mc, 0x8000 + i, bytes(q), contadores[i][0]))
        contadores[i][0] = (contadores[i][0] + 128) & 0xFFFF
        # Entradas: valores analogicos que derivan y IOPS 0x80
        e = bytearray(d["n_in"])
        if d["n_in"] >= 4:
            struct.pack_into("!H", e, 0, int(13824 + 900 * ((c % 1000) / 1000.0)) & 0xFFFF)
        for k in range(3, d["n_in"], 4):
            e[k] = 0x80
        poner(base + 0.000600 + 0.000025 * i + rnd.gauss(0, 12e-6),
              rt(mc, dm, 0x8100 + i, bytes(e), contadores[i][1]))
        contadores[i][1] = (contadores[i][1] + 128) & 0xFFFF
    if c in alarmas:
        prio, i = alarmas[c]
        d = DISPOSITIVOS[i]
        dm = mac(d["mac"])
        fid = 0xFC01 if prio == "alta" else 0xFE01
        # AlarmNotification: tipo 0x0001 Diagnosis (alta) / 0x0004 Pull... aqui 0x0001 y 0x000C
        cuerpo = pn_bloque(0x0001 if prio == "alta" else 0x0002, struct.pack("!HIHHIIH", 0x0001 if prio == "alta" else 0x000C,
                                                                            0, 1, 1, 0x00000001, 0x00000100, 0x8001))
        poner(base + 0.0019, rta(mc, dm, fid, 0x11, 1, 0xFFFF, cuerpo, 6 if prio == "alta" else 5))
        poner(base + 0.0023, rta(dm, mc, fid, 0x13, 0xFFFF, 1, b"", 6 if prio == "alta" else 5))       # ACK-RTA
        poner(base + 0.0310, rta(dm, mc, fid, 0x11, 1, 1, pn_bloque(0x8001 if prio == "alta" else 0x8002,
                                                                     struct.pack("!HIHHHI", 1, 0, 1, 1, 0x8001, 0)),
                                 6 if prio == "alta" else 5))                                         # AlarmAck
        poner(base + 0.0314, rta(mc, dm, fid, 0x13, 0xFFFF, 1, b"", 6 if prio == "alta" else 5))

tramas.sort(key=lambda x: x[0])

# ── pcapng: SHB + una IDB por interfaz del TAP + EPB por trama ───────────────
def opcion(codigo: int, valor: bytes) -> bytes:
    return struct.pack("<HH", codigo, len(valor)) + valor + b"\x00" * (-len(valor) % 4)


def bloque_png(tipo: int, cuerpo: bytes) -> bytes:
    largo = 12 + len(cuerpo)
    return struct.pack("<II", tipo, largo) + cuerpo + struct.pack("<I", largo)


NOMBRES = ["tap-lb3-l1 (PLC <-> ET200SP, todo)", "tap-lb3-l2 (solo LLDP)", "tap-lb3-l3 (solo LLDP)",
           "tap-lb3-l4 (solo LLDP)"]
with open(SALIDA, "wb") as f:
    f.write(bloque_png(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1)
                       + opcion(3, b"DEET - captura provista L8 (linea LB-3, sintetica y documentada)")
                       + opcion(4, b"l8_captura_planta.py") + opcion(0, b"")))
    for n in NOMBRES:
        f.write(bloque_png(1, struct.pack("<HHI", 1, 0, 0) + opcion(2, n.encode()) + opcion(9, b"\x06")
                           + opcion(0, b"")))
    origen = 1792656000 * 1000000          # 2026-10-21 05:20:00 UTC, en microsegundos
    for t, i, b in tramas:
        us = origen + int(round(t * 1e6))
        f.write(bloque_png(6, struct.pack("<IIIII", i, us >> 32, us & 0xFFFFFFFF, len(b), len(b))
                           + b + b"\x00" * (-len(b) % 4)))
print("%s: %d tramas, %.1f s" % (SALIDA, len(tramas), DURACION))
