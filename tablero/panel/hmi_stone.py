"""HMI STONE STWC050WT-01 virtual (5", 800x480, RS-232) para la practica L2.

El alumno DISENA la pantalla en el diseñador web (como en STONE Designer: paginas
y widgets con NOMBRE -label1, spin_box1, slider1, chart_view1/line_series1...-) y
PROGRAMA el Controllino para hablar con ella por Serial2 a 115 200 8N1, con las
librerias del banco (Stone_HMI_Define.h / Procesar_HMI.h) o a mano. La pantalla
vive aqui, en el panel; los bytes de Serial2 viajan en datagramas UDP entre el
Controllino (172.30.99.1n:5300) y este modulo (172.30.99.6:5300+n, uno por tablero).

Protocolo (juego de instrucciones JSON de STONE):

  MCU -> HMI   texto ASCII:  ST<{"cmd_code":"...", "type":"...", "widget":"...", ...}>ET
     set_text   {"type":"label"|"edit", "widget", "text"}
     set_value  {"type":"label", "widget", "value", ["format":"%.2f"]}
                {"type":"slider"|"spin_box"|"progress_bar"|"switch", "widget", "value"}
                {"type":"line_series", "widget", "mode":"push", "value"}   (añade un punto)
     get_value  {"type", "widget"}              la HMI responde con el valor (abajo)
     open_win   {"widget": "<pagina>"}          cambia de pagina
     clear      {"type":"line_series", "widget"}

  HMI -> MCU   binario:  'ST<' CMD(2) LEN(2) DATOS(LEN) '>ET' CRC16(2)
     DATOS = nombre del widget (ASCII) + ':' + valor (int32, big endian)
     CMD   0x1001 button   0x1010 switch   0x1040 slider   0x1062 spin_box
           0x1070 edit (el valor es el texto en ASCII)   0x1080 get_value (respuesta)
     CRC16 Modbus (0xA001, inicial 0xFFFF) sobre todo lo anterior, byte bajo primero.

  La documentacion publica de STONE describe el formato (cabecera, comando, longitud,
  datos, cola y CRC) pero no todos los codigos de comando por widget: los de arriba
  son los del banco y estan en Stone_HMI_Define.h.
"""

import json
import os
import re
import socket
import threading
import time
from collections import deque

IPS_CONTROLLINO = {1: "172.30.99.11", 2: "172.30.99.12"}
PUERTO_CONTROLLINO = 5300
ANCHO, ALTO = 800, 480
TIPOS = ("label", "button", "switch", "slider", "spin_box", "progress_bar", "edit", "chart_view", "image")
CMD = {"button": 0x1001, "switch": 0x1010, "slider": 0x1040, "spin_box": 0x1062, "edit": 0x1070}
CMD_RESPUESTA = 0x1080
TRAMA_JSON = re.compile(rb"ST<(\{.*?\})>ET", re.S)


def crc16(b: bytes) -> int:
    crc = 0xFFFF
    for x in b:
        crc ^= x
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def trama_evento(cmd: int, nombre: str, valor) -> bytes:
    if isinstance(valor, str):
        dato = nombre.encode() + b":" + valor.encode("ascii", "replace")
    else:
        dato = nombre.encode() + b":" + (int(valor) & 0xFFFFFFFF).to_bytes(4, "big")
    t = b"ST<" + cmd.to_bytes(2, "big") + len(dato).to_bytes(2, "big") + dato + b">ET"
    c = crc16(t)
    return t + bytes([c & 0xFF, c >> 8])


def _num(x, defecto=0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return defecto


def limpiar_proyecto(p) -> dict:
    """Valida y normaliza un proyecto venido del navegador (no se fia de nada)."""
    if not isinstance(p, dict):
        raise ValueError("proyecto no válido")
    paginas = []
    for pg in (p.get("paginas") or [])[:12]:
        ws = []
        for w in (pg.get("widgets") or [])[:150]:
            t = str(w.get("tipo", ""))
            if t not in TIPOS:
                continue
            nombre = re.sub(r"[^A-Za-z0-9_]", "", str(w.get("nombre") or "%s%d" % (t, len(ws) + 1)))[:24]
            d = {
                "nombre": nombre or "%s%d" % (t, len(ws) + 1), "tipo": t,
                "x": max(0, min(int(_num(w.get("x"))), ANCHO)), "y": max(0, min(int(_num(w.get("y"))), ALTO)),
                "w": max(8, min(int(_num(w.get("w"), 120)), ANCHO)), "h": max(8, min(int(_num(w.get("h"), 40)), ALTO)),
                "texto": str(w.get("texto", ""))[:80],
                "fuente": max(8, min(int(_num(w.get("fuente"), 20)), 80)),
                "min": _num(w.get("min"), 0), "max": _num(w.get("max"), 100), "paso": _num(w.get("paso"), 1) or 1,
                "vertical": bool(w.get("vertical", False)),
                "color": str(w.get("color", ""))[:9],
                "pagina_destino": str(w.get("pagina_destino", ""))[:30],
            }
            if t == "chart_view":
                series = []
                for s in (w.get("series") or [])[:4]:
                    series.append({"nombre": re.sub(r"[^A-Za-z0-9_]", "", str(s.get("nombre", "")))[:24] or "line_series%d" % (len(series) + 1),
                                   "color": str(s.get("color", "#2f62b0"))[:9],
                                   "min": _num(s.get("min"), 0), "max": _num(s.get("max"), 100)})
                d["series"] = series or [{"nombre": "line_series1", "color": "#2f62b0", "min": 0, "max": 100}]
                d["capacidad"] = max(10, min(int(_num(w.get("capacidad"), 100)), 500))
            ws.append(d)
        nombre_pg = re.sub(r"[^A-Za-z0-9_]", "", str(pg.get("nombre", "")))[:30] or ("home_page" if not paginas else "page%d" % (len(paginas) + 1))
        paginas.append({"nombre": nombre_pg, "widgets": ws})
    if not paginas:
        paginas = [{"nombre": "home_page", "widgets": []}]
    return {"nombre": str(p.get("nombre", "proyecto"))[:40], "modelo": "STWC050WT-01",
            "ancho": ANCHO, "alto": ALTO, "baudios": 115200, "paginas": paginas}


class HMI:
    def __init__(self, n: int, carpeta: str):
        self.n = n
        self.ruta = os.path.join(carpeta, "hmi_t%d.json" % n)
        self.proyecto = None
        self.valores = {}                 # nombre -> numero (slider, spin_box, switch, progress_bar, label numerico)
        self.textos = {}                  # nombre -> texto (label, edit)
        self.series = {}                  # nombre de line_series -> [valores]
        self.pagina = 0
        self.log = deque(maxlen=40)       # tramas: {"t", "dir", "hex"/"txt"}
        self.rx_total = self.tx_total = 0
        self.tramas_mcu = 0
        self._buf = b""
        self._cerrojo = threading.Lock()
        self._sock = None
        self._cargar_de_disco()

    # ── Proyecto ────────────────────────────────────────────────────────────
    def cargar(self, p: dict, guardar=True):
        p = limpiar_proyecto(p)
        with self._cerrojo:
            self.proyecto, self.pagina = p, 0
            self.valores.clear()
            self.textos.clear()
            self.series.clear()
            for pg in p["paginas"]:
                for w in pg["widgets"]:
                    if w["tipo"] in ("label", "edit", "button"):
                        self.textos[w["nombre"]] = w["texto"]
                    elif w["tipo"] in ("slider", "spin_box", "progress_bar", "switch"):
                        self.valores[w["nombre"]] = w["min"] if w["tipo"] != "switch" else 0
                    elif w["tipo"] == "chart_view":
                        for s in w["series"]:
                            self.series[s["nombre"]] = []
        if guardar:
            try:
                os.makedirs(os.path.dirname(self.ruta), exist_ok=True)
                with open(self.ruta, "w", encoding="utf-8") as f:
                    json.dump(p, f, ensure_ascii=False)
            except OSError:
                pass

    def _cargar_de_disco(self):
        try:
            with open(self.ruta, encoding="utf-8") as f:
                self.cargar(json.load(f), guardar=False)
        except (OSError, ValueError, KeyError):
            pass

    def _buscar(self, nombre: str):
        for pg in (self.proyecto or {}).get("paginas", []):
            for w in pg["widgets"]:
                if w["nombre"] == nombre:
                    return w
        return None

    def _capacidad(self, serie: str) -> int:
        for pg in (self.proyecto or {}).get("paginas", []):
            for w in pg["widgets"]:
                if w["tipo"] == "chart_view" and any(s["nombre"] == serie for s in w["series"]):
                    return w["capacidad"]
        return 100

    # ── Serie ───────────────────────────────────────────────────────────────
    def iniciar(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("0.0.0.0", PUERTO_CONTROLLINO + self.n))
        s.settimeout(1.0)
        self._sock = s
        threading.Thread(target=self._escuchar, daemon=True).start()

    def _escuchar(self):
        while True:
            try:
                datos, _ = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                time.sleep(1)
                continue
            self.rx_total += len(datos)
            self._buf += datos
            self._procesar()

    def _procesar(self):
        """Saca las ordenes JSON completas del buffer (ST<{...}>ET)."""
        while True:
            m = TRAMA_JSON.search(self._buf)
            if not m:
                # Basura antes de una cabecera (o ruido): se conserva desde el ultimo "ST<".
                i = self._buf.rfind(b"ST<")
                self._buf = self._buf[i:] if i >= 0 else self._buf[-2:]
                if len(self._buf) > 4096:
                    self._buf = b""
                return
            self._anotar("MCU→HMI", txt=m.group(0).decode("utf-8", "replace"))
            self._buf = self._buf[m.end():]
            try:
                orden = json.loads(m.group(1))
            except ValueError:
                self._anotar("HMI", txt="JSON mal formado: se ignora")
                continue
            self.tramas_mcu += 1
            self._orden_mcu(orden)

    def _anotar(self, sentido, b: bytes = b"", txt: str = ""):
        self.log.append({"t": time.strftime("%H:%M:%S"), "dir": sentido,
                         "hex": b.hex(" ").upper() if b else "", "txt": txt})

    def _enviar(self, b: bytes):
        self._anotar("HMI→MCU", b)
        self.tx_total += len(b)
        if self._sock:
            try:
                self._sock.sendto(b, (IPS_CONTROLLINO[self.n], PUERTO_CONTROLLINO))
            except OSError:
                pass

    def _orden_mcu(self, o: dict):
        cmd, w = str(o.get("cmd_code", "")), str(o.get("widget", ""))
        tipo = str(o.get("type", ""))
        with self._cerrojo:
            if cmd == "set_text":
                self.textos[w] = str(o.get("text", ""))[:120]
            elif cmd == "set_value":
                v = _num(o.get("value"))
                if tipo == "line_series":
                    serie = self.series.setdefault(w, [])
                    serie.append(v)
                    del serie[:-self._capacidad(w)]
                elif tipo == "label":
                    fmt = str(o.get("format", "%g"))
                    try:
                        self.textos[w] = fmt % v
                    except (TypeError, ValueError):
                        self.textos[w] = str(v)
                else:
                    self.valores[w] = v
            elif cmd == "clear" and tipo == "line_series":
                self.series[w] = []
            elif cmd == "open_win":
                for i, pg in enumerate((self.proyecto or {}).get("paginas", [])):
                    if pg["nombre"] == w:
                        self.pagina = i
            elif cmd == "get_value":
                wd = self._buscar(w)
                if wd is not None:
                    if wd["tipo"] in ("label", "edit"):
                        self._enviar(trama_evento(CMD_RESPUESTA, w, self.textos.get(w, "")))
                    else:
                        self._enviar(trama_evento(CMD_RESPUESTA, w, self.valores.get(w, 0)))

    # ── Toque ───────────────────────────────────────────────────────────────
    def toque(self, nombre: str, ev: str, v=None):
        """ev: 'down' | 'up' (botones) | 'set' (slider, spin_box, edit, con v)."""
        with self._cerrojo:
            w = self._buscar(nombre)
            if w is None:
                return False
            t = w["tipo"]
            if t == "button":
                if w["pagina_destino"] and ev == "down":
                    for i, pg in enumerate(self.proyecto["paginas"]):
                        if pg["nombre"] == w["pagina_destino"]:
                            self.pagina = i
                if ev in ("down", "up"):
                    self._enviar(trama_evento(CMD["button"], nombre, 1 if ev == "down" else 0))
            elif t == "switch" and ev == "down":
                nuevo = 0 if self.valores.get(nombre, 0) else 1
                self.valores[nombre] = nuevo
                self._enviar(trama_evento(CMD["switch"], nombre, nuevo))
            elif t in ("slider", "spin_box") and ev == "set" and v is not None:
                x = max(w["min"], min(float(v), w["max"]))
                if t == "spin_box":
                    x = round(x / w["paso"]) * w["paso"]
                self.valores[nombre] = x
                self._enviar(trama_evento(CMD[t], nombre, int(round(x))))
            elif t == "edit" and ev == "set" and v is not None:
                self.textos[nombre] = str(v)[:60]
                self._enviar(trama_evento(CMD["edit"], nombre, str(v)[:60]))
        return True

    # ── Estado para el navegador ────────────────────────────────────────────
    def estado(self):
        with self._cerrojo:
            return {
                "n": self.n, "pagina": self.pagina, "proyecto": self.proyecto,
                "valores": dict(self.valores), "textos": dict(self.textos),
                "series": {k: list(v) for k, v in self.series.items()},
                "log": list(self.log), "rx": self.rx_total, "tx": self.tx_total, "tramas_mcu": self.tramas_mcu,
            }
