"""Capa fisica del bus RS-485 del banco: lo que ve la UART de cada receptor.

Las tramas viajan por UDP tal como irian por el par (los bytes, sin cabecera: asi
Wireshark las sigue decodificando como Modbus RTU). Cada nodo tiene su linea
-baudios, formato «8N1»/«8E1»/«7O2»... y si su A/B esta cruzado- y la pasarela
reparte la de todos. Con eso el receptor reconstruye la forma de onda en el par
y la muestrea con SU UART, como el hardware:

  - mismos baudios y formato           -> los mismos bytes
  - baudios o formato distintos        -> lo que de verdad lee una UART: basura,
                                          errores de trama, bytes de mas o de menos
  - A/B cruzados (en un extremo)       -> la onda invertida: nunca sincroniza
  - dos emisores a la vez (colision)   -> las dos ondas superpuestas en el par
  - ruido (terminacion mal, sin
    polarizacion)                      -> bits cambiados con la probabilidad dada

Sin dependencias: lo usan los equipos (base.py), la pasarela y el convertidor
USB-RS485 del PC.
"""
import random

FORMATO_DEFECTO = "8N1"


def formato(fmt: str):
    """«8N1» -> (bits de datos, paridad 'N'/'E'/'O', bits de parada)."""
    try:
        return int(fmt[0]), fmt[1].upper(), int(fmt[2])
    except (IndexError, ValueError):
        return 8, "N", 1


def bits_por_caracter(fmt: str) -> int:
    d, p, s = formato(fmt)
    return 1 + d + (0 if p == "N" else 1) + s


def duracion(n_bytes: int, baudios: int, fmt: str = FORMATO_DEFECTO) -> float:
    """Segundos que tarda la trama en el par."""
    return n_bytes * bits_por_caracter(fmt) / float(max(1, baudios))


def t35(baudios: int, fmt: str = FORMATO_DEFECTO) -> float:
    """Silencio de fin de trama de Modbus RTU (fijo en 1,75 ms por encima de 19200)."""
    if baudios > 19200:
        return 0.00175
    return 3.5 * bits_por_caracter(fmt) / float(max(1, baudios))


def _bits(byte: int, fmt: str):
    d, p, s = formato(fmt)
    datos = [(byte >> i) & 1 for i in range(d)]
    out = [0] + datos
    if p != "N":
        unos = sum(datos)
        out.append(unos % 2 if p == "E" else 1 - unos % 2)
    return out + [1] * s


class Segmento:
    """Una trama en el par: desde t0, a sus baudios y formato, quiza invertida."""

    def __init__(self, t0: float, datos: bytes, baudios: int, fmt: str = FORMATO_DEFECTO, invertido=False):
        self.t0, self.datos, self.baudios, self.fmt = t0, bytes(datos), int(baudios), fmt
        self.invertido = bool(invertido)
        self.tb = 1.0 / max(1, self.baudios)
        self.bits = [b for x in self.datos for b in _bits(x, fmt)]
        self.t1 = self.t0 + len(self.bits) * self.tb

    def nivel(self, t: float) -> int:
        """Nivel logico que pone en el par en el instante t (1 = reposo)."""
        if t < self.t0 or t >= self.t1:
            v = 1
        else:
            v = self.bits[int((t - self.t0) / self.tb)]
        return 1 - v if self.invertido else v

    def bordes(self):
        return [self.t0 + i * self.tb for i in range(len(self.bits) + 1)]


def leer(segmentos, baudios: int, fmt: str = FORMATO_DEFECTO, invertido=False) -> bytes:
    """Lo que entrega la UART de un receptor (sus baudios, formato y polaridad)
    ante esas tramas en el par. Varias a la vez = colision: el par queda en el
    nivel dominante (un 0 de cualquiera gana)."""
    segmentos = [s for s in segmentos if s.datos]
    if not segmentos:
        return b""
    if (len(segmentos) == 1 and segmentos[0].baudios == baudios and segmentos[0].fmt == fmt
            and segmentos[0].invertido == bool(invertido)):
        return segmentos[0].datos                       # el caso normal, sin calcular la onda
    inv = 1 if invertido else 0

    def nivel(t):
        v = 1
        for s in segmentos:
            v &= s.nivel(t)
        return v ^ inv

    t_ini = min(s.t0 for s in segmentos)
    t_fin = max(s.t1 for s in segmentos)
    tr = 1.0 / max(1, baudios)
    d, p, st = formato(fmt)
    n_muestras = d + (0 if p == "N" else 1)
    eps = min(s.tb for s in segmentos) * 1e-3
    bordes = sorted({b for s in segmentos for b in s.bordes()})
    # La UART del receptor arranca en reposo: un flanco de bajada es un bit de start.
    caidas = [b for b in bordes if nivel(b - eps) == 1 and nivel(b + eps) == 0]
    if nivel(t_ini + eps) == 0 and (not caidas or caidas[0] > t_ini + eps):
        caidas.insert(0, t_ini)                         # la onda empieza ya en 0 (invertida)
    out = bytearray()
    libre = t_ini - 1.0
    for te in caidas:
        if te < libre:
            continue
        if nivel(te + tr * 0.5) != 0:                   # start falso (glitch): se ignora
            continue
        bits = [nivel(te + tr * (k + 1.5)) for k in range(n_muestras)]
        v = 0
        for k in range(d):
            v |= bits[k] << k
        out.append(v)                                   # Arduino entrega el byte aunque haya error de trama
        libre = te + tr * (1 + n_muestras + 0.5)        # tras la mitad del bit de stop
        if libre > t_fin + 20 * tr:
            break
    return bytes(out)


def ruido(datos: bytes, p: float, rnd=random) -> bytes:
    """Con probabilidad p por trama cambia un bit (reflexiones sin terminacion,
    linea sin polarizar...). El CRC lo detecta; un protocolo sin CRC no."""
    if not datos or p <= 0 or rnd.random() >= p:
        return datos
    b = bytearray(datos)
    i = rnd.randrange(len(b))
    b[i] ^= 1 << rnd.randrange(8)
    return bytes(b)
