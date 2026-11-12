#!/usr/bin/env python3
"""Lleva el aula mejorada en Blender (Laboratorio.glb, de LABO.rar) al marco del aula del
laboratorio digital (godot/models/lab/aula.glb) y la prepara para el Quest 3.

Que hace
  1. Lee el GLB con su jerarquia y materiales (los de Blender: Vidrio, LosaGranito, MetalNegro...).
     Descarta los nodos "Ifc*Type/..." (plantillas en el origen, no son piezas del aula).
  2. Lo transforma al marco de aula.glb (x=-x_ifc, y=z_ifc, z=y_ifc). Como el GLB de Blender
     es x=+x_ifc, y=z_ifc, z=-y_ifc, basta un giro de 180 grados sobre Y: (x,y,z) -> (-x,y,-z).
     Despues se mide contra las 20 cajas de aula_mesas.json y se aplica el desfase residual.
  3. Decima con cuadricas (fast_simplification) con un TOPE de triangulos POR INSTANCIA calculado
     por llenado de agua para no pasar del presupuesto total CONTANDO instancias (Quest 3).
  4. Funde por material (pocas llamadas de dibujo), normales suaves salvo bordes > 40 grados.
  5. Separa la pantalla del aula (PantallaOneScreen):
        pantalla_marco   nodo con el bisel/soporte decimado (hijos pantalla_marco_<material>)
        pantalla_imagen  quad limpio con UV 0..1 (u a la derecha, v hacia abajo, convencion glTF),
                         material neutro negro mate para que Godot le ponga la textura de video.
     y escribe godot/data/aula2_pantalla.json (centro, normal, ancho, alto, esquinas, aspecto).

    python -I tablero/herramientas/labo_a_aula.py <Laboratorio.glb> godot/models/lab/aula2.glb \
        godot/data/aula2_pantalla.json godot/data/aula_mesas.json

Requiere: pip install trimesh numpy fast-simplification
"""
import json
import os
import re
import struct
import sys

import fast_simplification
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

if len(sys.argv) != 5:
    sys.exit(__doc__)
ent, sal_glb, sal_json, mesas_json = sys.argv[1:5]

PRESUPUESTO_TOTAL = 250000      # triangulos contando instancias (limite duro 300 000)
PRESUPUESTO_MARCO = 16000       # bisel y soporte de la pantalla (limite 20 000)
ALBEDO_MAX = 0.78               # blancos 1.0 (MaderaBlanca, MetalBlanco) se queman con la luz
ALFA_CRISTAL = 0.28             # Blender exporto Cristal*/Vidrio opacos (gris 0.4): se hacen translucidos
ANGULO_SUAVE = 40.0             # grados: por encima, borde duro
MIN_TRI_DECIMAR = 24

# ---- materiales crudos del GLB (precision plena, trimesh los cuantiza a 8 bits) ------------
raw = open(ent, "rb").read()
jl = struct.unpack("<I", raw[12:16])[0]
J = json.loads(raw[20:20 + jl])
MATS = {m["name"]: m for m in J["materials"]}


def propiedades(nombre):
    m = MATS.get(nombre or "", {})
    p = m.get("pbrMetallicRoughness", {})
    col = list(p.get("baseColorFactor", [1, 1, 1, 1])) if p.get("baseColorFactor") else [1, 1, 1, 1]
    met = p.get("metallicFactor")
    rug = p.get("roughnessFactor")
    emi = m.get("emissiveFactor")
    es = m.get("extensions", {}).get("KHR_materials_emissive_strength", {}).get("emissiveStrength", 1.0)
    alfa_modo = m.get("alphaMode", "OPAQUE")
    cristal = bool(re.match(r"(Cristal|Vidrio)", nombre or ""))
    rgb = [min(float(c), ALBEDO_MAX) for c in col[:3]]
    a = float(col[3])
    if cristal and a >= 0.99:
        a = ALFA_CRISTAL
    return {"rgb": rgb, "a": a, "met": 0.0 if met is None else float(met),
            "rug": 0.5 if rug is None else float(rug), "emi": emi, "emi_f": float(es),
            "blend": a < 0.99 or alfa_modo == "BLEND"}


def clave_mat(nombre):
    p = propiedades(nombre)
    q = lambda x, s: round(x / s) * s
    return (tuple(round(q(c, 0.02), 3) for c in p["rgb"]), round(q(p["a"], 0.05), 2), round(q(p["met"], 0.1), 1),
            round(q(p["rug"], 0.1), 1), tuple(p["emi"]) if p["emi"] else None)


# ---- carga --------------------------------------------------------------------------------
esc = trimesh.load(ent, force="scene")
G = esc.graph
D = np.diag([-1.0, 1.0, -1.0, 1.0])        # marco Blender -> marco aula (giro 180 sobre Y)

geoms = {}          # nombre geom -> dict(v, f, mat, uv, inst=[(nodo, M)])
for nodo in G.nodes_geometry:
    if re.match(r"Ifc\w*Type/", nodo):
        continue
    T, gn = G[nodo]
    g = esc.geometry[gn]
    nm = getattr(getattr(g.visual, "material", None), "name", None)
    d = geoms.setdefault(gn, {"v": np.asarray(g.vertices, float), "f": np.asarray(g.faces, np.int64),
                              "mat": nm, "uv": getattr(g.visual, "uv", None), "inst": []})
    d["inst"].append((nodo, D @ T))


def familia(nodo):
    if nodo.startswith("PantallaOneScreen"):
        return "pantalla"
    if nodo.startswith("IfcFurniture"):
        return "mesas"
    return "aula"


# ---- calibracion con las 20 mesas ---------------------------------------------------------
js = json.load(open(mesas_json, encoding="utf-8"))
cajas = [(np.array(m["caja_godot"]["min"]), np.array(m["caja_godot"]["max"]), m["id"]) for m in js["mesas"]]
mesa_box = {}
for gn, d in geoms.items():
    for nodo, M in d["inst"]:
        if familia(nodo) == "mesas":
            w = trimesh.transform_points(d["v"], M)
            nodo = re.sub(r"_[0-9a-f]{6}$", "", nodo)          # las primitivas de una mesa comparten prefijo
            a, b = mesa_box.get(nodo, (np.full(3, np.inf), np.full(3, -np.inf)))
            mesa_box[nodo] = (np.minimum(a, w.min(0)), np.maximum(b, w.max(0)))
print("mesas en el GLB:", len(mesa_box))


def emparejar(desfase):
    """cada mesa del GLB con la caja JSON de centro mas cercano; devuelve lista de (dmin, dmax, id)"""
    out, usados = [], set()
    for nodo, (a, b) in sorted(mesa_box.items()):
        c = (a + b) / 2 + desfase
        k = int(np.argmin([np.linalg.norm((cj[0] + cj[1]) / 2 - c) for cj in cajas]))
        out.append((a + desfase - cajas[k][0], b + desfase - cajas[k][1], cajas[k][2], nodo))
        usados.add(k)
    return out, len(usados)


r0, n0 = emparejar(np.zeros(3))
dev0 = max(float(np.abs(np.concatenate([x[0], x[1]])).max()) for x in r0)
print("sin desfase: mesas emparejadas distintas %d/20, desviacion maxima de caja %.1f mm" % (n0, dev0 * 1000))
# desfase residual = mediana de la diferencia de centros (solo si mejora)
dc = np.array([((x[0] + x[1]) / 2) for x in r0])
off = -np.median(dc, axis=0)
off[1] = 0.0 if abs(off[1]) < 0.003 else off[1]
r1, n1 = emparejar(off)
dev1 = max(float(np.abs(np.concatenate([x[0], x[1]])).max()) for x in r1)
print("desfase residual (m) = %s -> desviacion maxima %.1f mm (%d/20 distintas)" % (off.round(4), dev1 * 1000, n1))
if dev1 < dev0 and np.linalg.norm(off) > 0.003:
    OFF = off
    marco_r = r1
else:
    OFF = np.zeros(3)
    marco_r = r0
TF = np.eye(4)
TF[:3, 3] = OFF
for d in geoms.values():
    d["inst"] = [(n, TF @ M) for n, M in d["inst"]]
print("TRANSFORMACION aplicada: x->-x, z->-z (giro 180 sobre Y) y traslacion", OFF.round(4).tolist())
for dmin, dmax, ident, nodo in marco_r:
    e = float(np.abs(np.concatenate([dmin, dmax])).max()) * 1000
    print("   %-8s %-34s desviacion de caja %.1f mm" % (ident, nodo, e))

# ---- pantalla: geometria de imagen -------------------------------------------------------
pant = None
for gn, d in geoms.items():
    if d["mat"] == "Pantalla":
        pant = (gn, d)
assert pant, "no hay primitiva con material Pantalla"
gn, d = pant
assert len(d["inst"]) == 1
M = d["inst"][0][1]
w = trimesh.transform_points(d["v"], M)
tri = w[d["f"]]
nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
area = np.linalg.norm(nrm, axis=1)
n_prom = (nrm / np.maximum(area[:, None], 1e-12) * area[:, None]).sum(0)
n_prom /= np.linalg.norm(n_prom)
centro_aula = np.array([-5.85, 1.1, 3.4])           # centro de la planta (aula_mesas.json)
pl = js["planta"]["godot"]
centro_aula = np.array([(pl["x_min"] + pl["x_max"]) / 2, 1.0, (pl["z_min"] + pl["z_max"]) / 2])
cen = w.mean(0)
if np.dot(n_prom, centro_aula - cen) < 0:
    n_prom = -n_prom                                # que mire hacia el aula
arriba = np.array([0.0, 1.0, 0.0])
der = np.cross(arriba, n_prom)                      # a la derecha del que mira (n hacia el observador)
der /= np.linalg.norm(der)
vup = np.cross(n_prom, der)
vup /= np.linalg.norm(vup)
# comprobacion: orientacion del UV original respecto a "derecha"/"arriba"
if d["uv"] is not None:
    uv = np.asarray(d["uv"])
    cu = np.polyfit(w @ der, uv[:, 0], 1)[0]
    cv = np.polyfit(w @ vup, uv[:, 1], 1)[0]
    print("UV original: du/d(derecha)=%.3f  dv/d(arriba)=%.3f  uv u[%.2f,%.2f] v[%.2f,%.2f]"
          % (cu, cv, uv[:, 0].min(), uv[:, 0].max(), uv[:, 1].min(), uv[:, 1].max()))
s_der, s_up = w @ der, w @ vup
x0, x1, y0, y1 = s_der.min(), s_der.max(), s_up.min(), s_up.max()
prof = float((w @ n_prom).max()) + 0.001                 # un milimetro por delante
ancho, alto = float(x1 - x0), float(y1 - y0)
esq = {"inferior_izquierda": x0 * der + y0 * vup + prof * n_prom, "inferior_derecha": x1 * der + y0 * vup + prof * n_prom,
       "superior_izquierda": x0 * der + y1 * vup + prof * n_prom, "superior_derecha": x1 * der + y1 * vup + prof * n_prom}
centro_p = (esq["inferior_izquierda"] + esq["superior_derecha"]) / 2
qv = np.array([esq["superior_izquierda"], esq["superior_derecha"], esq["inferior_izquierda"], esq["inferior_derecha"]])
quv = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], float)           # v hacia abajo (glTF)
qf = np.array([[0, 2, 1], [1, 2, 3]])                             # antihorario visto desde n
tn = np.cross(qv[qf[0, 1]] - qv[qf[0, 0]], qv[qf[0, 2]] - qv[qf[0, 0]])
if np.dot(tn, n_prom) < 0:
    qf = qf[:, ::-1]
mat_img = PBRMaterial(name="PantallaImagen", baseColorFactor=[0.02, 0.02, 0.02, 1.0], metallicFactor=0.0,
                      roughnessFactor=1.0, alphaMode="OPAQUE", doubleSided=False)
quad = trimesh.Trimesh(vertices=qv, faces=qf, process=False)
quad.visual = trimesh.visual.TextureVisuals(uv=quv, material=mat_img)
print("PANTALLA: centro %s normal %s ancho %.3f alto %.3f aspecto %.3f" % (centro_p.round(3), n_prom.round(3), ancho, alto, ancho / alto))

pj = {"_leeme": "Pantalla del aula espejo en ejes de Godot (marco de aula.glb/aula2.glb). La normal mira hacia el aula. "
                "UV del nodo pantalla_imagen: (0,0) esquina superior izquierda, (1,1) inferior derecha (glTF/Godot).",
      "nodo": "pantalla_imagen", "centro": centro_p.round(4).tolist(), "normal": n_prom.round(4).tolist(),
      "derecha": der.round(4).tolist(), "arriba": vup.round(4).tolist(),
      "ancho_m": round(ancho, 4), "alto_m": round(alto, 4), "aspecto": round(ancho / alto, 4),
      "esquinas": {k: v.round(4).tolist() for k, v in esq.items()}}
os.makedirs(os.path.dirname(os.path.abspath(sal_json)), exist_ok=True)
json.dump(pj, open(sal_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---- presupuesto y decimacion -------------------------------------------------------------
gpant = [gn_ for gn_, dd in geoms.items() if dd["inst"] and familia(dd["inst"][0][0]) == "pantalla" and dd["mat"] != "Pantalla"]
gresto = [gn_ for gn_, dd in geoms.items() if gn_ not in gpant and dd["mat"] != "Pantalla"]


PESO = {"IfcLamp": 0.06, "IfcDoor": 0.4, "IfcWindow": 0.4, "IfcCovering": 0.5}   # lo que menos se mira


def peso(g_):
    return PESO.get(geoms[g_]["inst"][0][0].split("/")[0], 1.0)


def limite(g_, c):
    return max(4, int(c * peso(g_)))


def tope(lista, presupuesto):
    """mayor tope c con sum(n_inst * min(tris, c * peso)) <= presupuesto"""
    lo, hi = 1, max(len(geoms[g_]["f"]) for g_ in lista)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        t = sum(len(geoms[g_]["inst"]) * min(len(geoms[g_]["f"]), limite(g_, mid)) for g_ in lista)
        if t <= presupuesto:
            lo = mid
        else:
            hi = mid - 1
    return lo


def agrupar_vertices(v, f, c):
    """respaldo cuando la cuadrica se atasca (mallas de muchas piezas sueltas): rejilla de
    vertices cuyo lado crece por biseccion hasta quedar en <= c triangulos"""
    ext = v.max(0) - v.min(0)
    lo, hi = 1e-4, float(ext.max())
    mejor = (v, f)
    for _ in range(18):
        celda = (lo * hi) ** 0.5
        k = np.floor((v - v.min(0)) / celda).astype(np.int64)
        _, idx, inv = np.unique(k, axis=0, return_index=True, return_inverse=True)
        inv = inv.reshape(-1)
        cnt = np.bincount(inv)
        nv = np.zeros((len(cnt), 3))
        for e in range(3):
            nv[:, e] = np.bincount(inv, weights=v[:, e]) / cnt
        nf = inv[f]
        ok = (nf[:, 0] != nf[:, 1]) & (nf[:, 1] != nf[:, 2]) & (nf[:, 0] != nf[:, 2])
        nf = nf[ok]
        if len(nf) <= c:
            mejor = (nv, nf)
            hi = celda
        else:
            lo = celda
    return mejor


def decimar(d, c):
    n = len(d["f"])
    if n <= max(c, MIN_TRI_DECIMAR):
        return d["v"], d["f"]
    m = trimesh.Trimesh(d["v"], d["f"], process=True)       # suelda por posicion
    v, f = m.vertices, m.faces
    for _ in range(3):
        red = 1.0 - max(c, 4) / len(f)
        pv, pf = fast_simplification.simplify(v.astype(np.float32), f.astype(np.int32),
                                              target_reduction=min(max(red, 0.0), 0.995), agg=7)
        gana = len(pf) < len(f) * 0.97
        v, f = pv.astype(float), pf.astype(np.int64)
        if len(f) <= c * 1.05 or not gana:
            break
    if len(f) > c * 1.05:
        v, f = agrupar_vertices(v, f, c)
    return v, f


def reducir(lista, presupuesto):
    """decima y repite con presupuesto menor si el resultado se pasa (la decimacion es aproximada)"""
    pres = presupuesto
    for _ in range(6):
        c = tope(lista, pres)
        sal, total = {}, 0
        for g_ in lista:
            v, f = decimar(geoms[g_], limite(g_, c))
            sal[g_] = (v, f)
            total += len(f) * len(geoms[g_]["inst"])
        if total <= presupuesto:
            return sal, total, c
        pres = int(pres * presupuesto / total * 0.99)
    return sal, total, c


orig_resto = sum(len(geoms[g_]["f"]) * len(geoms[g_]["inst"]) for g_ in gresto)
orig_marco = sum(len(geoms[g_]["f"]) * len(geoms[g_]["inst"]) for g_ in gpant)
print("triangulos originales con instancias: aula+mesas %d, pantalla %d (+%d de la imagen)" % (orig_resto, orig_marco, len(d["f"])))
dec_resto, tot_resto, c1 = reducir(gresto, PRESUPUESTO_TOTAL - PRESUPUESTO_MARCO - 2)
dec_marco, tot_marco, c2 = reducir(gpant, PRESUPUESTO_MARCO)
print("tope por instancia: aula %d tri, marco %d tri" % (c1, c2))

# ---- agrupar por material y escribir -----------------------------------------------------
grupos = {}       # (familia, clave) -> [(V, F)]
nombres = {}      # (familia, clave) -> {nombre: tris}
for gn_, (v, f) in list(dec_resto.items()) + list(dec_marco.items()):
    dd = geoms[gn_]
    for nodo, M in dd["inst"]:
        fam = familia(nodo)
        key = (fam, clave_mat(dd["mat"]))
        grupos.setdefault(key, []).append((trimesh.transform_points(v, M), f))
        nombres.setdefault(key, {})
        nombres[key][dd["mat"] or "sin_material"] = nombres[key].get(dd["mat"] or "sin_material", 0) + len(f)

escena = trimesh.Scene()
escena.graph.update(frame_to="pantalla_marco", frame_from=escena.graph.base_frame, matrix=np.eye(4))
res = {"aula": 0, "mesas": 0, "pantalla": 0}
usados = set()
for (fam, clave), partes in sorted(grupos.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
    vs, cs, off_ = [], [], 0
    for v, f in partes:
        vs.append(v)
        cs.append(f + off_)
        off_ += len(v)
    m = trimesh.Trimesh(np.vstack(vs), np.vstack(cs), process=True)
    m.update_faces(m.nondegenerate_faces())
    m = m.smooth_shaded if False else m
    try:
        m = trimesh.graph.smooth_shade(m, angle=np.radians(ANGULO_SUAVE), facet_minarea=None)
    except Exception as e:                      # respaldo: normales planas
        print("   smooth_shade fallo (%s): normales planas" % e)
        m = m.copy()
        m.unmerge_vertices()
    nom_mat = max(nombres[(fam, clave)].items(), key=lambda kv: kv[1])[0]
    nom_mat = re.sub(r"[^A-Za-z0-9_]", "_", nom_mat)
    p = propiedades(max(nombres[(fam, clave)].items(), key=lambda kv: kv[1])[0])
    nombre = "%s_%s" % ({"aula": "aula", "mesas": "mesas", "pantalla": "pantalla_marco"}[fam], nom_mat)
    k = 1
    base = nombre
    while nombre in usados:
        k += 1
        nombre = "%s_%d" % (base, k)
    usados.add(nombre)
    cmat = list(clave[0]) + [clave[1]]
    emi = None
    if clave[4]:
        emi = [min(1.0, e * p["emi_f"] / 8.0) for e in clave[4]] if p["emi_f"] > 1 else list(clave[4])
    mat = PBRMaterial(name=nom_mat, baseColorFactor=cmat, metallicFactor=clave[2], roughnessFactor=max(clave[3], 0.15),
                      emissiveFactor=emi, alphaMode="BLEND" if cmat[3] < 0.99 else "OPAQUE", doubleSided=True)
    m.visual = trimesh.visual.TextureVisuals(material=mat)
    if fam == "pantalla":
        escena.add_geometry(m, node_name=nombre, geom_name=nombre, parent_node_name="pantalla_marco")
    else:
        escena.add_geometry(m, node_name=nombre, geom_name=nombre)
    res[fam] += len(m.faces)
    print("%-34s %7d tri  rgba=%s" % (nombre, len(m.faces), tuple(round(q, 2) for q in cmat)))

escena.add_geometry(quad, node_name="pantalla_imagen", geom_name="pantalla_imagen")
res["pantalla"] += 0
total = sum(res.values()) + len(quad.faces)
os.makedirs(os.path.dirname(os.path.abspath(sal_glb)), exist_ok=True)
escena.export(sal_glb)
print("\nTRIANGULOS por grupo: aula %d | mesas %d | pantalla_marco %d | pantalla_imagen %d" % (res["aula"], res["mesas"], res["pantalla"], len(quad.faces)))
print("TOTAL con instancias (todo esta horneado, sin instancias en el GLB): %d  (limite 300000)" % total)
print("mallas: %d | escrito %s (%.1f MB) y %s" % (len(escena.geometry), sal_glb, os.path.getsize(sal_glb) / 1048576, sal_json))
