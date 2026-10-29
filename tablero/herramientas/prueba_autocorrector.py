#!/usr/bin/env python3
"""Barrido del autocorrector de todas las practicas del portal: para cada una, monta el
tablero (/api/practica_montar), sube el ejemplo de solucion si lo tiene, y lanza la
comprobacion (/api/verificar). Imprime cuantos pasos pasan de cada practica.

Las que necesitan un `docker compose` del alumno (L5, L10, U6) o una hoja de respuestas
del alumno (U2, U4) no pueden auto-resolverse aqui; se marcan [manual] y solo se comprueba
que montan sin error. El resto deberia dar todos los pasos en verde.

    python prueba_autocorrector.py [panel_url] [L0 L1 ...]

Necesita el banco arrancado. Deja el tablero en fabrica y sin cables.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

PANEL = "http://localhost:8090"
args = list(sys.argv[1:])
if args and args[0].startswith("http"):
    PANEL = args.pop(0)
# Subir los ejemplos que resuelven las practicas exige el modo docente:
# --clave <clave> o la variable TAB_CLAVE_DOCENTE.
CLAVE = os.environ.get("TAB_CLAVE_DOCENTE", "")
if "--clave" in args:
    i = args.index("--clave")
    CLAVE = args[i + 1]
    del args[i:i + 2]
COOKIE = ""
SOLO = [x.upper() for x in args]
AQUI = os.path.dirname(os.path.abspath(__file__))
PRAC = os.path.join(AQUI, "..", "practicas")

# practicas que el autocorrector puede resolver solo subiendo su ejemplo (sin Docker ni hoja)
AUTORRESUELVE = {"L0", "L1", "L2", "L3", "L6", "L7"}   # L9 (flujo Node-RED) es interactiva


def http(ruta, cuerpo=None):
    rq = urllib.request.Request(PANEL + ruta, data=cuerpo,
                                method="POST" if cuerpo is not None else "GET")
    if COOKIE:
        rq.add_header("Cookie", COOKIE)
    with urllib.request.urlopen(rq, timeout=120) as r:
        return json.load(r)


def entrar_docente():
    global COOKIE
    if not CLAVE:
        print("Sin clave de docente (--clave o TAB_CLAVE_DOCENTE): no se suben las soluciones.")
        return
    rq = urllib.request.Request(PANEL + "/api/docente_entrar", data=json.dumps({"clave": CLAVE}).encode(),
                                method="POST")
    try:
        with urllib.request.urlopen(rq, timeout=20) as r:
            COOKIE = (r.headers.get("Set-Cookie") or "").split(";")[0]
    except urllib.error.HTTPError:
        sys.exit("Clave de docente incorrecta.")


def catalogo():
    return json.load(open(os.path.join(PRAC, "catalogo.json"), encoding="utf-8"))


def practica(pid):
    return json.load(open(os.path.join(PRAC, pid, "practica.json"), encoding="utf-8"))


def verificar(pid):
    http("/api/verificar?id=%s" % pid, b"")
    for _ in range(90):
        time.sleep(3)
        v = http("/api/verificar_estado")
        if not v.get("corriendo") and v.get("informe"):
            return v["informe"]
    return None


def main():
    entrar_docente()
    filas = []
    for e in catalogo():
        pid = e["id"]
        if SOLO and pid not in SOLO:
            continue
        p = practica(pid)
        m = http("/api/practica_montar?id=%s" % pid, b"")
        if not m.get("ok"):
            filas.append((pid, "NO MONTA: " + m.get("salida", ""), False))
            continue
        if p.get("solucion_cables"):          # practicas en las que el alumno cablea (L13-L15): boton del docente
            http("/api/cablear_solucion?id=%s" % pid, b"")
            time.sleep(4)
        equipos = p.get("solucion_equipos") or ([[p.get("equipo", ""), p["solucion_ejemplo"]]]
                                                 if p.get("solucion_ejemplo") else [])
        if equipos and pid in AUTORRESUELVE:
            for eq, ej in equipos:
                http("/api/subir_ejemplo?equipo=%s&ejemplo=%s" % (eq, ej), b"")
            time.sleep(12)
        inf = verificar(pid)
        if inf is None:
            filas.append((pid, "la comprobacion no termino", False))
            continue
        ok, tot = inf["aprobados"], inf["total"]
        manual = pid not in AUTORRESUELVE
        etq = " [manual: necesita Docker/hoja del alumno]" if manual and ok < tot else ""
        filas.append((pid, "%d/%d%s" % (ok, tot, etq), ok == tot or manual))

    # Color ANSI (verde OK, amarillo manual, rojo NO); se apaga si la salida no es un TTY.
    usar_color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    V, A, R, G, Z = ("\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m") if usar_color else ("",) * 5
    print("\n%s=== Autocorrector ===%s" % (G, Z))
    for pid, txt, ok in filas:
        manual = "[manual" in txt
        col = (A if manual else V) if ok else R
        marca = "✓" if ok and not manual else ("~" if manual else "✗")
        print(" %s%s %-4s %s%s" % (col, marca, pid, txt, Z))
    malos = [f for f in filas if not f[2]]
    verde = len(filas) - len(malos)
    col = V if not malos else R
    print("\n%s%s%d/%d prácticas verifican%s" % (G, col, verde, len(filas), Z))
    sys.exit(1 if malos else 0)


if __name__ == "__main__":
    main()
