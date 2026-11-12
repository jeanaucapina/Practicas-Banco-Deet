#!/usr/bin/env python3
"""Arma el paquete del ALUMNO: solo lo que hace falta para correr el banco virtual.

    python tablero/herramientas/paquete_alumnos.py DESTINO [--sin-web] [--docente]

--docente: version del docente (privada): incluye lo que excluye export-ignore (docente/, soluciones,
clave) y no quita el cableado de solucion ni el codigo del PLC de produccion.

DESTINO es una carpeta (normalmente el clon del repositorio de los alumnos); se vacia
-menos su .git- y se llena con:
  - tablero/ (portal, pasarela, dispositivos, practicas, compose...) sin los CAD ni el
    material del docente (lo que marca .gitattributes con export-ignore);
  - lab.ps1 y docs/INSTALACION.md;
  - el 3D web ya exportado (tablero/run/web): el alumno no necesita Godot ni baja ~1 GB
    de plantillas. Se genera con `.\\lab.ps1 web` antes de empaquetar.
Se toma el contenido de los archivos del arbol de trabajo (lo ya commiteado en el repo del
docente), nunca los no seguidos por git: ni «Talleres Guia» ni nada suelto.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import readme_banco  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parents[2]
INCLUIR = ["tablero", "lab.ps1", "iniciar.cmd", "docs/INSTALACION.md", "docs/readme"]
SIN_PREFIJO = ("tablero/DiseñoTablero", "tablero/Talleres Guia")
SIN_EXT = (".rar", ".stp", ".iam", ".ipt")

GODOT_LEEME = """El proyecto Godot del tablero 3D no va en el paquete del alumno: el 3D web ya viene
exportado en tablero/run/web. Esta carpeta existe solo porque docker-compose.yml la nombra
como contexto de construccion del servicio web.
"""

GITIGNORE = """# Lo que genera el banco en tu PC (tu trabajo, capturas, estado). El 3D web exportado SI va.
tablero/run/*
!tablero/run/web/
tablero/Talleres Guia/
"""


def git(*args):
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=RAIZ, capture_output=True, check=True).stdout


def archivos(docente=False):
    lista = git("ls-files", "-z", "--", *(INCLUIR + (["docente"] if docente else []))).decode("utf-8").split("\0")
    lista = [f for f in lista if f]
    # export-ignore: lo mismo que respeta `git archive` (soluciones, clave del docente...)
    sal = subprocess.run(["git", "check-attr", "-z", "export-ignore", "--stdin"], cwd=RAIZ, capture_output=True,
                         check=True, input="\0".join(lista).encode("utf-8")).stdout.decode("utf-8").split("\0")
    ignorados = set() if docente else {sal[i] for i in range(0, len(sal) - 2, 3) if sal[i + 2] == "set"}
    return [f for f in lista
            if f not in ignorados and not f.startswith(SIN_PREFIJO) and not f.lower().endswith(SIN_EXT)]


CAMPOS_SOLUCION = ("solucion_cables", "solucion_archivos", "solucion_ejemplo", "solucion_equipos")


def limpiar_soluciones(destino):
    """Paquete del alumno: fuera de los practica.json lo que delata la solucion (cableado, ejemplos)."""
    for pj in (destino / "tablero" / "practicas").glob("*/practica.json"):
        d = json.loads(pj.read_text(encoding="utf-8"))
        if any(k in d for k in CAMPOS_SOLUCION):
            for k in CAMPOS_SOLUCION:
                d.pop(k, None)
            pj.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cat = destino / "tablero" / "practicas" / "catalogo.json"
    if cat.is_file():
        c = json.loads(cat.read_text(encoding="utf-8"))
        for e in c:
            e.pop("ejemplos", None)
        cat.write_text(json.dumps(c, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def compilar_plc(destino):
    """El PLC de produccion de L13-L15 es el programa de la L7: al alumno se le da COMPILADO (.bin),
    no su codigo. Se compila en el contenedor del ESP32 del banco (tiene que estar arrancado)."""
    for ino in (RAIZ / "tablero" / "practicas" / "_comun").glob("*.ino"):
        tmp = RAIZ / "tablero" / "programas" / "_paquete.esp32plc"
        shutil.rmtree(tmp, ignore_errors=True)
        (tmp / "fuente").mkdir(parents=True)
        shutil.copy2(ino, tmp / "fuente" / ino.name)
        r = subprocess.run(["docker", "exec", "-e", "TAB_ID=_paquete.esp32plc", "tab1-esp32plc", "python", "compilar.py"],
                           capture_output=True, text=True)
        if r.returncode != 0 or not (tmp / "programa").is_file():
            shutil.rmtree(tmp, ignore_errors=True)
            raise SystemExit("No se pudo compilar %s (¿esta el banco arrancado?): %s" % (ino.name, r.stdout + r.stderr))
        sale = destino / "tablero" / "practicas" / "_comun"
        sale.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp / "programa", sale / (ino.stem + ".bin"))
        shutil.rmtree(tmp, ignore_errors=True)
        (sale / ino.name).unlink(missing_ok=True)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    destino = pathlib.Path(sys.argv[1]).resolve()
    con_web = "--sin-web" not in sys.argv
    docente = "--docente" in sys.argv
    if destino == RAIZ or RAIZ in destino.parents and destino.name in ("tablero", "docs"):
        print("DESTINO no puede ser el repositorio del docente")
        return 1
    destino.mkdir(parents=True, exist_ok=True)
    for x in destino.iterdir():                        # vacia, conservando .git
        if x.name != ".git":
            shutil.rmtree(x) if x.is_dir() else x.unlink()
    n = 0
    for f in archivos(docente):
        origen = RAIZ / f
        if not origen.is_file():
            continue
        d = destino / f
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origen, d)
        n += 1
    inst = destino / "docs" / "INSTALACION.md"       # la seccion «Para el docente» no es del alumno
    if inst.is_file():
        t = inst.read_text(encoding="utf-8")
        inst.write_text(t.split("\n## Para el docente")[0].rstrip() + "\n", encoding="utf-8")
    web = RAIZ / "tablero" / "run" / "web"
    if con_web:
        if not (web / "index.pck").is_file():
            print("Falta tablero/run/web: ejecuta .\\lab.ps1 web (o usa --sin-web)")
            return 1
        mas_nuevo = max((p.stat().st_mtime for p in (RAIZ / "godot" / "scripts").glob("*.gd")), default=0)
        if (web / "index.pck").stat().st_mtime < mas_nuevo:
            print("AVISO: el 3D web es mas viejo que los scripts de godot/; re-exporta con .\\lab.ps1 web")
        shutil.copytree(web, destino / "tablero" / "run" / "web")
    if not docente:
        limpiar_soluciones(destino)
        compilar_plc(destino)
    (destino / "godot").mkdir(exist_ok=True)
    (destino / "godot" / "LEEME.txt").write_text(GODOT_LEEME, encoding="utf-8")
    catalogo = json.loads((RAIZ / "tablero" / "practicas" / "catalogo.json").read_text(encoding="utf-8"))
    texto = readme_banco.readme_docente(catalogo) if docente else readme_banco.readme_alumno(catalogo)
    (destino / "README.md").write_text(texto, encoding="utf-8")
    (destino / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    mb = sum(p.stat().st_size for p in destino.rglob("*") if p.is_file() and ".git" not in p.parts) / 1e6
    print("Paquete %s en %s: %d archivos del repo, %.0f MB%s" % ("DOCENTE" if docente else "ALUMNO", destino, n, mb,
                                                                  "" if con_web else " (sin 3D web)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
