"""Taller U6 - Parte II: frescura de nivel de aplicacion (Ec. U6.1) contra el replay de un
mando. Un mando es {reg, val, seq, ts}: seq es un contador monotono por registro y ts es
epoch en ms. Se acepta solo si el contador crece de verdad Y la marca de tiempo esta dentro
de la ventana DELTA. Mapea a SR 3.1 (integridad de la comunicacion) y SR 3.8 (integridad
de la sesion: rechazo de repeticiones) de la IEC 62443-3-3.

Es logica pura y sin red: la usa el nodo de Node-RED (funcion_frescura_nodered.js, misma
regla) y la prueba revisar_frescura.py. No hay nada que atacar aqui; es la defensa.
"""
DELTA_MS = 5000


def aceptar(estado: dict, mando: dict, ahora_ms: int, delta_ms: int = DELTA_MS):
    """estado: {reg: ultimo_seq_aceptado}. Devuelve (ok, motivo). Si ok, ACTUALIZA estado."""
    try:
        reg = int(mando["reg"])
        seq = int(mando["seq"])
        ts = int(mando["ts"])
    except (KeyError, TypeError, ValueError):
        return False, "mando mal formado"
    visto = estado.get(reg, 0)
    if seq <= visto:                                   # repeticion o trama vieja reinyectada
        return False, "REPLAY descartado: seq %d <= ultimo visto %d en reg %d" % (seq, visto, reg)
    if abs(ahora_ms - ts) > delta_ms:                  # fuera de la ventana de frescura
        return False, "CADUCADO descartado: dt %d ms > DELTA %d" % (ahora_ms - ts, delta_ms)
    estado[reg] = seq                                  # se acepta y se recuerda
    return True, "aceptado: reg %d val %s seq %d" % (reg, mando.get("val"), seq)
