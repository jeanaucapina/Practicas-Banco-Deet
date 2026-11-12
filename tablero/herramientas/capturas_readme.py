"""Regenera las capturas del README (docs/readme/*.png). Necesita el banco arriba con la practica L11 preparada
(portal :8090, 3D :8091, MES :8095 y Odoo :8069 con la base `banco`), Playwright (python -m playwright install chromium).
    python tablero/herramientas/capturas_readme.py
"""
import json
import time
import urllib.request

from playwright.sync_api import sync_playwright

import pathlib
RAIZ_P = pathlib.Path(__file__).resolve().parents[2]
OUT = str(RAIZ_P / "docs" / "readme")
RAIZ = str(RAIZ_P)


def http(url, data=None, metodo="GET"):
    r = urllib.request.Request(url, data=data, method=metodo)
    with urllib.request.urlopen(r, timeout=120) as f:
        return f.read().decode()


# 1. el PLC con el programa de produccion (como lo subiria un alumno) y una orden de 40 piezas
ino = open(RAIZ + r"\tablero\ejemplos_arduino\esp32plc_modbus_tcp\esp32plc_modbus_tcp.ino", "rb").read()
print(http("http://localhost:8090/api/subir?equipo=t1.esp32plc&nombre=esp32plc_modbus_tcp.ino", ino, "POST")[:120])
time.sleep(3)
print(http("http://localhost:8095/api/crear_orden?cantidad=40"))
http("http://localhost:8095/api/nueva_orden")

args = ["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
with sync_playwright() as p:
    b = p.chromium.launch(args=args)
    c = b.new_context(viewport={"width": 1400, "height": 860}, device_scale_factor=1)
    pg = c.new_page()

    # 2. MES con la orden a mitad
    pg.goto("http://localhost:8095")
    for _ in range(40):
        pg.wait_for_timeout(1000)
        o = json.loads(http("http://localhost:8095/api/oee"))["orden"]
        if o["producidas"] >= 14:
            break
    pg.screenshot(path=OUT + "/mes.png")
    print("MES", o["nombre"], o["producidas"], "/", o["objetivo"])

    # 3. portal + 3D con L11
    pg.goto("http://localhost:8090/lab")
    pg.wait_for_timeout(25000)
    pg.select_option("#prac", "L11")
    pg.wait_for_timeout(3500)
    pg.screenshot(path=OUT + "/portal.png")

    # 4. el 3D solo
    pg2 = c.new_page()
    pg2.goto("http://localhost:8091/")
    pg2.wait_for_timeout(25000)
    pg2.screenshot(path=OUT + "/tablero3d.png")

    # 5. Odoo: ordenes de fabricacion
    pg3 = c.new_page()
    pg3.goto("http://localhost:8069/web/login?db=banco")
    pg3.fill("input[name=login]", "admin")
    pg3.fill("input[name=password]", "admin")
    pg3.click("button[type=submit]")
    pg3.wait_for_timeout(5000)
    pg3.goto("http://localhost:8069/odoo/action-mrp.mrp_production_action")
    pg3.wait_for_timeout(6000)
    pg3.screenshot(path=OUT + "/odoo.png")

    # 6. diagrama de la piramide ISA-95
    pg4 = c.new_page()
    pg4.goto("" + RAIZ_P.as_uri() + "/docs/bancos_implementacion.html")
    pg4.locator("#tabs button").nth(1).click()
    pg4.wait_for_timeout(500)
    pg4.locator(".tarjeta").first.screenshot(path=OUT + "/piramide.png")
    b.close()
print("ok")
