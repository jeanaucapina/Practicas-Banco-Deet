#!/bin/sh
# Sirve el tablero 3D (de /srv/web_local si hay un build local; si no, el de la
# imagen) y reenvia el WebSocket a la pasarela.
RAIZ=/srv/tablero3d
if [ -s /srv/web_local/index.html ]; then
  RAIZ=/srv/web_local
fi
echo "tablero 3D desde $RAIZ -> pasarela ${PASARELA:-172.30.99.1:7170}"
exec python3 /servir.py --web "$RAIZ" 8091 "${PASARELA:-172.30.99.1:7170}"
