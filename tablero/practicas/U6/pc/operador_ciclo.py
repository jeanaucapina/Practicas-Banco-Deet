#!/usr/bin/env python3
"""Taller U6 - Parte III (Listado U6.7): el OPERADOR legitimo mide el tiempo de ciclo del PLC
y las transacciones perdidas. Ejecutalo EN PARALELO con la saturacion (saturar.sh) para
llenar la Tabla U6.8. Es medida, no ataque.

    python3 operador_ciclo.py [--n 300] [--plc 192.168.1.10]
"""
import argparse
import statistics
import time

from pymodbus.client import ModbusTcpClient


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plc", default="192.168.1.10")
    ap.add_argument("--n", type=int, default=300)       # ~30 s a 100 ms
    a = ap.parse_args()
    cli = ModbusTcpClient(a.plc, port=502, timeout=1.0)
    cli.connect()
    lat, perdidas = [], 0
    for _ in range(a.n):
        t0 = time.perf_counter()
        try:
            r = cli.read_holding_registers(address=0, count=8, slave=1)    # FC3
            err = r.isError()
        except Exception:
            err = True
        dt = (time.perf_counter() - t0) * 1000.0
        if err:
            perdidas += 1                               # timeout: el PLC no respondio a tiempo
        else:
            lat.append(dt)
        time.sleep(max(0.0, 0.100 - (time.perf_counter() - t0)))
    cli.close()
    if lat:
        print("Tc mediano = %.1f ms   p95 = %.1f ms   perdidas = %d/%d"
              % (statistics.median(lat), sorted(lat)[int(0.95 * len(lat)) - 1], perdidas, a.n))
    else:
        print("ninguna respuesta: el PLC no cumple su plazo bajo esta carga (perdidas %d/%d)"
              % (perdidas, a.n))


if __name__ == "__main__":
    main()
