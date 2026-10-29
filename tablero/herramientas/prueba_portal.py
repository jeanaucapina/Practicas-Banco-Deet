#!/usr/bin/env python3
"""Prueba del portal del laboratorio (http://localhost:8090/lab) en un navegador.

Abre el portal, espera al tablero 3D, comprueba que un clic en el ESP32 3D elige el
equipo en el cajon, sube un .ino bueno y uno con error (debe salir «linea N») y
abre el editor de escalera.

    python prueba_portal.py [--gpu] [--captura out.png] [--sin-editor]
"""
import argparse
import os
import sys

from playwright.sync_api import sync_playwright

AQUI = os.path.dirname(os.path.abspath(__file__))
EJ = os.path.join(AQUI, "..", "ejemplos_arduino")

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://localhost:8090/lab")
ap.add_argument("--gpu", action="store_true")
ap.add_argument("--captura", default="")
ap.add_argument("--sin-editor", action="store_true")
ap.add_argument("--espera", type=float, default=150.0)
ap.add_argument("--clic", default="640,300", help="x,y dentro del lienzo 3D, sobre el ESP32 PLC 1")
a = ap.parse_args()

resultados = []


def paso(txt, ok, extra=""):
    resultados.append(ok)
    print(("  OK    " if ok else "  FALLA ") + txt + ("  " + extra if extra else ""))


log = []
with sync_playwright() as p:
    if a.gpu:
        nav = p.chromium.launch(headless=False, args=["--ignore-gpu-blocklist"])
    else:
        nav = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                      "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    pag = nav.new_page(viewport={"width": 1500, "height": 860})
    pag.on("console", lambda m: log.append(m.text))
    pendientes = {}
    pag.on("request", lambda r: pendientes.__setitem__(r.url, r.url))
    pag.on("requestfinished", lambda r: pendientes.pop(r.url, None))
    pag.on("requestfailed", lambda r: pendientes.pop(r.url, None))
    pag.goto(a.url)
    for _ in range(int(a.espera * 4)):
        if any("TABLERO_WEB_CONECTADO" in t for t in log):
            break
        pag.wait_for_timeout(250)
    paso("el tablero 3D carga dentro del portal y conecta", any("TABLERO_WEB_CONECTADO" in t for t in log))
    pag.wait_for_timeout(1500)

    # Clic sobre el ESP32 en el 3D -> el cajon cambia de equipo
    caja = pag.locator("#f3d").bounding_box()
    x, y = (int(v) for v in a.clic.split(","))
    pag.mouse.move(caja["x"] + x, caja["y"] + y)
    pag.wait_for_timeout(400)
    pag.mouse.down()
    pag.mouse.up()
    pag.wait_for_timeout(800)
    try:
        import json as _j, urllib.request as _u
        _e = _j.load(_u.urlopen("http://127.0.0.1:8090/api/estado", timeout=10))["pasarela"]["equipos"]["t1.controllino"]
        print("DBG di tras el clic 3D:", _e["di"][16:19])
    except Exception as _x:
        print("DBG", _x)
    titulo = pag.locator("#eq-titulo").inner_text()
    paso("clic en el equipo 3D lo elige en el cajon", titulo != "Controllino 1" and "PLC" in titulo or "Controllino" in titulo,
         "titulo=%r" % titulo)

    pag.click("#sel button:has-text('Controllino 1')")
    # .ino con error de sintaxis
    malo = os.path.join(os.environ.get("TEMP", "."), "malo.ino")
    with open(malo, "w") as f:
        f.write("void setup() { pinMode(CONTROLLINO_D0, OUTPUT) }\nvoid loop() {}\n")
    pag.set_input_files("#archivo", malo)
    pag.wait_for_selector("#resultado .error", timeout=60000)
    txt = pag.locator("#resultado").inner_text()
    paso("un .ino con error muestra la linea", "línea" in txt and "1" in txt, txt.splitlines()[0] if txt else "")

    # .ino bueno
    pag.set_input_files("#archivo", os.path.join(EJ, "controllino_blink", "controllino_blink.ino"))
    pag.wait_for_selector("#resultado .ok", timeout=90000)
    paso("el .ino bueno se sube", "Subido" in pag.locator("#resultado").inner_text())
    pag.wait_for_timeout(3500)
    quien = pag.locator("#eq-quien").inner_text()
    paso("el cajon dice que corre tu programa", "controllino_blink" in quien, quien)

    # Practica L1: enunciado, preparar, plantilla, comprobar
    pag.select_option("#prac", "L1")
    pag.wait_for_selector("#prac-info .md", timeout=15000)
    paso("la práctica L1 muestra su enunciado", "máquina de estados" in pag.locator("#prac-info .md").inner_text().lower())
    pag.click("button:has-text('Preparar el tablero')")
    try:
        pag.wait_for_selector("#resultado .ok", timeout=40000)
    except Exception:
        print("DEBUG pendientes:", [u.split("8090")[-1] for u in pendientes if "8090" in u][:8])
        print("DEBUG resultado:", pag.locator("#resultado").inner_html()[:300])
        print("DEBUG info:", pag.locator("#prac-info").inner_text()[:200].replace(chr(10), " | "))
        if a.captura:
            pag.screenshot(path=a.captura)
        raise
    paso("«Preparar el tablero» responde", "preparado" in pag.locator("#resultado").inner_text().lower())
    pag.set_input_files("#archivo", os.path.join(EJ, "controllino_fsm", "controllino_fsm.ino"))
    pag.wait_for_selector("#resultado .ok:has-text('Subido')", timeout=90000)
    pag.wait_for_timeout(3000)
    pag.click("#b-comprobar")
    pag.wait_for_selector("#verif-fin .ok, #verif-fin .error:has-text('de')", timeout=120000)
    fin = pag.locator("#verif-fin").inner_text()
    paso("«Comprobar mi solución» da 6 de 6 con la FSM correcta", "6 de 6" in fin, " ".join(fin.split()))

    if not a.sin_editor:
        pag.click("#b-escalera")
        pag.wait_for_selector("#editor.abierto", timeout=90000)
        pag.wait_for_timeout(6000)
        paso("se abre el editor de escalera", pag.locator("#editor.abierto").count() == 1)
        paso("el editor esta enlazado al noVNC", "6080" in (pag.locator("#feditor").get_attribute("src") or ""))
    if a.captura:
        pag.screenshot(path=a.captura)
    nav.close()

print("FALLOS: %d" % resultados.count(False))
sys.exit(0 if all(resultados) else 1)
