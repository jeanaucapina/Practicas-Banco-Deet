# Practica L7 - Parte III (Listado L7.6 de la guia): lectura FC3, escrituras FC6 y FC16
# y medida del tiempo de ida y vuelta. En el PC del banco:  python3 cliente_l7.py
import socket, statistics, time
from pymodbus.client import ModbusTcpClient

SERVIDOR, PUERTO, UNIT = "192.168.1.10", 502, 1
N_MUESTRAS, PERIODO = 100, 0.050                 # 100 transacciones cada 50 ms

cliente = ModbusTcpClient(SERVIDOR, port=PUERTO, timeout=1.0)   # timeout 1000 ms
cliente.connect()                                # saludo de tres pasos SYN/SYN-ACK/ACK
# Exigido por la guia de implementacion de Modbus.org: desactivar Nagle
cliente.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
latencias = []
for i in range(N_MUESTRAS):
    t0 = time.perf_counter()
    r = cliente.read_holding_registers(address=0, count=8, slave=UNIT)   # FC3
    dt = (time.perf_counter() - t0) * 1000.0                             # ms
    if r.isError():
        print(f"{i:03d} EXCEPCION {r}")
    else:
        latencias.append(dt)
        print(f"{i:03d} {dt:6.2f} ms regs={r.registers}")
    time.sleep(max(0.0, PERIODO - (time.perf_counter() - t0)))

cliente.write_register(4, 1, slave=UNIT)                 # FC6: REL-A cierra
time.sleep(1.0)
cliente.write_registers(4, [0, 1, 0, 1], slave=UNIT)     # FC16: los cuatro
print(f"media {statistics.mean(latencias):.2f} ms "
      f"desv {statistics.stdev(latencias):.2f} ms "
      f"min {min(latencias):.2f} max {max(latencias):.2f}")
cliente.close()                                          # cierre ordenado FIN/ACK
