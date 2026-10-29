#!/usr/bin/env python3
"""Taller U2, Ejercicio 2 (a) medido: cronometra transacciones Modbus RTU FC3 reales
(01 03 00 00 00 08 + CRC: ocho registros del esclavo 1) por el USB-RS485 del PC y las
compara con la Ec. (U2.1). Solo biblioteca estandar (termios).

    python3 medir_fc3.py [--puerto /dev/ttyUSB0] [--baudios 19200] [--n 20] [--esclavo 1]

Antes: el USB-RS485 del PC en el bus del Controllino (A con A, B con B) y nadie mas
haciendo de maestro (si el ESP32 tambien pregunta, chocais: es el Ejercicio 3 vivido).
"""
import argparse
import os
import select
import statistics
import termios
import time

BAUDIOS = {9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400,
           57600: termios.B57600, 115200: termios.B115200}


def crc16(datos: bytes) -> bytes:
    crc = 0xFFFF
    for b in datos:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return bytes([crc & 0xFF, crc >> 8])


def abrir(puerto: str, baudios: int) -> int:
    fd = os.open(puerto, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = 0                                    # iflag
    a[1] = 0                                    # oflag
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL      # 8N1
    a[3] = 0                                    # lflag (crudo)
    a[4] = a[5] = BAUDIOS[baudios]
    termios.tcsetattr(fd, termios.TCSANOW, a)
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


def transaccion(fd: int, consulta: bytes, esperados: int, limite: float = 1.0):
    os.write(fd, consulta)
    t0 = time.perf_counter()
    rx = b""
    while len(rx) < esperados and time.perf_counter() - t0 < limite:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            rx += os.read(fd, 256)
    return time.perf_counter() - t0, rx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", default="/dev/ttyUSB0")
    ap.add_argument("--baudios", type=int, default=19200)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--esclavo", type=int, default=1)
    a = ap.parse_args()
    pdu = bytes([a.esclavo, 0x03, 0, 0, 0, 8])
    consulta = pdu + crc16(pdu)
    t_car = 10.0 / a.baudios                    # 8N1: inicio + 8 datos + parada
    t35 = 0.00175 if a.baudios > 19200 else 3.5 * t_car
    teoria = (8 + 21) * t_car + 2 * t35
    fd = abrir(a.puerto, a.baudios)
    tiempos, malas, mudas, ejemplo = [], 0, 0, b""
    for _ in range(a.n):
        dt, rx = transaccion(fd, consulta, 21)
        if len(rx) == 21 and crc16(rx[:-2]) == rx[-2:]:
            tiempos.append(dt)
        elif rx:
            malas += 1                          # llegaron bytes, pero no una respuesta valida
            ejemplo = ejemplo or rx
        else:
            mudas += 1
        time.sleep(t35 * 2)
    os.close(fd)
    print("consulta  %s" % consulta.hex(" "))
    print("teoria    Tcon + Tresp + 2 t3,5 = %.2f ms   (sin Tproc; t_car = %.1f us)" % (teoria * 1e3, t_car * 1e6))
    if tiempos:
        ms = [t * 1e3 for t in tiempos]
        print("medido    min %.2f  media %.2f  max %.2f ms   (%d buenas, %d con CRC mal, %d sin respuesta)"
              % (min(ms), statistics.mean(ms), max(ms), len(ms), malas, mudas))
        print("Tproc     ~ %.2f ms (media medida - teoria)" % (statistics.mean(ms) - teoria * 1e3))
    if malas:
        print("CRC mal   %d de %d: llegan bytes que no son una respuesta (p. ej. %s). Dos esclavos con la"
              " misma direccion, baudios distintos o A/B cruzados." % (malas, a.n, ejemplo.hex(" ")))
    if not tiempos and not malas:
        print("silencio  ninguna respuesta en %d intentos: revisa el cableado y que el esclavo %d este en el bus"
              % (mudas, a.esclavo))


if __name__ == "__main__":
    main()
