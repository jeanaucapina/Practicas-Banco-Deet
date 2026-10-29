#!/usr/bin/env python3
"""Convierte el modelo BIM del laboratorio (IFC) en un GLB ligero para el fondo del
tablero 3D (godot/models/tablero/laboratorio.glb).

El IFC original pesa 14 MB y 674 000 triangulos (solo las 15 lamparas llevan 447 000):
imposible en un visor. Aqui se conserva lo que da la sensacion de aula y se simplifica
el resto:

  muros, suelo, techo, columna, baranda, conductos   geometria original (pocos triangulos)
  mesas y bancos       tablero + 4 patas a partir de su caja envolvente
  ventanas             un cristal translucido
  puerta, cortinas     cajas
  lamparas             cajas emisivas

Ejes: IFC (x este, y norte, z arriba) -> Godot (x = -x_ifc, y = z_ifc, z = y_ifc), un
giro propio: el alumno de pie en +z mira hacia -z = el SUR del aula, hacia los bancos de la
pared sur (los que tienen el vidrio delante), y su derecha (+x) es el oeste. El origen
queda en la esquina suroeste del aula. Las mesas se dibujan blancas y con la cubierta a
0,74 m (la mesa del tablero queda 1 cm por encima, sin parpadeos).

    pip install ifcopenshell trimesh numpy
    python ifc_a_glb.py "Modelos Laboratorios/Laboratorio.ifc" godot/models/tablero/laboratorio.glb
"""
import sys

import ifcopenshell
import ifcopenshell.geom
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

if len(sys.argv) != 3:
    sys.exit(__doc__)
entrada, salida = sys.argv[1], sys.argv[2]

f = ifcopenshell.open(entrada)
ajustes = ifcopenshell.geom.settings()
ajustes.set("use-world-coords", True)
it = ifcopenshell.geom.iterator(ajustes, f, 4)

grupos = {}          # nombre de material -> lista de (vertices, caras) en ejes de Godot


def a_godot(v):
    v = np.asarray(v, dtype=float).reshape(-1, 3)
    w = v[:, [0, 2, 1]].copy()                          # (x, y, z) -> (x, z, y)
    w[:, 0] *= -1                                       # ... y x -> -x: giro propio
    return w


def anadir(nombre, v, caras):
    grupos.setdefault(nombre, []).append((v, np.asarray(caras, dtype=np.int64).reshape(-1, 3)))


def caja(nombre, a, b):
    """Caja alineada a los ejes entre las esquinas a y b (ya en ejes de Godot)."""
    m = trimesh.creation.box(extents=np.maximum(np.asarray(b) - np.asarray(a), 1e-3))
    m.apply_translation((np.asarray(a) + np.asarray(b)) / 2)
    anadir(nombre, m.vertices, m.faces)


MATERIALES = {          # albedos medios: con la luz del tablero los blancos puros se queman
    "muro": ((0.58, 0.60, 0.63, 1.0), None, 1.0),
    "suelo": ((0.34, 0.36, 0.40, 1.0), None, 0.8),
    "techo": ((0.66, 0.67, 0.69, 1.0), None, 1.0),
    "metal": ((0.48, 0.50, 0.53, 1.0), None, 0.5),
    "madera": ((0.74, 0.75, 0.77, 1.0), None, 0.7),     # mesas blancas
    "patas": ((0.18, 0.19, 0.21, 1.0), None, 0.6),
    "cristal": ((0.45, 0.62, 0.78, 0.30), None, 0.2),
    "puerta": ((0.42, 0.29, 0.19, 1.0), None, 0.8),
    "cortina": ((0.62, 0.57, 0.48, 1.0), None, 1.0),
    "lampara": ((0.9, 0.9, 0.85, 1.0), (0.9, 0.9, 0.8), 1.0),
}

if it.initialize():
    while True:
        s = it.get()
        clase = s.product.is_a()
        v = a_godot(s.geometry.verts)
        caras = s.geometry.faces
        if len(v) == 0:
            if not it.next():
                break
            continue
        a, b = v.min(0), v.max(0)
        if clase == "IfcWall":
            anadir("muro", v, caras)
        elif clase == "IfcSlab":
            # Solado (z ~ 0) o techo (y_godot > 2)
            anadir("suelo" if a[1] < 0.5 else "techo", v, caras)
        elif clase in ("IfcColumn",):
            anadir("muro", v, caras)
        elif clase == "IfcRailing":
            anadir("metal", v, caras)
        elif clase == "IfcDuctSegment":
            anadir("metal", v, caras)
        elif clase == "IfcFurniture":
            # tablero de 4 cm arriba y cuatro patas de 4 cm en las esquinas
            grosor, pata, alto = 0.04, 0.04, 0.74
            b = np.array([b[0], alto, b[2]])
            caja("madera", (a[0], alto - grosor, a[2]), b)
            for px in (a[0], b[0] - pata):
                for pz in (a[2], b[2] - pata):
                    caja("patas", (px, a[1], pz), (px + pata, alto - grosor, pz + pata))
        elif clase == "IfcWindow":
            # cristal: la caja envolvente achatada a su eje mas fino
            eje = int(np.argmin(b - a))
            c = (a + b) / 2
            aa, bb = a.copy(), b.copy()
            aa[eje], bb[eje] = c[eje] - 0.01, c[eje] + 0.01
            caja("cristal", aa, bb)
        elif clase == "IfcDoor":
            caja("puerta", a, b)
        elif clase == "IfcCovering":
            caja("cortina", a - np.array([0, 0, 0.0]), b + np.array([0, 0, 0.0]) + np.where((b - a) < 0.002, 0.02, 0))
        elif clase == "IfcLamp":
            caja("lampara", a, b)
        if not it.next():
            break

escena = trimesh.Scene()
total = 0
for nombre, partes in grupos.items():
    vs, cs, off = [], [], 0
    for v, c in partes:
        vs.append(v)
        cs.append(c + off)
        off += len(v)
    malla = trimesh.Trimesh(vertices=np.vstack(vs), faces=np.vstack(cs), process=False)
    color, emision, rugosidad = MATERIALES[nombre]
    mat = PBRMaterial(baseColorFactor=color, metallicFactor=0.0, roughnessFactor=rugosidad,
                      emissiveFactor=emision, alphaMode="BLEND" if color[3] < 1 else "OPAQUE", doubleSided=True)
    malla.visual = trimesh.visual.TextureVisuals(material=mat)
    escena.add_geometry(malla, node_name=nombre, geom_name=nombre)
    total += len(malla.faces)
    print("%-8s %6d triangulos" % (nombre, len(malla.faces)))
print("TOTAL", total, "triangulos")
escena.export(salida)
print("escrito", salida)
