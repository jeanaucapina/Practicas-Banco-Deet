#!/usr/bin/env python3
"""Convierte el modelo BIM del laboratorio (IFC) en un GLB de ALTA resolucion para el
"laboratorio digital" (fase F1 de docs/PLAN_LAB_DIGITAL.md).

A diferencia de ifc_a_glb.py (fondo ligero del tablero: mesas = caja + 4 patas, 100 KB),
aqui se conserva la geometria REAL de muros, losas, columnas, barandas, conductos, puertas,
ventanas, cortinas y mobiliario, con los colores del IFC (IfcSurfaceStyle) y los cristales
translucidos. Solo las lamparas (447 000 de los 674 000 triangulos) se sustituyen por una
carcasa oscura + un panel emisivo. El resto se decima de forma ligera (ventanas, cortinas,
puertas y mesas) hasta quedar muy por debajo de 250 000 triangulos.

Ejes (los mismos que ifc_a_glb.py): IFC (x este, y norte, z arriba) -> Godot
    x_godot = -x_ifc,  y_godot = z_ifc,  z_godot = y_ifc
(un giro propio; se invierte el orden de los vertices de cada cara para conservar las
normales hacia fuera). El origen sigue siendo el del IFC (esquina suroeste del aula).

Salidas:
  godot/models/lab/aula.glb      mallas agrupadas por material (pocas llamadas de dibujo):
                                 las del mobiliario se llaman "mesas_<n>" y las del edificio
                                 "aula_<n>"; los cristales son materiales con alfa.
  godot/data/aula_mesas.json     un registro por IfcFurniture (mesa_01.. ordenadas por x_ifc
                                 y luego y_ifc: id, GlobalId, nombre, centro y tamano en ejes
                                 de Godot, altura de la cubierta, caja en ejes IFC), la
                                 planta del aula (de los muros) y las puertas.

    python -I tablero/herramientas/ifc_aula_hd.py \
        "Modelos Laboratorios/Laboratorio.ifc" godot/models/lab/aula.glb godot/data/aula_mesas.json

Requiere: pip install ifcopenshell trimesh numpy fast-simplification
"""
import json
import os
import sys

import fast_simplification
import ifcopenshell
import ifcopenshell.geom
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

if len(sys.argv) != 4:
    sys.exit(__doc__)
entrada, salida_glb, salida_json = sys.argv[1:4]

# reduccion de triangulos por clase (0 = sin decimar). Se aplica por (elemento, material).
REDUCCION = {"IfcFurniture": 0.45, "IfcWindow": 0.6, "IfcCovering": 0.6, "IfcDoor": 0.6}
MIN_CARAS = 200          # submallas mas pequenas no se decimaran
ALBEDO_MAX, ALBEDO_MIN = 0.78, 0.10   # blancos/negros puros se queman o se pierden con la luz
ALFA_MIN = 0.20          # los cristales con transparencia 1.0 en el IFC seguirian invisibles


def a_godot(v):
    v = np.asarray(v, dtype=float).reshape(-1, 3)
    w = v[:, [0, 2, 1]].copy()
    w[:, 0] *= -1
    return w


def decimar(v, c, r):
    """Decima una submalla con cuadricas; devuelve (v, c)."""
    if r <= 0 or len(c) < MIN_CARAS:
        return v, c
    m = trimesh.Trimesh(v, c, process=True)          # suelda vertices por posicion
    if len(m.faces) < MIN_CARAS:
        return v, c
    pv, pc = fast_simplification.simplify(m.vertices.astype(np.float32), m.faces.astype(np.int32),
                                          target_reduction=r)
    return pv.astype(float), pc.astype(np.int64)


def clave_material(m):
    """(r, g, b, alfa) cuantizados: los cientos de estilos del IFC se funden en pocos."""
    d = m.diffuse
    rgb = [float(np.clip(q, ALBEDO_MIN, ALBEDO_MAX)) for q in (d.r(), d.g(), d.b())]
    t = float(m.transparency)
    alfa = 1.0 if np.isnan(t) or t <= 0 else max(ALFA_MIN, 1.0 - t)
    return tuple(round(q / 0.04) * 0.04 for q in rgb) + (round(alfa, 2),)


f = ifcopenshell.open(entrada)
ajustes = ifcopenshell.geom.settings()
ajustes.set("use-world-coords", True)
it = ifcopenshell.geom.iterator(ajustes, f, 4)

grupos = {}          # (familia, clave material) -> lista de (vertices, caras) en ejes Godot
mesas, puertas = [], []
cajas_muro, losas_techo = [], []
conteo_ifc = {}      # clase -> triangulos originales


def anadir(familia, clave, v, c):
    if len(c):
        grupos.setdefault((familia, clave), []).append((v, c))


def caja(a, b):
    m = trimesh.creation.box(extents=np.maximum(np.asarray(b) - np.asarray(a), 1e-3))
    m.apply_translation((np.asarray(a) + np.asarray(b)) / 2)
    return m.vertices, m.faces[:, [0, 2, 1]]


LAMP_CARCASA = (0.10, 0.10, 0.11, 1.0)
LAMP_PANEL = (0.95, 0.95, 0.88, 1.0)

if it.initialize():
    while True:
        s = it.get()
        p = s.product
        clase = p.is_a()
        faces = np.asarray(s.geometry.faces, dtype=np.int64).reshape(-1, 3)
        verts = np.asarray(s.geometry.verts, dtype=float).reshape(-1, 3)
        conteo_ifc[clase] = conteo_ifc.get(clase, 0) + len(faces)
        if len(faces) == 0:
            if not it.next():
                break
            continue
        v = a_godot(verts)
        c = faces[:, [0, 2, 1]]                        # giro propio: invierte el orden
        a, b = v.min(0), v.max(0)

        if clase == "IfcLamp":
            # carcasa oscura (la caja) + panel emisivo fino justo debajo
            vv, cc = caja(a, b)
            anadir("aula", ("carcasa",), vv, cc)
            ina = np.array([a[0] + 0.03, a[1] - 0.004, a[2] + 0.03])
            inb = np.array([b[0] - 0.03, a[1] + 0.002, b[2] - 0.03])
            vv, cc = caja(ina, inb)
            anadir("aula", ("panel",), vv, cc)
        else:
            familia = "mesas" if clase == "IfcFurniture" else "aula"
            ids = np.asarray(s.geometry.material_ids)
            mats = s.geometry.materials
            red = REDUCCION.get(clase, 0.0)
            for k in sorted(set(ids.tolist())):
                sel = c[ids == k]
                uso = np.unique(sel)
                remap = -np.ones(len(v), dtype=np.int64)
                remap[uso] = np.arange(len(uso))
                vv, cc = decimar(v[uso], remap[sel], red)
                anadir(familia, clave_material(mats[k]) if k >= 0 else (0.5, 0.5, 0.5, 1.0), vv, cc)

        if clase == "IfcFurniture":
            ai, bi = verts.min(0), verts.max(0)
            mesas.append({"global_id": p.GlobalId, "nombre": p.Name, "tipo": p.ObjectType or p.is_a(),
                          "ifc_min": ai, "ifc_max": bi, "tris_ifc": len(faces)})
        elif clase == "IfcDoor":
            ai, bi = verts.min(0), verts.max(0)
            puertas.append({"global_id": p.GlobalId, "nombre": p.Name,
                            "centro": ((a + b) / 2).round(4).tolist(),
                            "tamano": (b - a).round(4).tolist(),
                            "ifc_min": ai.round(4).tolist(), "ifc_max": bi.round(4).tolist()})
        elif clase == "IfcWall":
            cajas_muro.append((verts.min(0), verts.max(0)))
        elif clase == "IfcSlab" and verts.min(0)[2] > 2.0:
            losas_techo.append((verts.min(0), verts.max(0)))
        if not it.next():
            break

# ---- JSON de mesas -----------------------------------------------------------------------
mesas.sort(key=lambda m: (round(float(m["ifc_min"][0] + m["ifc_max"][0]) / 2, 3),
                          round(float(m["ifc_min"][1] + m["ifc_max"][1]) / 2, 3)))
reg = []
for i, m in enumerate(mesas, 1):
    ai, bi = m["ifc_min"], m["ifc_max"]
    a = np.array([-bi[0], ai[2], ai[1]])
    b = np.array([-ai[0], bi[2], bi[1]])
    reg.append({"id": "mesa_%02d" % i, "global_id": m["global_id"], "nombre": m["nombre"],
                "tipo": m["tipo"],
                "centro": ((a + b) / 2).round(4).tolist(),
                "tamano": {"ancho_x": round(float(b[0] - a[0]), 4), "alto_y": round(float(b[1] - a[1]), 4),
                           "fondo_z": round(float(b[2] - a[2]), 4)},
                "altura_cubierta": round(float(b[1]), 4),
                "caja_godot": {"min": a.round(4).tolist(), "max": b.round(4).tolist()},
                "caja_ifc": {"min": ai.round(4).tolist(), "max": bi.round(4).tolist()},
                "triangulos_ifc": m["tris_ifc"]})

# planta interior del aula: x de los muros oeste/este, y del muro sur y de la losa de techo
muros_al = [w for w in cajas_muro if w[1][2] - w[0][2] > 2.0]       # muros de suelo a techo
x0 = max(w[1][0] for w in muros_al if w[1][0] < 1.0)                # cara interior del oeste
x1 = min(w[0][0] for w in muros_al if w[0][0] > 10.0)               # cara interior del este
y0 = max(w[1][1] for w in muros_al if w[1][1] < 1.0)                # cara interior del sur
techo = max(losas_techo, key=lambda w: (w[1][0] - w[0][0]) * (w[1][1] - w[0][1]))
y1 = float(techo[1][1])
alto = float(techo[0][2])
planta = {
    "ifc": {"x_min": round(float(x0), 4), "x_max": round(float(x1), 4),
            "y_min": round(float(y0), 4), "y_max": round(y1, 4), "alto": round(alto, 4)},
    "godot": {"x_min": round(-float(x1), 4), "x_max": round(-float(x0), 4),
              "z_min": round(float(y0), 4), "z_max": round(y1, 4), "alto": round(alto, 4)},
    "nota": "x_godot = -x_ifc, y_godot = z_ifc, z_godot = y_ifc; interior de los muros, techo = losa grande a z>2",
}
datos = {"ejes": "Godot: x = -x_ifc, y = z_ifc, z = y_ifc (origen = origen del IFC)",
         "fuente": os.path.basename(entrada), "planta": planta, "puertas": puertas, "mesas": reg}
os.makedirs(os.path.dirname(os.path.abspath(salida_json)), exist_ok=True)
with open(salida_json, "w", encoding="utf-8") as fh:
    json.dump(datos, fh, ensure_ascii=False, indent=1)

# ---- GLB ---------------------------------------------------------------------------------
escena = trimesh.Scene()
resumen = {"aula": 0, "mesas": 0}
cuenta = {}
for (familia, clave), partes in sorted(grupos.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
    vs, cs, off = [], [], 0
    for v, c in partes:
        vs.append(v)
        cs.append(c + off)
        off += len(v)
    V, C = np.vstack(vs), np.vstack(cs)
    # normales planas por cara y soldadura por (posicion, normal): bordes duros como en CAD
    n = np.cross(V[C[:, 1]] - V[C[:, 0]], V[C[:, 2]] - V[C[:, 0]])
    ln = np.linalg.norm(n, axis=1)
    C, n, ln = C[ln > 1e-12], n[ln > 1e-12], ln[ln > 1e-12]
    n = n / ln[:, None]
    filas = np.hstack([V[C.reshape(-1)], np.repeat(n, 3, axis=0)])
    unico, inv = np.unique(np.round(filas, 5), axis=0, return_inverse=True)
    malla = trimesh.Trimesh(vertices=unico[:, :3], faces=inv.reshape(-1, 3), vertex_normals=unico[:, 3:],
                            process=False)
    if clave == ("carcasa",):
        color, emis, rug, nombre = LAMP_CARCASA, None, 0.6, "aula_lamparas"
    elif clave == ("panel",):
        color, emis, rug, nombre = LAMP_PANEL, (0.95, 0.95, 0.85), 1.0, "aula_lamparas_luz"
    else:
        color, emis, rug = clave, None, 0.7
        cuenta[familia] = cuenta.get(familia, 0) + 1
        nombre = "%s_%02d" % (familia, cuenta[familia])
    translucido = color[3] < 1.0
    mat = PBRMaterial(name=nombre, baseColorFactor=color, metallicFactor=0.0, roughnessFactor=0.15 if translucido else rug,
                      emissiveFactor=emis, alphaMode="BLEND" if translucido else "OPAQUE",
                      doubleSided=(familia != "mesas"))
    malla.visual = trimesh.visual.TextureVisuals(material=mat)
    escena.add_geometry(malla, node_name=nombre, geom_name=nombre)
    resumen[familia] += len(malla.faces)
    print("%-20s %7d tri  color=%s" % (nombre, len(malla.faces), tuple(round(q, 2) for q in color)))
os.makedirs(os.path.dirname(os.path.abspath(salida_glb)), exist_ok=True)
escena.export(salida_glb)

print("\nTriangulos originales del IFC por clase:", conteo_ifc)
print("TOTAL IFC %d" % sum(conteo_ifc.values()))
print("Grupo aula (edificio + lamparas) %d | grupo mesas %d | TOTAL %d triangulos"
      % (resumen["aula"], resumen["mesas"], sum(resumen.values())))
print("mallas:", len(escena.geometry), "| mesas:", len(reg), "| puertas:", len(puertas))
print("planta aula (ifc):", planta["ifc"])
print("escrito", salida_glb, "(%d KB)" % (os.path.getsize(salida_glb) // 1024), "y", salida_json)
