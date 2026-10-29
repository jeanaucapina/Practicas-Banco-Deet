"""Compila el .ino del alumno con el nucleo Arduino virtual (el boton
"Verificar" del Arduino IDE). Corre dentro del contenedor del equipo:

    python compilar.py              (equipo = TAB_ID)

Lee /programas/<TAB_ID>/fuente/ (un .ino y, si hay, .h/.cpp a su lado) y deja
el ejecutable en /programas/<TAB_ID>/programa. Si falla no toca el programa
anterior, escribe los errores con la linea del .ino y sale con codigo 1.

Como el IDE, declara solo las funciones del .ino (prototipos) para poder
usarlas antes de definirlas, y añade #include <Arduino.h>.
"""

import glob
import os
import re
import subprocess
import sys

NUCLEO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arduino")
ID = os.environ.get("TAB_ID", "")
TIPO = ID.split(".")[-1]
BASE = "/programas/%s" % ID
FUENTE = BASE + "/fuente"
OBJ = "/tmp/nucleo_%s" % TIPO
TRABAJO = "/tmp/compilar"
FLAGS = ["-std=gnu++17", "-O1", "-pthread", "-I", NUCLEO, "-I", FUENTE, "-include", "Arduino.h"]
if TIPO == "esp32plc":
    FLAGS += ["-DVINO_ESP32", "-include", "placa_esp32plc.h"]
else:
    FLAGS += ["-DVINO_CONTROLLINO"]

CLAVES = {"if", "while", "for", "switch", "return", "else", "do", "sizeof", "catch", "operator"}
CABECERA = re.compile(r"^(?:template\s*<[^{};]*>\s*)?([A-Za-z_][\w\s\*&:<>,]*?[\s\*&])"
                      r"([A-Za-z_]\w*)\s*\(([^{};]*)\)\s*(?:const\s*)?$", re.S)


def limpiar(t: str) -> str:
    """Comentarios y literales -> espacios (mismas posiciones y saltos)."""
    out, i, n = [], 0, len(t)
    while i < n:
        c = t[i]
        if t.startswith("//", i):
            j = t.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif t.startswith("/*", i):
            j = t.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", t[i:j]))
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and t[j] != c and t[j] != "\n":
                j += 2 if t[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(c + " " * (j - i - 2) + c if j - i >= 2 else " ")
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def prototipos(fuente: str):
    """(linea donde insertarlos, [prototipos]) de las funciones del .ino."""
    t = limpiar(fuente)
    protos, primera = [], None
    prof, ini = 0, 0
    for i, c in enumerate(t):
        if c == "{":
            if prof == 0:
                cab = t[ini:i]
                # Fuera las directivas del preprocesador que queden delante.
                lineas = cab.split("\n")
                k = 0
                while k < len(lineas) and (not lineas[k].strip() or lineas[k].strip().startswith("#")):
                    k += 1
                pos = ini + sum(len(x) + 1 for x in lineas[:k])
                while pos < i and t[pos] in " \t\r\n":
                    pos += 1
                m = CABECERA.match(t[pos:i].strip())
                if m and m.group(2) not in CLAVES and not re.search(r"\b(class|struct|enum|union|namespace)\b", m.group(1)):
                    if m.group(2) not in ("setup", "loop"):
                        protos.append(" ".join(fuente[pos:i].split()) + ";")
                    if primera is None:
                        primera = t.count("\n", 0, pos)
            prof += 1
        elif c == "}":
            prof = max(0, prof - 1)
            if prof == 0:
                ini = i + 1
        elif c == ";" and prof == 0:
            ini = i + 1
        elif c == "\n" and prof == 0 and t[ini:i].strip().startswith("#"):
            ini = i + 1
    return primera, protos


def compilar_nucleo():
    os.makedirs(OBJ, exist_ok=True)
    objs = []
    for src in sorted(glob.glob(os.path.join(NUCLEO, "*.cpp"))):
        o = os.path.join(OBJ, os.path.basename(src)[:-4] + ".o")
        cabs = glob.glob(os.path.join(NUCLEO, "*.h"))
        if not os.path.exists(o) or os.path.getmtime(o) < max(os.path.getmtime(f) for f in [src] + cabs):
            r = subprocess.run(["g++"] + FLAGS + ["-c", src, "-o", o], capture_output=True, text=True)
            if r.returncode != 0:
                sys.stderr.write("ERROR en el nucleo virtual (no es tu programa):\n" + r.stderr)
                sys.exit(2)
        objs.append(o)
    return objs


def main():
    inos = sorted(glob.glob(os.path.join(FUENTE, "*.ino")))
    if len(inos) != 1:
        sys.stderr.write("Hace falta exactamente un .ino en %s (hay %d)\n" % (FUENTE, len(inos)))
        sys.exit(1)
    ino = inos[0]
    nombre = os.path.basename(ino)
    texto = open(ino, encoding="utf-8", errors="replace").read()
    linea, protos = prototipos(texto)
    lineas = texto.split("\n")
    if linea is None or not protos:
        cpp = '#line 1 "%s"\n%s\n' % (nombre, texto)
    else:
        cpp = ('#line 1 "%s"\n' % nombre + "\n".join(lineas[:linea]) + "\n" + "\n".join(protos) +
               '\n#line %d "%s"\n' % (linea + 1, nombre) + "\n".join(lineas[linea:]) + "\n")
    os.makedirs(TRABAJO, exist_ok=True)
    sketch = os.path.join(TRABAJO, "sketch.cpp")
    open(sketch, "w", encoding="utf-8").write(cpp)

    objs = compilar_nucleo()
    fuentes = [sketch] + sorted(glob.glob(os.path.join(FUENTE, "*.cpp")) + glob.glob(os.path.join(FUENTE, "*.c")))
    # El paquete de Industrial Shields da el objeto RS485 del ESP32 PLC sin #include
    # (guia L10, Listado L10.3); salvo si el programa usa la ArduinoRS485 oficial.
    todo = "".join(open(f, encoding="utf-8", errors="replace").read() for f in fuentes[1:]) + texto
    extra = ["-include", "RS485.h"] if TIPO == "esp32plc" and "ArduinoRS485" not in todo else []
    for f in fuentes:
        o = os.path.join(TRABAJO, os.path.basename(f) + ".o")
        r = subprocess.run(["g++"] + FLAGS + extra + ["-c", f, "-o", o], capture_output=True, text=True)
        if r.returncode != 0:
            sys.stderr.write(r.stderr.replace(TRABAJO + "/", "").replace(FUENTE + "/", ""))
            sys.exit(1)
        objs.append(o)
    tmp = BASE + "/programa.tmp"
    r = subprocess.run(["g++", "-pthread"] + objs + ["-o", tmp], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.replace(TRABAJO + "/", ""))
        sys.exit(1)
    os.replace(tmp, BASE + "/programa")
    open(BASE + "/nombre", "w").write(nombre)
    print("Compilado %s para %s" % (nombre, ID))


if __name__ == "__main__":
    main()
