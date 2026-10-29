"""Arranque de un equipo del tablero: si se subio un programa del alumno
(`.\\lab.ps1 subir <equipo> <archivo.ino>`) corre ese; si no, la imitacion de
fabrica en Python (controllino.py / esp32plc.py).
`.\\lab.ps1 subir <equipo> fabrica` vuelve a la de fabrica."""

import os
import sys

ID = os.environ.get("TAB_ID", "")
tipo = ID.split(".")[-1]
if os.path.exists("/programas/%s/programa" % ID):
    guion = "programa.py"
else:
    guion = "%s.py" % tipo
os.execv(sys.executable, [sys.executable, guion])
