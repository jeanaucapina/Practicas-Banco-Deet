"""Cliente S7 de ejemplo contra el S7-1200 simulado del tablero.

    pip install python-snap7
    python cliente_s7.py              # desde el PC: 127.0.0.1 (puerto 102 publicado)
    python cliente_s7.py 192.168.1.40   # desde la LAN del tablero

Arranca la cinta, mira como suben piezas y temperatura, y la para. El mapa de
memoria (DB1 "Proceso", entradas y salidas) esta en tablero/dispositivos/s7.py.
Contra un S7-1200 real hace falta en TIA Portal: "Permitir acceso PUT/GET" en
la CPU y el DB con "acceso optimizado" desactivado.
"""
import sys
import time

import snap7
from snap7.type import Area, WordLen
from snap7.util import get_bool, get_dint, get_int, get_real

PLC = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"


def escribir_bit(c, db, byte, bit, valor):
    """Un solo bit (DBXbyte.bit) sin pisar los otros 7 del mismo byte."""
    c.write_area(Area.DB, db, byte * 8 + bit, bytearray([1 if valor else 0]), WordLen.Bit)


def leer(c):
    d = c.db_read(1, 0, 16)
    return {"motor": get_bool(d, 0, 2), "alarma": get_bool(d, 0, 3), "piezas": get_int(d, 2),
            "temperatura": get_int(d, 4) / 10, "consigna": round(get_real(d, 6), 1),
            "t_marcha": get_dint(d, 10)}


c = snap7.client.Client()
c.connect(PLC, 0, 1)                  # rack 0, slot 1 (S7-1200)
print("conectado:", c.get_connected(), "  estado:", leer(c))
escribir_bit(c, 1, 0, 0, True)        # DBX0.0 MarchaRemota (pulso)
for _ in range(5):
    time.sleep(1)
    print(leer(c), "  salidas QB0 =", bin(c.ab_read(0, 1)[0]))
escribir_bit(c, 1, 0, 1, True)        # DBX0.1 ParoRemoto (pulso)
time.sleep(0.3)
print("tras paro:", leer(c))
c.disconnect()
