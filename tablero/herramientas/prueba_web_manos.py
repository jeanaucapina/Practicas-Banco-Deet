#!/usr/bin/env python3
"""Lo que hace un estudiante remoto con el RATON en el tablero 3D del navegador:
enchufar un cable Ethernet y pulsar un pulsador, comprobando el efecto REAL en la
pasarela (/api/estado del panel). Si esto falla, el remoto no siente lo mismo que
quien esta con el tablero.

    python prueba_web_manos.py [--gpu] [--captura out.png]
"""
import argparse
import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8091/")
ap.add_argument("--panel", default="http://127.0.0.1:8090")
ap.add_argument("--gpu", action="store_true")
ap.add_argument("--captura", default="")
a = ap.parse_args()

res = []


def paso(txt, ok, extra=""):
    res.append(ok)
    print(("  OK    " if ok else "  FALLA ") + txt + ("  " + extra if extra else ""))


def estado():
    with urllib.request.urlopen(a.panel + "/api/estado", timeout=5) as r:
        return json.load(r)["pasarela"]


def orden(d):
    rq = urllib.request.Request(a.panel + "/api/orden", data=json.dumps(d).encode(), method="POST")
    urllib.request.urlopen(rq, timeout=5).read()


log, msgs = [], []
with sync_playwright() as p:
    if a.gpu:
        nav = p.chromium.launch(headless=False, args=["--ignore-gpu-blocklist"])
    else:
        nav = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                      "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    pag = nav.new_page(viewport={"width": 1280, "height": 720})
    pag.on("console", lambda m: log.append(m.text))
    pag.expose_function("recibir", lambda m: msgs.append(json.loads(m)))
    pag.add_init_script("window.addEventListener('message', e => window.recibir(JSON.stringify(e.data)));")
    pag.goto(a.url)
    for _ in range(600):
        if any("TABLERO_WEB_CONECTADO" in t for t in log):
            break
        pag.wait_for_timeout(250)
    pag.wait_for_timeout(1500)

    def donde(ids):
        msgs.clear()
        pag.evaluate("ids => window.postMessage({t:'donde', ids}, '*')", ids)
        for _ in range(40):
            for m in msgs:
                if m.get("t") == "donde" and "pos" in m:
                    return m["pos"]
            pag.wait_for_timeout(100)
        return {}

    # Vista del tablero 1 para que los puertos queden grandes
    pag.evaluate("window.postMessage({t:'vista', equipo:'t1'}, '*')")
    pag.wait_for_timeout(800)
    pos = donde(["t1.controllino.eth", "t1.switch.p1", "t1.I16"])
    paso("el 3D sabe dónde están los puertos y el pulsador", len(pos) == 3, str(pos))

    if len(pos) == 3:
        # Cable: clic en el puerto del Controllino (coge la clavija) y clic en el del switch
        def clic(xy):
            pag.mouse.move(*xy)
            pag.wait_for_timeout(250)
            pag.mouse.down()
            pag.mouse.up()
            pag.wait_for_timeout(500)

        antes = len(estado().get("cables", {}))
        clic(pos["t1.controllino.eth"])
        clic(pos["t1.switch.p1"])
        pag.wait_for_timeout(2500)
        cab = estado().get("cables", {})
        ok = any({"t1.controllino.eth", "t1.switch.p1"} == {c["a"], c["b"]} for c in cab.values())
        paso("enchufar un cable con el ratón llega a la pasarela", ok, "cables=%d (antes %d)" % (len(cab), antes))

        # Pulsador I16: mantener pulsado 1 s y ver la entrada en el equipo real
        e0 = estado()["equipos"]["t1.controllino"]["di"][:]
        pag.mouse.move(*pos["t1.I16"])
        pag.wait_for_timeout(300)
        pag.mouse.down()
        pag.wait_for_timeout(1200)
        e1 = estado()["equipos"]["t1.controllino"]["di"][:]
        pag.mouse.up()
        pag.wait_for_timeout(1500)
        e2 = estado()["equipos"]["t1.controllino"]["di"][:]
        paso("pulsar I16 con el ratón cambia una entrada del Controllino", e1 != e0, "di %s -> %s" % (e0[-5:], e1[-5:]))
        paso("al soltar vuelve", e2 == e0)
    if a.captura:
        pag.screenshot(path=a.captura)
    nav.close()

# Deja el tablero como estaba
try:
    orden({"t": "limpiar"})
except Exception:
    pass
print("FALLOS: %d" % res.count(False))
sys.exit(0 if all(res) else 1)
