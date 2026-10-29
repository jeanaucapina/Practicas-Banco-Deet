#!/usr/bin/env python3
"""Taller U6 - comprueba tu filtro de frescura (frescura.py) contra los tres casos de la
Parte II, sin tocar la red: (1) un mando nuevo se acepta; (2) el mismo reinyectado (replay,
mismo seq) se descarta; (3) un seq nuevo pero con marca de tiempo vieja se descarta por la
ventana. Si editaste frescura.py y rompiste la Ec. (U6.1), aqui se ve.

    python3 revisar_frescura.py
"""
import sys

import frescura


def main():
    ahora = 1_793_000_000_000           # epoch ms de referencia
    estado = {}
    errores = []

    ok, _ = frescura.aceptar(estado, {"reg": 4, "val": 1, "seq": 1, "ts": ahora}, ahora)
    if not ok:
        errores.append("un mando fresco (seq 1, ts actual) deberia aceptarse")

    ok, _ = frescura.aceptar(estado, {"reg": 4, "val": 1, "seq": 1, "ts": ahora + 100}, ahora + 100)
    if ok:
        errores.append("el replay (mismo seq 1) deberia descartarse")

    ok, _ = frescura.aceptar(estado, {"reg": 4, "val": 1, "seq": 2, "ts": ahora - 60_000}, ahora)
    if ok:
        errores.append("un seq nuevo con marca de tiempo vieja deberia descartarse por la ventana")

    ok, _ = frescura.aceptar(estado, {"reg": 4, "val": 0, "seq": 2, "ts": ahora + 10}, ahora + 10)
    if not ok:
        errores.append("un mando legitimo posterior (seq 2, ts actual) deberia aceptarse")

    if errores:
        print("REVISAR\n- " + "\n- ".join(errores))
        sys.exit(1)
    print("OK  la frescura acepta lo legitimo y descarta el replay y lo caducado (SR 3.1 / SR 3.8)")


if __name__ == "__main__":
    main()
