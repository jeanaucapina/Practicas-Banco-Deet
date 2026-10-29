#!/usr/bin/env python3
"""websockify con `Cache-Control: no-cache`: el navegador revalida el 3D (index.pck, .wasm...)
en cada carga y, si no cambio, recibe un 304 sin bajarlo otra vez. Asi una actualizacion del
tablero 3D se ve sola, sin Ctrl+Shift+R. Mismos argumentos que websockify: --web DIR PUERTO DESTINO."""
from websockify import websocketproxy

_fin = websocketproxy.ProxyRequestHandler.end_headers


def end_headers(self):
    self.send_header("Cache-Control", "no-cache")
    _fin(self)


websocketproxy.ProxyRequestHandler.end_headers = end_headers
websocketproxy.websockify_init()
