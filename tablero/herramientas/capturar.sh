#!/usr/bin/env bash
# Captura del tablero sin permisos de Wireshark.
#
#   ./capturar.sh tab-lan                  -> pcap por stdout
#   ./capturar.sh tab-lan | wireshark -k -i -          (en este PC)
#   ./capturar.sh tab-485 captura.pcap                 (a fichero)
#
# Desde OTRO PC (la "compu externa" del laboratorio):
#   ssh usuario@pc-del-tablero ros2_godot_robot_starter/tablero/herramientas/capturar.sh tab-lan \
#     | wireshark -k -i -
#
# Interfaces: tab-lan (switch y WiFi del laboratorio), tab-485 (bus RS-485).
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
IFACE="${1:-tab-lan}"
DEST="${2:--}"
if [[ "$DEST" != "-" ]]; then
  DIR="$(cd "$(dirname "$DEST")" && pwd)"; F="$(basename "$DEST")"
  exec docker run --rm --network host --cap-add NET_RAW --cap-add NET_ADMIN \
    -v "$AQUI:/h:ro" -v "$DIR:/o" python:3.12-slim python -u /h/sniffer.py "$IFACE" "/o/$F"
fi
exec docker run --rm -i --network host --cap-add NET_RAW --cap-add NET_ADMIN \
  -v "$AQUI:/h:ro" python:3.12-slim python -u /h/sniffer.py "$IFACE" -
