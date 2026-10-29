"""Prueba de extremo a extremo de la pasarela, haciendo de gafas.

Monta la Practica 1 (Modbus RTU entre tableros), pulsa I16 en el tablero 1 y
comprueba que se enciende la fila D0 D6 D12 del tablero 2. Tambien enchufa el
Controllino 1 al switch y mira que Docker lo haya conectado a tab_lan.

    python tablero/herramientas/prueba_pasarela.py [host] [puerto]
Deja el tablero descableado al terminar.
"""
import json, socket, subprocess, sys, time

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PUERTO = int(sys.argv[2]) if len(sys.argv) > 2 else 7070
fallos = 0


def chk(nombre, ok, detalle=""):
    global fallos
    print("  %s  %s  %s" % ("OK   " if ok else "FALLO", nombre, detalle))
    fallos += 0 if ok else 1


s = socket.create_connection((HOST, PUERTO), timeout=5)
f = s.makefile("rw", encoding="utf-8", newline="\n")


def enviar(d):
    f.write(json.dumps(d) + "\n")
    f.flush()


def estado(seg=1.0):
    """Ultimo estado recibido tras esperar `seg`."""
    fin, ult = time.time() + seg, None
    while time.time() < fin:
        d = json.loads(f.readline())
        if d.get("t") == "estado":
            ult = d
    return ult


def redes(c):
    r = subprocess.run(["docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", c],
                       capture_output=True, text=True)
    return json.loads(r.stdout or "{}")


enviar({"t": "limpiar"})
estado(2.0)
chk("sin cable, tab1-controllino fuera de tab_lan", "tab_lan" not in redes("tab1-controllino"))

cables = [("t1.controllino.eth", "t1.switch.p1"), ("t2.controllino.eth", "t2.switch.p1"),
          ("t1.controllino.485A", "t2.controllino.485A"), ("t1.controllino.485B", "t2.controllino.485B")]
for i, (a, b) in enumerate(cables):
    enviar({"t": "cable", "id": "prueba%d" % i, "a": a, "b": b, "color": "ffaa00"})
enviar({"t": "orden", "equipo": "t1.controllino", "orden": {"cmd": "modo", "v": 3}})
enviar({"t": "orden", "equipo": "t2.controllino", "orden": {"cmd": "modo", "v": 0}})
estado(3.0)
chk("cable enchufado -> docker network connect", "tab_lan" in redes("tab1-controllino"),
    str(redes("tab1-controllino").get("tab_lan", {}).get("IPAddress", "")))

enviar({"t": "orden", "equipo": "t1.controllino", "orden": {"cmd": "entrada", "i": 16, "v": 1}})
e = estado(3.0)
do2 = e["equipos"]["t2.controllino"]["do"]
chk("I16 de T1 enciende D0 D6 D12 de T2 por RS-485", do2[0] == 1 and do2[6] == 1 and do2[12] == 1,
    "do[0,6,12]=%s" % [do2[0], do2[6], do2[12]])
tramas = [t for t in e.get("tramas", []) if "485" in json.dumps(t) or "RTU" in json.dumps(t)]
chk("se ven tramas del bus", len(e.get("tramas", [])) > 0, "%d tramas" % len(e.get("tramas", [])))

enviar({"t": "orden", "equipo": "t1.controllino", "orden": {"cmd": "entrada", "i": 16, "v": 0}})
e = estado(3.0)
chk("al soltar se apaga", e["equipos"]["t2.controllino"]["do"][0] == 0)

enviar({"t": "limpiar"})
estado(3.0)
chk("descableado -> fuera de tab_lan", "tab_lan" not in redes("tab1-controllino"))
print("FALLOS: %d" % fallos)
sys.exit(fallos)
