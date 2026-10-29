"""Decodificador de tramas para la pantalla del PC en las gafas.

Un Wireshark de bolsillo: lee el pcap en vivo de tab-lan (lo produce
herramientas/sniffer.py dentro de un contenedor con NET_RAW) y las tramas del
bus RS-485 que ya recibe la pasarela, y deja para cada una un resumen de una
linea y el desglose de sus bytes por campos.

Protocolos: Modbus TCP (MBAP + PDU), Modbus RTU (con CRC), MQTT, S7comm (el
S7-1200 simulado, puerto 102), ICMP, ARP y el arranque / cierre de las
conexiones TCP.
"""

import struct
import time

FC = {1: "Read Coils", 2: "Read Discrete Inputs", 3: "Read Holding Registers",
      4: "Read Input Registers", 5: "Write Single Coil", 6: "Write Single Register",
      15: "Write Multiple Coils", 16: "Write Multiple Registers"}
EXC = {1: "funcion ilegal", 2: "direccion ilegal", 3: "valor ilegal", 4: "fallo del esclavo"}
MQTT = {1: "CONNECT", 2: "CONNACK", 3: "PUBLISH", 4: "PUBACK", 8: "SUBSCRIBE", 9: "SUBACK",
        12: "PINGREQ", 13: "PINGRESP", 14: "DISCONNECT"}


def nombre_ip(ip):
    p = ip.split(".")
    if ip.startswith("192.168.1."):         # segmento del banco (guias del curso)
        h = int(p[3])
        nombres = {1: "pasarela", 100: "PC", 101: "atacante", 50: "broker", 60: "NodeRED",
                   40: "S7-1200", 31: "OpenPLC1", 32: "OpenPLC2", 10: "ESP1", 20: "ESP2",
                   11: "CTL1", 12: "CTL2"}
        otlab = {200: "OpenPLC", 201: "Ignition", 202: "FUXA", 203: "NodeRED-OT", 204: "Mosq-OT",
                 205: "ModSim", 206: "OPCUApy", 207: "OPC-PLC", 208: "Conpot"}
        if h in nombres:
            return nombres[h]
        if h in otlab:
            return otlab[h]
        if 150 <= h <= 199:
            return "DHCP%d" % h
    if ip.startswith("172.30.85."):
        h = int(p[3])
        if h == 1:
            return "PC(USB485)"
        if 11 <= h <= 19:
            return "CTL%d" % (h - 10)
        if 21 <= h <= 29:
            return "ESP%d" % (h - 20)
    return ip


def hexa(b):
    return " ".join("%02X" % x for x in b)


def _crc16(datos):
    crc = 0xFFFF
    for b in datos:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def pdu_modbus(pdu, peticion):
    """Resumen y campos [(nombre, bytes)] de una PDU Modbus."""
    if not pdu:
        return "PDU vacia", []
    fc = pdu[0]
    if fc & 0x80:
        cod = pdu[1] if len(pdu) > 1 else 0
        return ("EXCEPCION %d (%s) a FC%d" % (cod, EXC.get(cod, "?"), fc & 0x7F),
                [("funcion|0x80", pdu[:1]), ("codigo excepcion", pdu[1:2])])
    nom = "FC%d %s" % (fc, FC.get(fc, "?"))
    campos = [("funcion", pdu[:1])]
    try:
        if fc in (1, 2, 3, 4):
            if peticion:
                ini, n = struct.unpack(">HH", pdu[1:5])
                campos += [("direccion inicial", pdu[1:3]), ("cantidad", pdu[3:5])]
                return "%s  dir %d  cant %d" % (nom, ini, n), campos
            nb = pdu[1]
            datos = pdu[2:2 + nb]
            campos += [("n.º de bytes", pdu[1:2]), ("datos", datos)]
            if fc <= 2:
                bits = "".join(str((datos[i // 8] >> (i % 8)) & 1) for i in range(nb * 8))
                return "%s  resp  bits %s" % (nom, bits[:24]), campos
            regs = [struct.unpack(">H", datos[i:i + 2])[0] for i in range(0, nb - 1, 2)]
            return "%s  resp  %s" % (nom, regs[:8]), campos
        if fc in (5, 6):
            d, v = struct.unpack(">HH", pdu[1:5])
            campos += [("direccion", pdu[1:3]), ("valor", pdu[3:5])]
            val = ("ON" if v == 0xFF00 else "OFF") if fc == 5 else str(v)
            return "%s  dir %d = %s%s" % (nom, d, val, "" if peticion else "  (eco)"), campos
        if fc in (15, 16):
            ini, n = struct.unpack(">HH", pdu[1:5])
            campos += [("direccion inicial", pdu[1:3]), ("cantidad", pdu[3:5])]
            if peticion:
                nb = pdu[5]
                datos = pdu[6:6 + nb]
                campos += [("n.º de bytes", pdu[5:6]), ("valores", datos)]
                if fc == 15:
                    bits = "".join(str((datos[i // 8] >> (i % 8)) & 1) for i in range(n))
                    return "%s  dir %d cant %d  bits %s" % (nom, ini, n, bits), campos
                return "%s  dir %d cant %d" % (nom, ini, n), campos
            return "%s  dir %d cant %d  (confirmado)" % (nom, ini, n), campos
    except (struct.error, IndexError):
        pass
    return nom, campos


S7_AREA = {0x81: "I", 0x82: "Q", 0x83: "M", 0x84: "DB", 0x1C: "C", 0x1D: "T"}
S7_ROSCTR = {1: "Job", 2: "Ack", 3: "Ack_Data", 7: "Userdata"}
S7_FUNC = {0x04: "Read Var", 0x05: "Write Var", 0xF0: "Setup comm"}


def _s7_item(it):
    """Direccion S7 de un item de peticion (12 B): "DB1.DBB0 x16", "Q0.0"..."""
    ts, n, db, area = it[3], struct.unpack(">H", it[4:6])[0], struct.unpack(">H", it[6:8])[0], it[8]
    dirb = int.from_bytes(it[9:12], "big")
    byte, bit = dirb >> 3, dirb & 7
    a = S7_AREA.get(area, "area%02X" % area)
    if ts == 1:                                   # BIT
        return ("DB%d.DBX%d.%d" % (db, byte, bit)) if area == 0x84 else "%s%d.%d" % (a, byte, bit)
    return ("DB%d.DBB%d x%d" % (db, byte, n)) if area == 0x84 else "%sB%d x%d" % (a, byte, n)


def s7comm(datos):
    """TPKT + COTP + S7comm (lo justo para leer una sesion de cliente)."""
    if len(datos) < 7 or datos[0] != 3:
        return None
    cotp = datos[5]
    if cotp == 0xE0:
        return "COTP peticion de conexion", "pet", [("TPKT", datos[:4]), ("COTP CR", datos[4:])]
    if cotp == 0xD0:
        return "COTP conexion aceptada", "resp", [("TPKT", datos[:4]), ("COTP CC", datos[4:])]
    s7 = datos[4 + 1 + datos[4]:]
    if len(s7) < 10 or s7[0] != 0x32:
        return None
    rosctr = s7[1]
    plen, dlen = struct.unpack(">HH", s7[6:10])
    cab = 12 if rosctr in (2, 3) else 10
    par, dat = s7[cab:cab + plen], s7[cab + plen:cab + plen + dlen]
    campos = [("TPKT", datos[:4]), ("COTP DT", datos[4:7]), ("S7 cabecera", s7[:cab]),
              ("S7 parametros", par), ("S7 datos", dat[:24])]
    if not par:
        return "S7 %s" % S7_ROSCTR.get(rosctr, rosctr), "info", campos
    func = S7_FUNC.get(par[0], "funcion %02X" % par[0])
    if rosctr == 3 and len(s7) >= 12 and s7[10]:
        return "S7 ERROR %02X%02X en %s" % (s7[10], s7[11], func), "mal", campos
    if par[0] in (0x04, 0x05) and rosctr == 1 and len(par) >= 14:
        items = [_s7_item(par[2 + 12 * i:14 + 12 * i]) for i in range(par[1]) if len(par) >= 14 + 12 * i]
        res = "%s %s" % (func, ", ".join(items))
        if par[0] == 0x05 and len(dat) > 4:
            res += " = " + hexa(dat[4:12])
        return res, "pet", campos
    if rosctr == 3 and par[0] in (0x04, 0x05):
        if par[0] == 0x05:
            ok = all(b == 0xFF for b in dat[:par[1]])
            return "Ack %s %s" % (func, "OK" if ok else "RECHAZADA"), "resp" if ok else "mal", campos
        if len(dat) >= 4 and dat[0] != 0xFF:
            return "Ack %s RECHAZADA (codigo %02X: ¿PUT/GET?)" % (func, dat[0]), "mal", campos
        return "Ack %s OK  %s" % (func, hexa(dat[4:12])), "resp", campos
    return "S7 %s %s" % (S7_ROSCTR.get(rosctr, rosctr), func), "pet" if rosctr == 1 else "resp", campos


def rtu(datos, origen, bus):
    t = {"hora": time.strftime("%H:%M:%S"), "medio": "RS-485 bus %d" % bus,
         "de": nombre_ip(origen), "a": "bus", "hex": hexa(datos)}
    if len(datos) < 4:
        return {**t, "proto": "RTU", "resumen": "trama corta (%d B)" % len(datos), "tipo": "mal",
                "campos": []}
    crc_ok = _crc16(datos[:-2]) == struct.unpack("<H", datos[-2:])[0]
    unidad, pdu = datos[0], datos[1:-2]
    # En RTU la trama no dice si es peticion o respuesta; aqui se sabe por quien
    # la manda: si sale del Controllino cuya direccion es la de la trama (el
    # tablero n tiene la n por defecto), es la respuesta del esclavo.
    de = nombre_ip(origen)
    peticion = not (de.startswith("CTL") and de[3:] == str(unidad))
    res, campos = pdu_modbus(pdu, peticion)
    campos = [("direccion esclavo", datos[:1])] + campos + [("CRC " + ("OK" if crc_ok else "MAL"), datos[-2:])]
    if not crc_ok:
        return {**t, "proto": "RTU", "resumen": "CRC MAL (¿A/B cruzados?)", "tipo": "mal",
                "campos": campos}
    return {**t, "proto": "Modbus RTU", "resumen": "esclavo %d  %s" % (unidad, res),
            "tipo": "pet" if peticion else ("mal" if pdu[0] & 0x80 else "resp"), "campos": campos}


def ethernet(pkt):
    """Una trama Ethernet de tab-lan -> dict, o None si no interesa."""
    if len(pkt) < 14:
        return None
    tipo = struct.unpack(">H", pkt[12:14])[0]
    t = {"hora": time.strftime("%H:%M:%S"), "medio": "Ethernet"}
    if tipo == 0x0806 and len(pkt) >= 42:
        op = struct.unpack(">H", pkt[20:22])[0]
        spa = ".".join(map(str, pkt[28:32]))
        tpa = ".".join(map(str, pkt[38:42]))
        res = ("¿quien tiene %s? dilo a %s" % (tpa, spa)) if op == 1 else ("%s esta en %s" % (spa, pkt[22:28].hex(":")))
        return {**t, "proto": "ARP", "de": nombre_ip(spa), "a": nombre_ip(tpa), "resumen": res,
                "tipo": "info", "hex": hexa(pkt[14:42]), "campos": [("ARP", pkt[14:42])]}
    if tipo != 0x0800 or len(pkt) < 34:
        return None
    ihl = (pkt[14] & 0x0F) * 4
    proto = pkt[23]
    src = ".".join(map(str, pkt[26:30]))
    dst = ".".join(map(str, pkt[30:34]))
    t.update({"de": nombre_ip(src), "a": nombre_ip(dst)})
    l4 = 14 + ihl
    if proto == 1:
        it = pkt[l4]
        return {**t, "proto": "ICMP", "resumen": "ping " + ("peticion" if it == 8 else "respuesta" if it == 0 else str(it)),
                "tipo": "info", "hex": hexa(pkt[l4:l4 + 8]), "campos": [("ICMP", pkt[l4:l4 + 8])]}
    if proto != 6 or len(pkt) < l4 + 20:
        return None
    sp, dp = struct.unpack(">HH", pkt[l4:l4 + 4])
    off = (pkt[l4 + 12] >> 4) * 4
    flags = pkt[l4 + 13]
    datos = pkt[l4 + off:]
    ips_len = struct.unpack(">H", pkt[16:18])[0]
    datos = datos[:max(0, ips_len - ihl - off)]
    if not datos:
        # Sin carga: solo interesan el saludo y el cierre de la conexion.
        nombres = [n for bit, n in ((0x02, "SYN"), (0x01, "FIN"), (0x04, "RST")) if flags & bit]
        if not nombres:
            return None
        if flags & 0x10:
            nombres.append("ACK")
        return {**t, "proto": "TCP", "resumen": "%s  %d -> %d" % (",".join(nombres), sp, dp),
                "tipo": "mal" if flags & 0x04 else "info", "hex": "", "campos": []}
    if 502 in (sp, dp) and len(datos) >= 8:
        tid, pid, lon, uid = struct.unpack(">HHHB", datos[:7])
        pet = dp == 502
        res, campos = pdu_modbus(datos[7:7 + lon - 1], pet)
        campos = [("MBAP transaccion", datos[0:2]), ("MBAP protocolo", datos[2:4]),
                  ("MBAP longitud", datos[4:6]), ("MBAP unidad", datos[6:7])] + campos
        return {**t, "proto": "Modbus TCP", "resumen": "tid %d  %s" % (tid, res),
                "tipo": "pet" if pet else ("mal" if len(datos) > 7 and datos[7] & 0x80 else "resp"),
                "hex": hexa(datos[:40]), "campos": campos}
    if 102 in (sp, dp):
        r = s7comm(datos)
        if r:
            return {**t, "proto": "S7comm", "resumen": r[0], "tipo": r[1], "hex": hexa(datos[:40]),
                    "campos": r[2]}
        return None
    if 1883 in (sp, dp):
        pt = datos[0] >> 4
        res = MQTT.get(pt, "tipo %d" % pt)
        if pt == 3 and len(datos) > 4:
            i, lon = 1, 0
            mult = 1
            while i < len(datos):
                lon += (datos[i] & 0x7F) * mult
                mult *= 128
                i += 1
                if not datos[i - 1] & 0x80:
                    break
            nt = struct.unpack(">H", datos[i:i + 2])[0]
            tema = datos[i + 2:i + 2 + nt].decode(errors="replace")
            carga = datos[i + 2 + nt:].decode(errors="replace")
            res = "PUBLISH %s  %s" % (tema, carga[:60])
        return {**t, "proto": "MQTT", "resumen": res, "tipo": "info", "hex": hexa(datos[:40]),
                "campos": [("cabecera fija", datos[:2]), ("resto", datos[2:40])]}
    return None


class LectorPcap:
    """Trocea un flujo pcap (cabecera global + registros) que llega por trozos."""

    def __init__(self):
        self.buf = b""
        self.cabecera = False

    def meter(self, datos):
        self.buf += datos
        out = []
        if not self.cabecera:
            if len(self.buf) < 24:
                return out
            self.buf = self.buf[24:]
            self.cabecera = True
        while len(self.buf) >= 16:
            incl = struct.unpack("<I", self.buf[8:12])[0]
            if len(self.buf) < 16 + incl:
                break
            out.append(self.buf[16:16 + incl])
            self.buf = self.buf[16 + incl:]
        return out
