#!/usr/bin/env python3
"""Prueba del tablero en el navegador (export web de Godot).

Abre la pagina, espera a que el juego diga que esta listo y falla si la consola
trae errores de script. Con --pasarela exige ademas que haya conectado al
puente WebSocket y que lleguen estados.

    python prueba_web.py http://localhost:8091/ [--pasarela] [--captura out.png]

Necesita `pip install playwright` y `playwright install chromium`.
"""
import argparse
import sys
import time

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("url", nargs="?", default="http://localhost:8091/")
ap.add_argument("--pasarela", action="store_true", help="exige conexion y estados")
ap.add_argument("--captura", default="")
ap.add_argument("--gpu", action="store_true", help="GPU real (ventana visible) en vez de SwiftShader")
ap.add_argument("--clic", default="", help="x,y: clic en el lienzo y exige postMessage de equipo")
ap.add_argument("--espera", type=float, default=60.0)
a = ap.parse_args()

log = []
errores = []
puentes = []

with sync_playwright() as p:
    if a.gpu:
        nav = p.chromium.launch(headless=False, args=["--ignore-gpu-blocklist"])
    else:
        nav = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                      "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    pag = nav.new_page(viewport={"width": 1280, "height": 720})

    def on_console(m):
        t = m.text
        log.append(t)
        if "SCRIPT ERROR" in t or "Parse Error" in t or "ERROR:" in t:
            errores.append(t)

    pag.on("console", on_console)
    pag.on("pageerror", lambda e: errores.append("pageerror: %s" % e))
    # El portal recibe aqui los clics en equipos.
    pag.expose_function("puenteTablero", lambda msg: puentes.append(msg))
    pag.add_init_script("window.addEventListener('message', e => window.puenteTablero(JSON.stringify(e.data)));")
    t0 = time.time()
    pag.goto(a.url)
    listo = False
    while time.time() - t0 < a.espera:
        if any("TABLERO_WEB_LISTO" in t for t in log):
            listo = True
            break
        if errores:
            break
        pag.wait_for_timeout(250)
    t_listo = time.time() - t0
    conectado = False
    if listo and a.pasarela:
        while time.time() - t0 < a.espera:
            if any("TABLERO_WEB_CONECTADO" in t for t in log):
                conectado = True
                break
            pag.wait_for_timeout(250)
    pag.wait_for_timeout(1500)
    fps = 0.0
    if listo:
        fps = pag.evaluate("""() => new Promise(res => { let n = 0; const t0 = performance.now();
            const f = () => { n++; if (performance.now() - t0 < 3000) requestAnimationFrame(f); else res(n / 3); };
            requestAnimationFrame(f); })""")
    if a.clic and listo:
        x, y = (int(v) for v in a.clic.split(","))
        pag.mouse.move(x, y)
        pag.wait_for_timeout(500)
        pag.mouse.down()
        pag.mouse.up()
        pag.wait_for_timeout(1000)
    if a.captura:
        pag.screenshot(path=a.captura)
    nav.close()

print("listo=%s en %.1f s, %.0f FPS" % (listo, t_listo, fps))
if a.pasarela:
    print("conectado=%s" % conectado)
for t in log[-15:]:
    print("  >", t)
for e in errores:
    print("ERROR:", e)
if a.clic:
    print("mensajes al portal:", puentes)
reconex = sum(1 for t in log if "TABLERO_WEB_CONECTADO" in t)
if a.pasarela:
    print("conexiones=%d (debe ser 1: mas es reconexion)" % reconex)
ok = listo and not errores and (conectado or not a.pasarela) and reconex <= 1 and (not a.clic or any('equipo' in m for m in puentes))
print("OK" if ok else "FALLO")
sys.exit(0 if ok else 1)
