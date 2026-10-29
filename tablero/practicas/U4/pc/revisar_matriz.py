#!/usr/bin/env python3
"""Taller U4 · revisa la parte de la matriz de decision de respuestas.txt: que el caso
exista, que las puntuaciones S_j esten en [1, 5] (Ec. U5.1 con pesos que suman 1), que el
ganador puntue mas que el segundo y que el ganador sea un protocolo de las alternativas
del caso. No juzga los pesos ni las puntuaciones p_ij: eso se defiende ante el grupo.

    python3 revisar_matriz.py [respuestas.txt]
"""
import os
import re
import sys

ALTERNATIVAS = {
    1: ["iec 61850 goose", "goose", "iec 61850", "dnp3"],
    2: ["profinet", "modbus tcp", "devicenet"],
    3: ["bacnet", "knx", "modbus"],
    4: ["opc ua", "opc ua + mqtt", "pasarela opc ua", "modbus"],
}


def leer(ruta):
    d = {}
    for linea in open(ruta, encoding="utf-8"):
        m = re.match(r"^\s*([A-Za-z_0-9]+)\s*=\s*(.*?)\s*$", linea)
        if m and not linea.lstrip().startswith("#"):
            d[m.group(1)] = m.group(2)
    return d


def numero(t):
    try:
        return float(t.replace(",", "."))
    except (AttributeError, ValueError):
        return None


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                               "respuestas.txt")
    d = leer(ruta)
    errores = []
    caso = numero(d.get("caso", ""))
    if caso not in (1, 2, 3, 4):
        errores.append("caso: pon 1, 2, 3 o 4")
    s1, s2 = numero(d.get("S_ganador", "")), numero(d.get("S_segundo", ""))
    for nombre, s in (("S_ganador", s1), ("S_segundo", s2)):
        if s is None or not 1.0 <= s <= 5.0:
            errores.append("%s: con p_ij en 1..5 y pesos que suman 1, S_j queda entre 1 y 5" % nombre)
    if s1 is not None and s2 is not None and s1 < s2:
        errores.append("S_ganador (%.2f) es menor que S_segundo (%.2f)" % (s1, s2))
    g, sg = d.get("ganador", "").lower(), d.get("segundo", "").lower()
    if caso in ALTERNATIVAS:
        alt = ALTERNATIVAS[int(caso)]
        if not any(a in g for a in alt):
            errores.append("ganador «%s» no es una alternativa del caso %d (%s)" % (g, caso, ", ".join(alt)))
        if not any(a in sg for a in alt) or (g and sg and g == sg):
            errores.append("segundo «%s»: otra alternativa del caso, distinta del ganador" % sg)
    if not d.get("ganador_sensibilidad", ""):
        errores.append("ganador_sensibilidad: el ganador al bajar el determinismo a 0,10")
    if errores:
        print("REVISAR\n- " + "\n- ".join(errores))
    else:
        margen = s1 - s2
        print("OK  caso %d: %s %.2f frente a %s %.2f (margen %.2f%s)" % (
            caso, g, s1, sg, s2, margen, ", estrecho: decision discutible" if margen < 0.3 else ""))


if __name__ == "__main__":
    main()
