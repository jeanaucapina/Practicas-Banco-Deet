"""Prueba de seguridad del panel (sin Docker): arranca panel.py en un puerto libre con una
clave docente TEMPORAL (nunca la real) e intenta lo que haria un alumno o una web hostil.

    python3 tablero/herramientas/prueba_panel_seguridad.py

Necesita /tablero -> el directorio tablero del repo (ln -sfn <repo>/tablero /tablero).
Sale con codigo 1 si algo falla.
"""
import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(os.path.dirname(AQUI), "panel", "panel.py")
CLAVE = "clave-de-prueba-no-real"
fallos = []


def libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pet(puerto, metodo, ruta, cuerpo=None, cab=None, crudo=False):
    c = http.client.HTTPConnection("127.0.0.1", puerto, timeout=15)
    try:
        c.putrequest(metodo, ruta, skip_host=False)
        cab = dict(cab or {})
        if cuerpo is not None and "Content-Length" not in cab:
            cab["Content-Length"] = str(len(cuerpo))
        for k, v in cab.items():
            c.putheader(k, v)
        c.endheaders(cuerpo if isinstance(cuerpo, bytes) else (cuerpo or "").encode() if cuerpo is not None else None)
        r = c.getresponse()
        datos = r.read()
        return r.status, datos, r
    except (ConnectionError, http.client.HTTPException, socket.timeout) as e:
        return 0, repr(e).encode(), None
    finally:
        c.close()


def ok(cond, nombre, det=""):
    print(("  ok    " if cond else "  FALLA ") + nombre + (" · " + det if det and not cond else ""))
    if not cond:
        fallos.append(nombre)


def main():
    if not os.path.isdir("/tablero/panel"):
        print("Falta /tablero -> tablero/ del repo"); return 2
    tmp = tempfile.mkdtemp(prefix="panel_seg_")
    ruta_clave = os.path.join(tmp, "clave.sha256")
    with open(ruta_clave, "w") as f:
        f.write(hashlib.sha256(CLAVE.encode()).hexdigest() + "\n")
    puerto = libre()
    env = dict(os.environ, PANEL_PUERTO=str(puerto), PANEL_CLAVE_ARCHIVO=ruta_clave,
               PANEL_SESIONES_ARCHIVO=os.path.join(tmp, "ses.json"), PANEL_PASARELA="127.0.0.1:1", PANEL_BROKER="127.0.0.1")
    errlog = open(os.path.join(tmp, "err.log"), "w")
    srv = subprocess.Popen([sys.executable, PANEL], env=env, stdout=subprocess.DEVNULL, stderr=errlog)
    try:
        for _ in range(50):
            if pet(puerto, "GET", "/api/docente")[0] == 200:
                break
            time.sleep(0.2)
        else:
            print("el panel no arranca"); return 2

        print("Rutas y estaticos")
        for ruta in ("/guias/..%2f..%2fetc%2fpasswd", "/guias/../README.md", "/guias/%2e%2e/x.pdf", "/guias/a%00.pdf",
                     "/guias//etc/passwd", "/guias/..\\x.pdf"):
            st, b, _ = pet(puerto, "GET", ruta)
            ok(st in (404, 400) and b"root:" not in b, "traversal " + ruta, str(st))
        st, b, _ = pet(puerto, "GET", "/api/guia?g=../../etc/passwd")
        ok(st == 404, "api/guia solo claves conocidas", str(st))
        st, b, _ = pet(puerto, "GET", "/api/practica?id=../../etc/passwd")
        ok(st == 404, "api/practica id con ..", str(st))

        print("Parametros y JSON rotos: nada de trazas ni conexion colgada")
        for m, ruta, cuerpo in (("GET", "/api/captura?seg=abc", None), ("POST", "/api/saturar?nivel=x", b""),
                                ("POST", "/api/orden", b"{no json"), ("POST", "/api/lora_config", b"[1,2"),
                                ("POST", "/api/montar", b'{"cables":[[1]]}'), ("POST", "/api/montar", b"{no"),
                                ("POST", "/api/hmi_cargar?n=9", b"{}"), ("POST", "/api/docente_entrar", b"\xff\xfe"),
                                ("POST", "/api/cargar?archivo=build/generated_plc.st&equipo=t1.openplc", b""),
                                ("POST", "/api/cargar?archivo=../../etc/passwd&equipo=t1.openplc", b"")):
            st, b, _ = pet(puerto, m, ruta, cuerpo)
            ok(st in (200, 400, 403, 404, 500) and b"Traceback" not in b, "%s %s" % (m, ruta), "%s %r" % (st, b[:80]))
        st, b, _ = pet(puerto, "POST", "/api/subir", b"x", {"Content-Length": "abc"})
        ok(st == 400, "Content-Length no numerico -> 400", str(st))
        st, b, _ = pet(puerto, "POST", "/api/subir", b"x", {"Content-Length": "-5"})
        ok(st == 400, "Content-Length negativo -> 400", str(st))
        st, b, _ = pet(puerto, "POST", "/api/subir?equipo=t1.controllino&nombre=a.ino", None, {"Content-Length": str(500 * 1024 * 1024)})
        ok(st == 413, "cuerpo de 500 MB rechazado sin leerlo", str(st))

        print("Subidas y nombres")
        for nombre in ("../../etc/cron.d/x.ino", "a;rm -rf /.ino", "$(id).ino", "..", ""):
            st, b, _ = pet(puerto, "POST", "/api/subir?equipo=t1.openplc&nombre=" + nombre.replace(" ", "%20"), b"x")
            ok(st == 200 and b"Traceback" not in b, "nombre raro %r" % nombre, str(st))
        st, b, _ = pet(puerto, "POST", "/api/subir?equipo=../x&nombre=a.ino", b"x")
        ok(json.loads(b).get("ok") is False, "equipo desconocido rechazado")
        # Nada se escribio fuera de programas/ ni quedo un archivo traversal
        ok(not os.path.exists("/etc/cron.d/x.ino"), "no se escribio fuera de la carpeta")

        print("Modo docente")
        for m, ruta in (("GET", "/api/lora_demo"), ("POST", "/api/lora_demo"), ("POST", "/api/cablear_solucion?id=L7"),
                        ("POST", "/api/mes_demo")):
            st, b, _ = pet(puerto, m, ruta, b"" if m == "POST" else None)
            ok(st == 403, "%s %s exige docente" % (m, ruta), str(st))
        st, b, _ = pet(puerto, "GET", "/api/practicas")
        ok(b"ejemplos" not in b, "catalogo sin soluciones para el alumno")
        for pid in ("L1", "L2", "L7", "L13"):
            st, b, _ = pet(puerto, "GET", "/api/practica?id=" + pid)
            if st == 200:
                d = json.loads(b)
                ok(not any(k.startswith("solucion") for k in d) and "demo_lora" not in d, "practica %s sin solucion al alumno" % pid)
        st, b, _ = pet(puerto, "GET", "/api/practicas")
        sol = [e["ejemplos"] for e in json.loads(b) if e.get("ejemplos")]
        st, b, _ = pet(puerto, "POST", "/api/subir_ejemplo?equipo=t1.controllino&ejemplo=__nada__")
        ok(st == 404, "ejemplo inexistente 404", str(st))
        for cookie in ("docente=falsa", "docente=", "docente=" + "A" * 5000, "docente=a;docente=b"):
            st, b, _ = pet(puerto, "GET", "/api/docente", None, {"Cookie": cookie})
            ok(json.loads(b)["activo"] is False, "cookie falsa no es docente: %s" % cookie[:20])
        st, b, _ = pet(puerto, "POST", "/api/docente_entrar", json.dumps({"clave": "mala"}))
        ok(st == 403, "clave mala 403", str(st))
        st, b, r = pet(puerto, "POST", "/api/docente_entrar", json.dumps({"clave": CLAVE}))
        ck = (r.getheader("Set-Cookie") or "") if r else ""
        ok(st == 200 and "HttpOnly" in ck and "SameSite=Strict" in ck, "login docente con cookie HttpOnly+SameSite", ck[:40])
        cookie = ck.split(";")[0]
        st, b, _ = pet(puerto, "GET", "/api/docente", None, {"Cookie": cookie})
        ok(json.loads(b)["activo"], "cookie docente valida")
        st, b, _ = pet(puerto, "GET", "/api/lora_demo", None, {"Cookie": cookie})
        ok(st == 200, "docente accede a lora_demo", str(st))

        print("CSRF")
        st, b, _ = pet(puerto, "POST", "/api/auto?destino=t1", b"", {"Origin": "http://evil.example"})
        ok(st == 403, "POST con Origin ajeno rechazado", str(st))
        st, b, _ = pet(puerto, "POST", "/api/auto?destino=t1", b"", {"Origin": "null"})
        ok(st == 403, "POST con Origin null rechazado", str(st))
        st, b, _ = pet(puerto, "GET", "/api/captura?seg=3&red=tab-lan", None, {"Sec-Fetch-Site": "cross-site"})
        ok(st == 403, "GET cross-site rechazado", str(st))
        st, b, _ = pet(puerto, "POST", "/api/auto?destino=t1", b"", {"Origin": "http://127.0.0.1:%d" % puerto})
        ok(st == 200, "mismo origen permitido", str(st))
        st, b, _ = pet(puerto, "POST", "/api/auto?destino=", b"")
        ok(st == 200, "cliente sin Origin (curl/pruebas) permitido", str(st))

        print("XSS del informe")
        # No hay ruta para fabricar un informe sin banco: se prueba la funcion.
        sys.path.insert(0, "/tablero/panel"); sys.path.insert(0, "/tablero/dispositivos")
        import importlib
        os.environ.update(env)
        pm = importlib.import_module("panel")
        h = pm.informe_html({"practica": "L1", "titulo": "<script>x</script>", "equipo": "e", "hora": "h", "programa": "<img onerror=1>",
                             "subido": "", "sha256": "", "aprobados": 0, "total": 1,
                             "pasos": [{"txt": "<b>t</b>", "ok": False, "motivo": "<script>alert(1)</script>"}]})
        ok("<script>" not in h and "<img" not in h and "<b>" not in h, "informe_html escapa titulo, paso y motivo")

        print("Carga concurrente")
        import threading
        res = []
        def h2():
            res.append(pet(puerto, "GET", "/api/docente")[0])
        ts = [threading.Thread(target=h2) for _ in range(60)]
        [t.start() for t in ts]; [t.join() for t in ts]
        ok(res.count(200) == 60, "60 peticiones paralelas", str(res.count(200)))
        errlog.flush()
        txt = open(os.path.join(tmp, "err.log")).read()
        ok("Traceback" not in txt, "el panel no volco trazas a stderr", txt[-300:])
    finally:
        srv.terminate()
        try:
            srv.wait(5)
        except subprocess.TimeoutExpired:
            srv.kill()
    print("\n%s" % ("TODO BIEN" if not fallos else "FALLOS: %d -> %s" % (len(fallos), fallos)))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
