"""Captura cruda de una interfaz a formato pcap por stdout (o a fichero).

Sin tcpdump ni Wireshark instalados: un socket AF_PACKET y la cabecera pcap
escrita a mano. Lo lanza capturar.sh dentro de un contenedor con red del
anfitrion, asi no hace falta pertenecer al grupo wireshark.
"""
import socket, struct, sys, time

iface = sys.argv[1]
out = open(sys.argv[2], "wb") if len(sys.argv) > 2 and sys.argv[2] != "-" else sys.stdout.buffer
s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0003))
s.bind((iface, 0))
# Modo promiscuo: sin el, el puente solo sube al anfitrion lo que va para el, y
# no se verian las tramas entre dos equipos (p. ej. ESP32 -> broker MQTT).
ifindex = socket.if_nametoindex(iface)
s.setsockopt(263, 1, struct.pack("iHH8s", ifindex, 1, 0, b""))  # SOL_PACKET, ADD_MEMBERSHIP, PROMISC
out.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))  # DLT_EN10MB
out.flush()
try:
    while True:
        pkt, meta = s.recvfrom(65535)
        t = time.time()
        out.write(struct.pack("<IIII", int(t), int((t % 1) * 1e6), len(pkt), len(pkt)) + pkt)
        out.flush()
except (KeyboardInterrupt, BrokenPipeError):
    pass
