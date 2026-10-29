"""Autocorrector de practicas: ejecuta los pasos de `practicas/<id>/practica.json`
contra el banco (pulsa pulsadores, mira salidas, monitor serie y MQTT) y dice
que paso falla y por que.

Es de la biblioteca estandar y no sabe de Docker ni de la pasarela: el panel le
da un `Contexto` con cuatro funciones. Asi se puede probar sin banco.

Pasos (`hacer` es una lista de acciones, en orden; el paso pasa si todas pasan):

  {"tipo": "pulsar",   "equipo", "i", "ms"}      pulsa y suelta la entrada i
  {"tipo": "entrada",  "equipo", "i", "v"}       pone la entrada i a 0/1 (y la deja)
  {"tipo": "analogica", "equipo", "i", "v"}      pone la entrada analogica i (0-1023)
  {"tipo": "esperar",  "equipo", "do"|"rele"|"di"|"ai": {indice: valor | [min, max]},
                       "max_ms"}                 hasta que se cumpla (si no, falla)
  {"tipo": "mantener", "equipo", <igual>, "ms"}  tiene que cumplirse TODO ese tiempo
  {"tipo": "nunca",    "equipo", <igual>, "ms"}  esas condiciones no se dan TODAS a la vez
                                                 en ningun momento de ese tiempo (invariante)
  {"tipo": "serie",    "equipo", "regex", "max_ms"}   aparece en el monitor serie
  {"tipo": "mqtt",     "tema", "carga", "max_ms", ["reciente": s]}   llega un mensaje (regex); con
                       "reciente" vale tambien el ultimo de cada tema de esos s (envios cada 10 min)
  {"tipo": "pausa",    "ms"}
  {"tipo": "energia",  "id": "t1.esp32plc", "v": false}   interruptor de energia del tablero
  {"tipo": "estado",   "equipo", "clave": "epc.conectado", "valor" | "regex", "max_ms"}   un dato del estado
  {"tipo": "docker", "args": ["exec", "l5-sw2", "tc", ...], "regex", "max_ms"}   en el Docker del alumno
  {"tipo": "pc", "cmd", "regex", ["no": true], "max_ms"}   orden en el PC del banco (192.168.1.100,
                       bash): su salida tiene que casar con la regex (o NO casar, con "no")
  {"tipo": "lora_trama", "equipo", "plc"}   el ultimo ascendente LoRaWAN del nodo es la trama de 9 B
                       de la guia L10 (VER=1) y TEMP/NIV/alarmas son las del PLC (A0, A1)
  {"tipo": "hmi_widget", "n", "nombre", ["ctl": "spin_box"]}   la HMI STONE tiene ese widget
  {"tipo": "hmi_tocar",  "n", "nombre", ["ev": "pulsar"|"set"|"down"], ["v"]}  lo toca (set = valor)
  {"tipo": "hmi_var",    "n", "nombre", "valor"|[min,max] | "texto": regex, "max_ms"}   lo que muestra
  {"tipo": "hmi_serie",  "n", "nombre", ["min": puntos], ["valor": [min,max]], "max_ms"}   line_series

Los margenes son holgados a proposito: el estado llega a 10 Hz, un pulso corto no
cuenta (800 ms como en el 3D) y OpenPLC sondea cada 100 ms.
"""

import re
import time

CAMPOS = ("do", "rele", "di", "ai", "s24")
PAUSA_TRAS_PULSAR = 0.8


class Contexto:
    """Lo que el verificador necesita del banco. El panel lo implementa."""

    def equipo(self, nombre: str) -> dict:           # estado del equipo (do, rele, di, ai, modo...)
        raise NotImplementedError

    def orden(self, nombre: str, orden: dict) -> None:
        raise NotImplementedError

    def serie(self, nombre: str) -> str:             # ultimas lineas del monitor serie
        raise NotImplementedError

    def mqtt(self) -> list:                          # [{"tema", "carga"}]
        raise NotImplementedError

    def mqtt_ultimos(self) -> list:                  # [{"tema", "carga" entera, "t"}]: el ultimo por tema
        return []

    def hmi(self, n: int) -> dict:                   # estado de la HMI virtual (proyecto, vars, textos)
        raise NotImplementedError

    def hmi_toque(self, n: int, widget: str, ev: str, v=None) -> None:
        raise NotImplementedError

    def pc(self, cmd: str, timeout: float) -> str:       # salida (stdout+stderr) de la orden en el PC
        raise NotImplementedError

    def energia(self, id_: str, v: bool) -> None:        # interruptor de energia de un equipo
        raise NotImplementedError

    def docker(self, args: list, timeout: float) -> str:  # salida de «docker <args>» (contenedores del alumno)
        raise NotImplementedError


def _coincide(valor, esperado) -> bool:
    if isinstance(esperado, (list, tuple)) and len(esperado) == 2:
        return esperado[0] <= valor <= esperado[1]
    return valor == esperado


def fallos(estado: dict, accion: dict) -> list:
    """Condiciones de la accion que NO se cumplen ahora: [(texto)]."""
    malos = []
    for campo in CAMPOS:
        for idx, esp in (accion.get(campo) or {}).items():
            lista = estado.get(campo) or []
            i = int(idx)
            actual = lista[i] if i < len(lista) else None
            if actual is None or not _coincide(actual, esp):
                nombre = {"do": "D", "rele": "R", "di": "entrada ", "ai": "analógica A", "s24": "S_24v "}[campo] + str(i)
                malos.append("%s vale %s (se esperaba %s)" % (nombre, actual, esp))
    return malos


def _hacer(accion: dict, ctx: Contexto, dormir) -> str:
    """Ejecuta una accion. Devuelve "" si va bien o el motivo del fallo."""
    tipo = accion.get("tipo")
    eq = accion.get("equipo", "")
    if tipo == "pausa":
        dormir(accion.get("ms", 500) / 1000.0)
        return ""
    if tipo == "entrada":
        ctx.orden(eq, {"cmd": "entrada", "i": int(accion["i"]), "v": int(accion["v"])})
        return ""
    if tipo == "analogica":
        ctx.orden(eq, {"cmd": "analogica", "i": int(accion["i"]), "v": int(accion["v"])})
        return ""
    if tipo == "orden":
        # Orden cruda al equipo (p. ej. {"cmd": "modo", "v": 4}): para poner el banco en el
        # estado que pide una parte de la practica antes de comprobarla.
        ctx.orden(eq, dict(accion["orden"]))
        dormir(accion.get("ms", 300) / 1000.0)
        return ""
    if tipo == "pulsar":
        ctx.orden(eq, {"cmd": "entrada", "i": int(accion["i"]), "v": 1})
        dormir(accion.get("ms", 900) / 1000.0)
        ctx.orden(eq, {"cmd": "entrada", "i": int(accion["i"]), "v": 0})
        dormir(PAUSA_TRAS_PULSAR)
        return ""
    if tipo == "esperar":
        t0 = time.time()
        limite = accion.get("max_ms", 2000) / 1000.0
        malos = fallos(ctx.equipo(eq), accion)
        while malos and time.time() - t0 < limite:
            dormir(0.1)
            malos = fallos(ctx.equipo(eq), accion)
        if not malos:
            return ""
        return "%s (tras %.1f s)" % ("; ".join(malos[:3]), limite)
    if tipo == "mantener":
        t0 = time.time()
        total = accion.get("ms", 1000) / 1000.0
        while time.time() - t0 < total:
            malos = fallos(ctx.equipo(eq), accion)
            if malos:
                return "%s (a los %.1f s)" % ("; ".join(malos[:3]), time.time() - t0)
            dormir(0.1)
        return ""
    if tipo == "nunca":
        t0 = time.time()
        total = accion.get("ms", 1000) / 1000.0
        while time.time() - t0 < total:
            if not fallos(ctx.equipo(eq), accion):
                return "se dio a la vez lo prohibido (a los %.1f s)" % (time.time() - t0)
            dormir(0.05)
        return ""
    if tipo == "serie":
        rx = re.compile(accion["regex"])
        t0 = time.time()
        limite = accion.get("max_ms", 2000) / 1000.0
        while not rx.search(ctx.serie(eq)):
            if time.time() - t0 > limite:
                return "no aparece «%s» en el monitor serie" % accion["regex"]
            dormir(0.2)
        return ""
    if tipo == "mqtt":
        tema, carga = re.compile(accion.get("tema", ".*")), re.compile(accion.get("carga", ".*"))
        t0 = time.time()
        limite = accion.get("max_ms", 5000) / 1000.0
        reciente = float(accion.get("reciente", 0))
        while True:
            msgs = ctx.mqtt()
            if reciente:
                msgs = msgs + [m for m in ctx.mqtt_ultimos() if time.time() - m.get("t", 0) <= reciente]
            if any(tema.search(m["tema"]) and carga.search(m["carga"]) for m in msgs):
                return ""
            if time.time() - t0 > limite:
                return "no llega ningún mensaje MQTT con tema «%s»" % accion.get("tema", ".*")
            dormir(0.3)
    if tipo == "estado":
        # Cualquier dato del estado del equipo por ruta con puntos ("epc.conectado").
        t0 = time.time()
        limite = accion.get("max_ms", 3000) / 1000.0
        while True:
            v = ctx.equipo(eq)
            for k in str(accion["clave"]).split("."):
                v = v.get(k) if isinstance(v, dict) else None
            if "regex" in accion:
                if v is not None and re.search(accion["regex"], str(v)):
                    return ""
            elif v is not None and _coincide(v, accion.get("valor")):
                return ""
            if time.time() - t0 > limite:
                return "%s de %s vale %s (se esperaba %s)" % (accion["clave"], eq, v,
                                                              accion.get("valor", accion.get("regex")))
            dormir(0.2)
    if tipo == "lora_trama":
        ult = (ctx.equipo(eq).get("lora") or {}).get("ultima") or {}
        h = str(ult.get("hex", ""))
        if not h:
            return "el nodo no ha enviado ningún ascendente todavía"
        if len(h) != 18:
            return "el último ascendente tiene %d B, no los 9 B de la trama (Fig. L10.4)" % (len(h) // 2)
        b = bytes.fromhex(h)
        if b[0] >> 4 != 1:
            return "byte 0: la versión (b7-b4) vale %d, no 1" % (b[0] >> 4)
        ai = ctx.equipo(accion.get("plc", "t1.controllino")).get("ai") or [0, 0]
        temp, niv = b[1] << 8 | b[2], b[3] << 8 | b[4]
        esp_t, esp_n = ai[0] * 1000 // 1023, ai[1] * 1000 // 1023
        if abs(temp - esp_t) > 3 or abs(niv - esp_n) > 3:
            return ("TEMP=%d y NIV=%d décimas, pero el PLC tiene A0=%d (%d) y A1=%d (%d): ¿movieron los "
                    "potenciómetros después del último envío?" % (temp, niv, ai[0], esp_t, ai[1], esp_n))
        a_t, a_n = b[0] >> 3 & 1, b[0] >> 2 & 1
        if a_t != (1 if not 50 <= temp <= 300 else 0) or a_n != (1 if not 200 <= niv <= 900 else 0):
            return "los bits de alarma (A_T=%d, A_N=%d) no casan con TEMP y NIV" % (a_t, a_n)
        return ""
    if tipo == "energia":
        ctx.energia(accion["id"], bool(accion.get("v")))
        return ""
    if tipo == "docker":
        rx = re.compile(accion.get("regex", "."))
        t0 = time.time()
        limite = accion.get("max_ms", 5000) / 1000.0
        while True:
            salida = ctx.docker([str(x) for x in accion["args"]], max(5.0, limite))
            if rx.search(salida):
                return ""
            if time.time() - t0 > limite:
                ultima = salida.strip().splitlines()[-1:] or ["(sin salida)"]
                return "«docker %s» no da «%s» (última línea: %s)" % (" ".join(accion["args"]), accion.get("regex"), ultima[0][:120])
            dormir(1.0)
    if tipo == "pc":
        rx = re.compile(accion.get("regex", "."))
        quiere = not accion.get("no", False)
        t0 = time.time()
        limite = accion.get("max_ms", 5000) / 1000.0
        while True:
            salida = ctx.pc(accion["cmd"], max(5.0, limite))
            if bool(rx.search(salida)) == quiere:
                return ""
            if time.time() - t0 > limite:
                ultima = salida.strip().splitlines()[-1:] or ["(sin salida)"]
                return "en el PC, «%s» %s «%s» (última línea: %s)" % (
                    accion["cmd"], "no da" if quiere else "da", accion.get("regex", "."), ultima[0][:120])
            dormir(1.0)
    if tipo in ("hmi_widget", "hmi_tocar", "hmi_var", "hmi_serie"):
        return _hmi(accion, ctx, dormir)
    return "acción desconocida: %s" % tipo


def _buscar_widget(proyecto, nombre, tipo=None):
    for pg in (proyecto or {}).get("paginas", []):
        for w in pg.get("widgets", []):
            if w.get("nombre") == nombre and (tipo is None or w.get("tipo") == tipo):
                return w
    return None


def _hmi(accion: dict, ctx: Contexto, dormir) -> str:
    """HMI STONE por NOMBRE de widget (label2, spin_box1, line_series2...)."""
    n, nombre, tipo = accion.get("n", 1), str(accion.get("nombre", "")), accion["tipo"]
    est = ctx.hmi(n)
    if tipo == "hmi_widget":
        if _buscar_widget(est.get("proyecto"), nombre, accion.get("ctl")) is None:
            return "la HMI del tablero %d no tiene el widget %s%s (¿la descargaste con «Descargar a la HMI»?)" % (
                n, nombre, " (%s)" % accion["ctl"] if accion.get("ctl") else "")
        return ""
    if tipo == "hmi_tocar":
        if _buscar_widget(est.get("proyecto"), nombre) is None:
            return "no hay ningún widget %s en la HMI" % nombre
        ev = accion.get("ev", "pulsar")
        if ev == "pulsar":
            ctx.hmi_toque(n, nombre, "down", None)
            dormir(accion.get("ms", 400) / 1000.0)
            ctx.hmi_toque(n, nombre, "up", None)
        else:
            ctx.hmi_toque(n, nombre, ev, accion.get("v"))
        dormir(PAUSA_TRAS_PULSAR)
        return ""
    t0 = time.time()
    limite = accion.get("max_ms", 3000) / 1000.0
    while True:
        est = ctx.hmi(n)
        if tipo == "hmi_serie":
            pts = (est.get("series") or {}).get(nombre, [])
            ok = len(pts) >= int(accion.get("min", 1))
            if ok and "valor" in accion:
                ok = _coincide(pts[-1], accion["valor"])
            if ok:
                return ""
            motivo = "la serie %s tiene %d puntos%s (se esperaban %s%s)" % (
                nombre, len(pts), ", el último %s" % pts[-1] if pts else "", accion.get("min", 1),
                " con el último en %s" % (accion["valor"],) if "valor" in accion else "")
        elif "texto" in accion:
            txt = str((est.get("textos") or {}).get(nombre, ""))
            if re.search(accion["texto"], txt):
                return ""
            motivo = "el texto de %s es «%s» (se esperaba algo como %s)" % (nombre, txt, accion["texto"])
        else:
            v = (est.get("valores") or {}).get(nombre)
            if v is not None and _coincide(v, accion.get("valor")):
                return ""
            motivo = "%s vale %s (se esperaba %s)" % (nombre, v, accion.get("valor"))
        if time.time() - t0 > limite:
            return "%s (tras %.1f s)" % (motivo, limite)
        dormir(0.2)


def correr(practica: dict, ctx: Contexto, al_paso=None, dormir=time.sleep) -> list:
    """Ejecuta todos los pasos. `al_paso(i, resultado)` se llama tras cada uno
    (y con resultado None antes de empezarlo) para ir mostrando el avance."""
    resultados = []
    for i, paso in enumerate(practica.get("verificacion", [])):
        if al_paso:
            al_paso(i, None)
        motivo = ""
        for accion in paso.get("hacer", []):
            motivo = _hacer(accion, ctx, dormir)
            if motivo:
                break
        r = {"txt": paso.get("txt", "paso %d" % (i + 1)), "ok": not motivo, "motivo": motivo}
        resultados.append(r)
        if al_paso:
            al_paso(i, r)
    return resultados
