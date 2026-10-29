"""PROFINET simulado para la practica L8 (DCP / LLDP / RT).

No es una pila PROFINET: es un generador de las TRAMAS que un alumno analiza con
Wireshark, hechas a mano a nivel Ethernet (EtherType 0x8892 y 0x88CC), con la
estructura de las especificaciones y las mismas que decodifican los disectores
`lldp`, `pn_dcp` y `pn_rt` de Wireshark. Escenario:

  PLC (el S7-1200 simulado)   controlador de IO: manda DCP Identify All cada 10 s y
                              datos cíclicos de salida (RT clase 1) cada 100 ms
  Controllino 1 y 2           dispositivos de IO: responden al Identify, anuncian su
                              puerto por LLDP cada 5 s y mandan datos cíclicos de
                              entrada, que SON las entradas reales (A0-A15, I16-I18)

Un dispositivo solo existe si su cable Ethernet esta enchufado al switch (el mismo
`lan` que usa la pasarela): desenchufa el cable en el 3D y deja de aparecer, como
en un tablero fisico. Las tramas salen por el puente `tab-lan` (corre en la red del
anfitrion), de modo que Wireshark las ve en `tab-lan`.

Para que el puente deje pasar LLDP (01:80:C2:00:00:0E, de enlace local) hay que
subir `group_fwd_mask` de tab-lan; si /sys es de solo lectura se avisa y LLDP solo
se ve en los puertos, no en el puente.
"""

import json
import os
import socket
import struct
import time
import urllib.request

IFACE = os.environ.get("PNIO_IFACE", "tab-lan")
PANEL = os.environ.get("PNIO_PANEL", "http://172.30.99.6:8090/api/estado")

ET_PN, ET_LLDP = 0x8892, 0x88CC
MC_DCP = bytes.fromhex("010ecf000000")
MC_LLDP = bytes.fromhex("0180c200000e")

PLC = {"nombre": "plc-s7-1200", "mac": bytes.fromhex("020ecf000040"), "ip": "192.168.1.40",
       "tipo": "S7-1200 (simulado)", "rol": 0x02, "vendor": 0x002A, "devid": 0x0301, "frame_ds": 0x8100}
DISP = [
    {"nombre": "controllino-t1", "mac": bytes.fromhex("020ecf000011"), "ip": "192.168.1.11", "equipo": "t1.controllino",
     "tipo": "Controllino MEGA", "rol": 0x01, "vendor": 0x1234, "devid": 0x0001, "frame": 0x8001, "frame_ds": 0x8101},
    {"nombre": "controllino-t2", "mac": bytes.fromhex("020ecf000012"), "ip": "192.168.1.12", "equipo": "t2.controllino",
     "tipo": "Controllino MEGA", "rol": 0x01, "vendor": 0x1234, "devid": 0x0001, "frame": 0x8002, "frame_ds": 0x8102},
]


def eth(dst: bytes, src: bytes, ethertype: int, carga: bytes) -> bytes:
    f = dst + src + struct.pack(">H", ethertype) + carga
    return f + b"\x00" * max(0, 60 - len(f))


def tlv(tipo: int, datos: bytes) -> bytes:
    return struct.pack(">H", (tipo << 9) | len(datos)) + datos


def lldp(d: dict) -> bytes:
    carga = tlv(1, b"\x07" + d["nombre"].encode())                     # chassis: nombre de estacion
    carga += tlv(2, b"\x07" + b"port-001")                              # puerto
    carga += tlv(3, struct.pack(">H", 20))                              # TTL
    carga += tlv(4, b"Port 1")                                          # descripcion del puerto
    carga += tlv(5, d["nombre"].encode())                               # nombre del sistema
    carga += tlv(127, bytes.fromhex("000ecf") + b"\x02" + struct.pack(">HH", 0, 0))   # PN: estado RT del puerto
    carga += tlv(0, b"")
    return eth(MC_LLDP, d["mac"], ET_LLDP, carga)


def bloque(opcion: int, sub: int, datos: bytes) -> bytes:
    b = struct.pack(">BBH", opcion, sub, len(datos)) + datos
    return b + (b"\x00" if len(b) % 2 else b"")


def dcp_peticion(xid: int) -> bytes:
    bl = bloque(0xFF, 0xFF, b"")                                         # selector: todos
    cab = struct.pack(">HBBIHH", 0xFEFE, 5, 0, xid, 1, len(bl))          # Identify, request, ResponseDelay=1
    return eth(MC_DCP, PLC["mac"], ET_PN, cab + bl)


def dcp_respuesta(d: dict, xid: int, destino: bytes) -> bytes:
    info = b"\x00\x00"
    ip = bytes(int(x) for x in d["ip"].split("."))
    bl = bloque(2, 1, info + d["tipo"].encode())                         # tipo de estacion
    bl += bloque(2, 2, info + d["nombre"].encode())                      # NameOfStation
    bl += bloque(2, 3, info + struct.pack(">HH", d["vendor"], d["devid"]))   # Device ID
    bl += bloque(2, 4, info + struct.pack(">BB", d["rol"], 0))           # rol: 1 = dispositivo, 2 = controlador
    bl += bloque(1, 2, struct.pack(">H", 1) + ip + bytes([255, 255, 255, 0]) + bytes([192, 168, 1, 1]))
    cab = struct.pack(">HBBIHH", 0xFEFF, 5, 1, xid, 0, len(bl))          # Identify, response OK
    return eth(destino, d["mac"], ET_PN, cab + bl)


def rt(frame_id: int, src: bytes, dst: bytes, datos: bytes, ciclo: int) -> bytes:
    """RT clase 1: FrameID, datos de IO (rellenos a 40 B) y APDU status."""
    datos = datos.ljust(40, b"\x00")[:40]
    apdu = struct.pack(">HBB", ciclo & 0xFFFF, 0x35, 0x00)               # CycleCounter, DataStatus, TransferStatus
    return eth(dst, src, ET_PN, struct.pack(">H", frame_id) + datos + apdu)


def permitir_lldp():
    ruta = "/sys/class/net/%s/bridge/group_fwd_mask" % IFACE
    try:
        with open(ruta, "w") as f:
            f.write("16384")
    except OSError as e:
        print("aviso: no se pudo abrir LLDP en el puente (%s): LLDP solo en los puertos" % e, flush=True)


def estado():
    try:
        with urllib.request.urlopen(PANEL, timeout=2) as r:
            return (json.load(r).get("pasarela") or {}).get("equipos") or {}
    except (OSError, ValueError):
        return {}


def bits(valores) -> bytes:
    """Lista de 0/1 -> bytes (bit 0 = primer elemento)."""
    out = bytearray((len(valores) + 7) // 8)
    for i, v in enumerate(valores):
        if v:
            out[i // 8] |= 1 << (i % 8)
    return bytes(out)


def main():
    permitir_lldp()
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
    s.bind((IFACE, 0))
    print("PROFINET simulado en %s: PLC + %d dispositivos" % (IFACE, len(DISP)), flush=True)
    eq = {}
    t_est = t_dcp = t_lldp = 0.0
    xid = 0x1000
    ciclo = 0
    sig = time.time()
    while True:
        ahora = time.time()
        if ahora - t_est > 0.5:
            eq, t_est = estado(), ahora
        activos = [d for d in DISP if (eq.get(d["equipo"]) or {}).get("lan")]
        try:
            if ahora - t_lldp > 5.0:
                t_lldp = ahora
                s.send(lldp(PLC))
                for d in activos:
                    s.send(lldp(d))
            if ahora - t_dcp > 10.0:
                t_dcp = ahora
                xid += 1
                s.send(dcp_peticion(xid))
                for d in activos:
                    time.sleep(0.02)
                    s.send(dcp_respuesta(d, xid, PLC["mac"]))
            ciclo += 3200                                                # 100 ms en unidades de 31,25 us
            for d in activos:
                e = eq.get(d["equipo"]) or {}
                entradas = bits(e.get("di") or [])
                s.send(rt(d["frame"], d["mac"], PLC["mac"], entradas + b"\x80", ciclo))      # IOPS bueno
                s.send(rt(d["frame_ds"], PLC["mac"], d["mac"], struct.pack(">H", ciclo & 0xFFFF) + b"\x80", ciclo))
        except OSError as err:
            print("error al enviar:", err, flush=True)
            time.sleep(2)
        sig += 0.1
        time.sleep(max(0.0, sig - time.time()))
        if sig < time.time() - 1:
            sig = time.time()


if __name__ == "__main__":
    main()
