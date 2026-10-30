#!/bin/sh
# Sirve el tablero 3D (de /srv/web_local si hay un build local; si no, el de la
# imagen) y reenvia el WebSocket a la pasarela.
RAIZ=/srv/tablero3d
if [ -s /srv/web_local/index.html ]; then
  RAIZ=/srv/web_local
fi
echo "tablero 3D desde $RAIZ -> pasarela ${PASARELA:-172.30.99.1:7170}"
TLS=""
if [ -s /certs/cert.pem ] && [ -s /certs/key.pem ]; then      # lab.ps1 compartir: HTTPS con certificado propio
  TLS="--cert /certs/cert.pem --key /certs/key.pem"
  echo "tablero 3D por HTTPS (certificado propio)"
fi
exec python3 /servir.py $TLS --web "$RAIZ" 8091 "${PASARELA:-172.30.99.1:7170}"
