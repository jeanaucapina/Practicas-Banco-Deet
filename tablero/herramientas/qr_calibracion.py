"""Genera el PDF imprimible con los QR de calibración del laboratorio digital.

Convención del texto (la lee godot/scripts/camara_qr.gd, ver docs/CALIBRACION_QR.md):
    LAB-UCUENCA:<FIJO|VISOR>:<id>:<lado_mm>
<lado_mm> es el lado del cuadrado NEGRO del código (sin la zona blanca de alrededor).
QR versión 2 (25×25 módulos) a propósito: su patrón de alineación da la cuarta esquina con
precisión, que es lo que necesita el cálculo de la pose. Mayúsculas: modo alfanumérico.

Uso:
    python3 tablero/herramientas/qr_calibracion.py                       # valores por defecto
    python3 tablero/herramientas/qr_calibracion.py --fijo 2 --lado-fijo 150 --visor 4 --lado-visor 100 -o qr.pdf
Necesita: pip install qrcode reportlab

IMPRIMIR AL 100 % (tamaño real), sin «ajustar a la página». Comprobar con una regla la barra
de 100 mm de cada hoja: si no mide 100 mm, el visor calculará mal la distancia.
"""

import argparse
import math

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

PREFIJO = "LAB-UCUENCA"
ZONA_MODULOS = 3          # zona blanca de silencio (el estándar pide 4; 3 basta y cabe en A4)
# Estimación del alcance: cámara de passthrough de ~1280 px de ancho y ~90° de campo
# horizontal => focal ~640 px. Se necesitan ~2–3 px por módulo para decodificar.
FOCAL_PX = 640.0


def matriz(texto: str):
    """QR versión 2 (25×25) forzada: trae patrón de alineación, que da la cuarta esquina
    con precisión (en la versión 1 se extrapola y la pose sale peor en vistas oblicuas)."""
    q = qrcode.QRCode(version=2, error_correction=ERROR_CORRECT_M, border=0)
    q.add_data(texto)
    q.make(fit=False)
    return q.get_matrix(), q.version


def alcance_m(lado_mm: float, modulos: int, px_por_modulo: float) -> float:
    return (lado_mm / modulos) * FOCAL_PX / px_por_modulo / 1000.0


def dibujar_qr(c, texto, x, y, lado_mm):
    """(x, y) = esquina inferior izquierda del cuadrado negro, en puntos."""
    m, version = matriz(texto)
    n = len(m)
    mod = lado_mm * mm / n
    z = ZONA_MODULOS * mod
    c.setFillColorRGB(1, 1, 1)
    c.rect(x - z, y - z, n * mod + 2 * z, n * mod + 2 * z, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    for i, fila in enumerate(m):
        for j, v in enumerate(fila):
            if v:
                c.rect(x + j * mod, y + (n - 1 - i) * mod, mod * 1.002, mod * 1.002, stroke=0, fill=1)
    # marcas de corte (línea discontinua por fuera de la zona blanca)
    c.setDash(3, 3)
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.rect(x - z - 2 * mm, y - z - 2 * mm, n * mod + 2 * z + 4 * mm, n * mod + 2 * z + 4 * mm)
    c.setDash()
    return n, version


def barra_100mm(c, x, y):
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(1)
    c.line(x, y, x + 100 * mm, y)
    for k in range(11):
        h = 3 * mm if k % 5 == 0 else 1.5 * mm
        c.line(x + k * 10 * mm, y, x + k * 10 * mm, y + h)
    c.setFont("Helvetica", 8)
    c.drawString(x, y - 4 * mm, "Comprueba con una regla: esta barra debe medir 100 mm (imprimir al 100 %, sin ajustar a la página)")


def pie(c, texto):
    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.35, 0.35, 0.35)
    c.drawString(12 * mm, 8 * mm, texto)
    c.setFillColorRGB(0, 0, 0)


def portada(c, args):
    W, H = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(15 * mm, H - 25 * mm, "QR de calibración · Laboratorio digital (Quest 3)")
    c.setFont("Helvetica", 10)
    lineas = [
        "Sirven para que varios visores compartan el mismo sistema de coordenadas: las plantas, la pelota",
        "y los avatares de los compañeros coinciden con la sala real sin alinear la mesa a mano.",
        "",
        "QR FIJO: pégalo plano en una pared o en el borde de una mesa, a la altura de los ojos si es pared.",
        "  Todos los visores lo miran una vez y quedan alineados al aula. Indica en la app dónde está (ver doc).",
        "QR DE VISOR: uno por visor (el número es el del visor). Pégalo en una tarjeta rígida ARRIBA o ATRÁS",
        "  de la correa, centrado. NUNCA en el frente del visor: ahí están las cámaras de seguimiento y el",
        "  sensor de profundidad. Mide la distancia del centro del QR a los ojos y apúntala en la app.",
        "  Basta con que otro visor lo mire un segundo para alinear a los dos.",
        "",
        "Imprime al 100 % (tamaño real). Comprueba la barra de 100 mm de cada hoja con una regla.",
        "No plastifiques con brillo (reflejos); papel mate o cartulina. Que no quede curvado.",
        "",
        "Alcance estimado (NO medido: depende de la cámara del Quest, la luz y el ángulo):",
    ]
    y = H - 37 * mm
    for t in lineas:
        c.drawString(15 * mm, y, t)
        y -= 5.2 * mm
    for nombre, lado in (("fijo", args.lado_fijo), ("visor", args.lado_visor)):
        n = len(matriz(f"{PREFIJO}:{nombre.upper()}:1:{lado}")[0])
        c.drawString(20 * mm, y, f"  {nombre}: {lado} mm, {n}×{n} módulos de {lado / n:.1f} mm  →  "
                     f"cómodo hasta ~{alcance_m(lado, n, 3):.1f} m, límite ~{alcance_m(lado, n, 2):.1f} m")
        y -= 5.2 * mm
    y -= 3 * mm
    c.drawString(15 * mm, y, "Para más alcance, genera uno más grande:  python3 tablero/herramientas/qr_calibracion.py --lado-fijo 180")
    barra_100mm(c, 15 * mm, 30 * mm)
    pie(c, "Generado por tablero/herramientas/qr_calibracion.py · documentación: docs/CALIBRACION_QR.md")


def hoja_fijo(c, ident, lado):
    W, H = A4
    texto = f"{PREFIJO}:FIJO:{ident}:{lado}"
    x = (W - lado * mm) / 2
    y = (H - lado * mm) / 2 + 10 * mm
    n, v = dibujar_qr(c, texto, x, y, lado)
    y -= ZONA_MODULOS * lado * mm / n + 2 * mm   # los textos, fuera de la zona blanca
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(W / 2, H - 18 * mm, f"QR FIJO n.º {ident}  ·  lado del cuadrado negro: {lado} mm")
    c.setFont("Helvetica", 10)
    c.drawCentredString(W / 2, y - 14 * mm, f"Contenido: {texto}   (QR versión {v}, {n}×{n} módulos de {lado / n:.2f} mm)")
    c.drawCentredString(W / 2, y - 20 * mm, "Pegar plano en pared o mesa. Indicar en la app su posición en el aula.")
    barra_100mm(c, (W - 100 * mm) / 2, 22 * mm)
    pie(c, "Imprimir al 100 %. El tamaño real lo lee el visor del propio texto del QR: no lo escales.")


def hojas_visor(c, ids, lado):
    W, H = A4
    texto0 = f"{PREFIJO}:VISOR:1:{lado}"
    n = len(matriz(texto0)[0])
    total = lado * mm + 2 * ZONA_MODULOS * (lado * mm / n) + 18 * mm
    cols = max(1, int((W - 20 * mm) // (lado * mm + 2 * ZONA_MODULOS * lado * mm / n + 10 * mm)))
    filas = max(1, int((H - 70 * mm) // total))
    por_hoja = cols * filas
    for k in range(0, len(ids), por_hoja):
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(W / 2, H - 18 * mm, f"QR DE VISOR · lado del cuadrado negro: {lado} mm")
        c.setFont("Helvetica", 10)
        c.drawCentredString(W / 2, H - 25 * mm, "Arriba o atrás de la correa, en tarjeta rígida. NUNCA en el frente del visor.")
        for idx, ident in enumerate(ids[k:k + por_hoja]):
            fi, co = divmod(idx, cols)
            cx = 10 * mm + (W - 20 * mm) * (co + 0.5) / cols
            cy = H - 35 * mm - total * (fi + 1) + 25 * mm
            texto = f"{PREFIJO}:VISOR:{ident}:{lado}"
            dibujar_qr(c, texto, cx - lado * mm / 2, cy, lado)
            zy = cy - ZONA_MODULOS * lado * mm / n - 2 * mm   # fuera de la zona blanca
            c.setFont("Helvetica-Bold", 11)
            c.drawCentredString(cx, zy - 6 * mm, f"Visor {ident}")
            c.setFont("Helvetica", 7)
            c.drawCentredString(cx, zy - 10 * mm, texto)
        barra_100mm(c, (W - 100 * mm) / 2, 22 * mm)
        pie(c, "Recortar por la línea discontinua y pegar en tarjeta rígida. Medir la distancia del centro del QR a los ojos.")
        c.showPage()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fijo", type=int, default=2, help="cuántos QR fijos (uno por hoja)")
    ap.add_argument("--lado-fijo", type=int, default=150, help="lado del cuadrado negro [mm] (máx. ~170 en A4)")
    ap.add_argument("--visor", type=int, default=4, help="cuántos QR de visor")
    ap.add_argument("--lado-visor", type=int, default=100, help="lado del cuadrado negro [mm]")
    ap.add_argument("-o", "--salida", default="docs/qr/qr_calibracion.pdf")
    a = ap.parse_args()
    if a.lado_fijo > 170:
        raise SystemExit("El QR fijo no cabe en A4 con su zona blanca por encima de ~170 mm.")
    import os
    os.makedirs(os.path.dirname(a.salida) or ".", exist_ok=True)
    c = canvas.Canvas(a.salida, pagesize=A4)
    c.setTitle("QR de calibración - Laboratorio digital")
    portada(c, a)
    c.showPage()
    for i in range(1, a.fijo + 1):
        hoja_fijo(c, i, a.lado_fijo)
        c.showPage()
    if a.visor:
        hojas_visor(c, list(range(1, a.visor + 1)), a.lado_visor)
    c.save()
    print("PDF:", a.salida)


if __name__ == "__main__":
    main()
