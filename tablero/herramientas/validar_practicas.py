#!/usr/bin/env python3
"""Valida tablero/practicas/*/practica.json contra lo que entiende el autocorrector y el banco.

    python3 tablero/herramientas/validar_practicas.py [--godot ruta/a/tablero_lab.gd]

Comprueba, sin Docker ni gafas:
  * claves obligatorias, id = carpeta, presencia en catalogo.json, archivos que nombra
    (enunciado, plantilla, ejemplos, cargar_plc, generar, solucion_archivos, pc/...);
  * cada paso de `verificacion`: el tipo existe en panel/verificador.py, trae sus campos
    obligatorios, los regex compilan, el equipo existe y los indices caben en su E/S;
  * los puertos de montaje.cables y solucion_cables existen en pasarela.PUERTOS o, si son del
    3D (bornera, jacks, modulos con hilo cautivo), en los nombres que arma godot/scripts/tablero_lab.gd.
Sale con 1 si hay errores (los avisos no cuentan).
"""
import glob
import json
import os
import re
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
REPO = os.path.dirname(RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "pasarela"))
sys.path.insert(0, os.path.join(RAIZ, "panel"))

errores, avisos = [], []


def err(pid, txt):
    errores.append("%s: %s" % (pid, txt))


def aviso(pid, txt):
    avisos.append("%s: %s" % (pid, txt))


# Campos obligatorios de cada tipo de accion (ver la cabecera de panel/verificador.py)
OBLIGATORIOS = {
    "pausa": [], "entrada": ["equipo", "i", "v"], "analogica": ["equipo", "i", "v"],
    "orden": ["equipo", "orden"], "pulsar": ["equipo", "i"],
    "esperar": ["equipo"], "mantener": ["equipo"], "nunca": ["equipo"],
    "serie": ["equipo", "regex"], "mqtt": [], "estado": ["equipo", "clave"],
    "lora_trama": ["equipo"], "energia": ["id"], "docker": ["args"], "pc": ["cmd"],
    "hmi_widget": ["nombre"], "hmi_tocar": ["nombre"], "hmi_var": ["nombre"], "hmi_serie": ["nombre"],
}
CAMPOS_ES = ("do", "rele", "di", "ai", "s24")
# Tamano de cada tabla del estado: (Controllino, ESP32 PLC) -- controllino.py / esp32plc.py / programa.py
TAM = {"controllino": {"do": 24, "rele": 16, "di": 21, "ai": 16}, "esp32plc": {"do": 4, "rele": 2, "di": 8, "ai": 4, "s24": 4}}   # con programa del alumno (PERFILES de programa.py); de fabrica tiene 1 rele


def tipos_del_verificador():
    with open(os.path.join(RAIZ, "panel", "verificador.py"), encoding="utf-8") as f:
        src = f.read()
    return set(re.findall(r'tipo == "(\w+)"', src)) | set(re.findall(r'tipo in \(([^)]*)\)', src) and
                                                          re.findall(r'"(hmi_\w+)"', src))


def puertos_3d(ruta_godot):
    """Nombres de puertos que solo existen en el 3D, sacados de tablero_lab.gd."""
    p = {"bornera": set(), "lead": set(), "jack": set()}
    if not os.path.isfile(ruta_godot):
        return None
    with open(ruta_godot, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"const BORNERA := \[(.*?)\]\]\n", src, re.S)
    if m:
        p["bornera"] = set(re.findall(r'\["([\w.]+)",\s*"', m.group(1) + "]"))
    p["lead"] = set(re.findall(r'_lead\(\w+,\s*"([\w.%]+)"', src))
    p["lead"] |= set(re.findall(r'"([\w.]+)"\s*:\s*_lead', src))
    m = re.search(r"var jacks := \[(.*?)\]\n", src, re.S)
    if m:
        p["jack"] = set(re.findall(r'\["[\w.]*",\s*"([\w.]+)"\]', m.group(1)))
    p["jack"] |= {"GND", "5V"}
    p["texto"] = src
    return p


def puerto_valido(puerto, PUERTOS, g3d):
    if puerto in PUERTOS:
        return True
    if not isinstance(puerto, str) or not re.match(r"^(t\d+)\.", puerto):
        return False
    suf = puerto.split(".", 1)[1]
    if not any(k.startswith(puerto.split(".")[0] + ".") for k in PUERTOS):
        return False                      # tablero que no existe (t9...)
    if g3d is None:
        return True                       # sin godot no se puede decidir
    if suf.startswith("bornera."):
        return suf[len("bornera."):] in g3d["bornera"]
    if suf.startswith("esp32plc.jack."):
        return suf[len("esp32plc.jack."):] in g3d["jack"]
    for pref in ("esp32plc.", "comp.", "epc."):
        resto = suf[len(pref):] if suf.startswith(pref) else None
        if resto is not None and any(re.fullmatch(re.escape(l).replace("%d", r"\d+"), resto) for l in g3d["lead"]):
            return True
    # Pines del Controllino en el 3D (A0, A1...)
    return re.fullmatch(r"controllino\.[A-Z]\d+", suf) is not None


def main():
    ruta_godot = os.path.join(REPO, "godot", "scripts", "tablero_lab.gd")
    if "--godot" in sys.argv:
        ruta_godot = sys.argv[sys.argv.index("--godot") + 1]
    try:
        import pasarela
        PUERTOS, EQUIPOS, ENERGIA = pasarela.PUERTOS, pasarela.EQUIPOS, pasarela.ENERGIA
    except ImportError as e:
        print("No se pudo importar pasarela.py (%s): se omite la validacion de puertos" % e)
        PUERTOS, EQUIPOS, ENERGIA = None, None, None
    g3d = puertos_3d(ruta_godot)
    if g3d is None:
        print("(sin %s: los puertos del 3D no se validan)" % ruta_godot)
    tipos = tipos_del_verificador()
    faltan = set(OBLIGATORIOS) - tipos
    if faltan:
        print("AVISO: el validador conoce tipos que verificador.py no parece tener: %s" % sorted(faltan))
    try:
        with open(os.path.join(RAIZ, "practicas", "catalogo.json"), encoding="utf-8") as f:
            cat = {e["id"]: e for e in json.load(f)}
    except (OSError, ValueError, KeyError) as e:
        err("catalogo", "no se lee catalogo.json: %s" % e)
        cat = {}
    for ficha in sorted(glob.glob(os.path.join(RAIZ, "practicas", "*", "practica.json"))):
        d = os.path.dirname(ficha)
        pid = os.path.basename(d)
        try:
            with open(ficha, encoding="utf-8") as f:
                p = json.load(f)
        except ValueError as e:
            err(pid, "JSON invalido: %s" % e)
            continue
        for k in ("id", "titulo", "equipo", "enunciado", "montaje", "verificacion"):
            if k not in p:
                err(pid, "falta la clave «%s»" % k)
        if p.get("id") != pid:
            err(pid, "id «%s» distinto de la carpeta" % p.get("id"))
        if pid not in cat:
            err(pid, "no esta en catalogo.json")
        for k in ("enunciado", "plantilla"):
            if p.get(k) and not os.path.isfile(os.path.join(d, p[k])):
                err(pid, "%s «%s» no existe" % (k, p[k]))
        eq = p.get("equipo", "")
        if eq and EQUIPOS is not None and eq not in EQUIPOS:
            err(pid, "equipo «%s» desconocido" % eq)
        # Ejemplos: carpeta ejemplos_arduino/<n>/<n>.ino
        nombres = set(cat.get(pid, {}).get("ejemplos", []))
        if p.get("solucion_ejemplo"):
            nombres.add(p["solucion_ejemplo"])
        nombres.update(x[1] for x in p.get("solucion_equipos", []) if len(x) > 1)
        for n in sorted(nombres):
            if not os.path.isfile(os.path.join(RAIZ, "ejemplos_arduino", n, n + ".ino")):
                err(pid, "ejemplo «%s» sin ejemplos_arduino/%s/%s.ino" % (n, n, n))
        for x in p.get("solucion_equipos", []):
            if len(x) != 2 or (EQUIPOS is not None and x[0] not in EQUIPOS):
                err(pid, "solucion_equipos mal formado: %r" % (x,))
        for a in p.get("solucion_archivos", []):
            if not os.path.isfile(os.path.join(d, "pc", a)) and not os.path.isfile(os.path.join(d, a)):
                aviso(pid, "solucion_archivos «%s» no esta en la carpeta de la practica" % a)
        m = p.get("montaje", {})
        for eqp, ruta in m.get("cargar_plc", []):
            base = os.path.join(RAIZ, "practicas", ruta)
            if not (os.path.isfile(base) or os.path.isfile(os.path.splitext(base)[0] + ".bin")):
                err(pid, "cargar_plc «%s» no existe (ni .bin)" % ruta)
        for g in m.get("generar", []):
            if not os.path.isfile(os.path.join(RAIZ, g[0])):
                err(pid, "generar: falta el script %s" % g[0])
        if m.get("pila") and not os.path.isfile(os.path.join(d, "pc", "docker-compose.yml")):
            err(pid, "montaje.pila pero no hay pc/docker-compose.yml")
        for a in m.get("pc_actualizar", []):
            if not os.path.isfile(os.path.join(d, "pc", a)):
                err(pid, "pc_actualizar «%s» no esta en pc/" % a)
        for id_, v in m.get("energia", []):
            if ENERGIA is not None and id_.split(".")[-1] not in ENERGIA:
                err(pid, "energia: «%s» no es un interruptor conocido" % id_)
        for par in list(m.get("cables", [])) + list(p.get("solucion_cables", [])):
            if len(par) != 2:
                err(pid, "cable mal formado: %r" % (par,))
                continue
            if PUERTOS is not None:
                for puerto in par:
                    if not puerto_valido(puerto, PUERTOS, g3d):
                        err(pid, "puerto «%s» no existe en la pasarela ni en el 3D" % puerto)
        for eqo, o in m.get("ordenes", []):
            if EQUIPOS is not None and eqo not in EQUIPOS:
                err(pid, "montaje.ordenes: equipo «%s» desconocido" % eqo)
            if not isinstance(o, dict) or "cmd" not in o:
                err(pid, "montaje.ordenes: orden sin «cmd»: %r" % (o,))
        if not p.get("verificacion"):
            aviso(pid, "sin pasos de verificacion")
        for i, paso in enumerate(p.get("verificacion", []), 1):
            ctx = "paso %d" % i
            if not paso.get("txt"):
                err(pid, "%s sin «txt»" % ctx)
            if not isinstance(paso.get("hacer"), list) or not paso["hacer"]:
                err(pid, "%s sin lista «hacer»" % ctx)
                continue
            for a in paso["hacer"]:
                t = a.get("tipo")
                if t not in OBLIGATORIOS or (tipos and t not in tipos):
                    err(pid, "%s: tipo «%s» desconocido para el verificador" % (ctx, t))
                    continue
                for k in OBLIGATORIOS[t]:
                    if k not in a:
                        err(pid, "%s (%s): falta «%s»" % (ctx, t, k))
                if t in ("esperar", "mantener", "nunca") and not any(a.get(c) for c in CAMPOS_ES):
                    err(pid, "%s (%s): sin condiciones (%s)" % (ctx, t, "/".join(CAMPOS_ES)))
                for k in ("regex", "carga", "tema", "texto"):
                    if k in a:
                        try:
                            re.compile(a[k])
                        except re.error as e:
                            err(pid, "%s (%s): regex «%s» invalido: %s" % (ctx, t, a[k], e))
                e = a.get("equipo")
                if e and EQUIPOS is not None and e not in EQUIPOS:
                    err(pid, "%s (%s): equipo «%s» desconocido" % (ctx, t, e))
                if t == "lora_trama" and a.get("plc") and EQUIPOS is not None and a["plc"] not in EQUIPOS:
                    err(pid, "%s: plc «%s» desconocido" % (ctx, a["plc"]))
                if e and "." in e:
                    tam = TAM.get(e.split(".")[1], {})
                    for c in CAMPOS_ES:
                        for idx in (a.get(c) or {}):
                            if not str(idx).isdigit():
                                err(pid, "%s (%s): indice «%s» de %s no es numero" % (ctx, t, idx, c))
                            elif tam and c in tam and int(idx) >= tam[c]:
                                err(pid, "%s (%s): %s[%s] fuera de rango (%s tiene %d)" % (ctx, t, c, idx, e, tam[c]))
                            elif tam and c not in tam:
                                err(pid, "%s (%s): %s no existe en %s" % (ctx, t, c, e))
                    if t in ("entrada", "pulsar") and "i" in a and tam and int(a["i"]) >= tam["di"]:
                        err(pid, "%s (%s): entrada %s fuera de rango" % (ctx, t, a["i"]))
                    if t == "analogica" and "i" in a and tam and int(a["i"]) >= tam["ai"]:
                        err(pid, "%s (analogica): A%s fuera de rango en %s" % (ctx, a["i"], e))
                if t == "docker" and not isinstance(a.get("args"), list):
                    err(pid, "%s (docker): args debe ser una lista" % ctx)
                if t == "energia" and ENERGIA is not None and a.get("id", "").split(".")[-1] not in ENERGIA:
                    err(pid, "%s (energia): «%s» no es un interruptor conocido" % (ctx, a.get("id")))
    print("%d practicas revisadas" % len(glob.glob(os.path.join(RAIZ, "practicas", "*", "practica.json"))))
    for a in avisos:
        print("  aviso  " + a)
    for e in errores:
        print("  ERROR  " + e)
    print("%d errores, %d avisos" % (len(errores), len(avisos)))
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
