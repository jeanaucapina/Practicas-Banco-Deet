# Practica L4 - Listado L4.5: sondeo ciclico FC3 de ocho registros cada 250 ms.
import os
import time
from pymodbus.client import ModbusTcpClient

PERIODO = 0.250                       # s : tiempo de ciclo nominal de la practica
N_CICLOS = 480                        # 480 x 0,250 s = 120 s de captura
# IP del plc_sim: la de la guia; con ot-lab arriba se usa otra subred (PLC_IP=172.27.0.10)
cliente = ModbusTcpClient(os.environ.get("PLC_IP", "172.28.0.10"), port=502, timeout=1.0)
cliente.connect()                     # abre la conexion TCP: fase de establecimiento

for i in range(N_CICLOS):
    t0 = time.perf_counter()
    r = cliente.read_holding_registers(address=0, count=8, slave=1)
    print(f"{i:04d} {'EXCEPCION' if r.isError() else r.registers}", flush=True)
    time.sleep(max(0.0, PERIODO - (time.perf_counter() - t0)))

cliente.close()                       # cierre ordenado: FIN, FIN-ACK
