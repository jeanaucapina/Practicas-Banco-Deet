#!/usr/bin/env bash
# Tablero de comunicaciones simulado: arranque y utilidades.
#
#   ./tablero.sh arrancar          equipos Docker + pasarela para las gafas
#   ./tablero.sh parar             apaga todo (los cables quedan guardados)
#   ./tablero.sh estado            contenedores, enlaces y ultimo registro
#   ./tablero.sh capturar [iface]  pcap en vivo a Wireshark (tab-lan por defecto)
#   ./tablero.sh descablear        borra el cableado guardado
#   ./tablero.sh otlab             enchufa los contenedores de ot-lab a la LAN
#                                  de los tableros (192.168.1.200+)
#   ./tablero.sh otlab-quitar      los vuelve a desenchufar
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p run

pid_pasarela() { pgrep -f "^python3 pasarela/pasarela.py" || true; }

case "${1:-}" in
  arrancar)
    docker compose up -d
    if [[ -n "$(pid_pasarela)" ]]; then
      echo "La pasarela ya estaba corriendo (pid $(pid_pasarela))."
    else
      setsid python3 pasarela/pasarela.py > run/pasarela.log 2>&1 < /dev/null &
      sleep 1.5
      echo "Pasarela arrancada. Registro: tablero/run/pasarela.log"
    fi
    IP=$(hostname -I | awk '{print $1}')
    echo
    echo "  Escritorio: godot4 --xr-mode off --path $(cd ../godot && pwd) res://scenes/TableroLab.tscn"
    echo "  Gafas:      abren TableroLab y encuentran la pasarela solas (o --pasarela=$IP)"
    echo "  Wireshark:  wireshark -k -i tab-lan      (RS-485: -i tab-485, Decode As udp 4850-4859 -> mbrtu)"
    echo "              sin permisos: ./tablero.sh capturar tab-lan | wireshark -k -i -"
    echo "  QModMaster: puerto serie $(pwd)/run/ttyTAB485"
    echo "  Modbus TCP: Controllino 192.168.1.1n:502 (RTU n) · ESP32 PLC 192.168.1.10 (T1) / .20 (T2) · PC .100"
    echo "  MQTT:       broker 192.168.1.50:1883  (mosquitto_sub -h 192.168.1.50 -t 'tablero+/#' -v)"
    ;;
  parar)
    P=$(pid_pasarela); [[ -n "$P" ]] && kill $P && echo "pasarela parada"
    docker compose down
    ;;
  estado)
    docker compose ps --format '{{.Name}}\t{{.Status}}'
    for c in tab1-controllino tab1-esp32plc tab2-controllino tab2-esp32plc; do
      printf '%-16s redes: %s\n' "$c" "$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}={{$v.IPAddress}} {{end}}' $c 2>/dev/null)"
    done
    P=$(pid_pasarela); echo "pasarela: ${P:-parada}"
    [[ -f run/pasarela.log ]] && tail -5 run/pasarela.log
    ;;
  capturar)
    exec herramientas/capturar.sh "${2:-tab-lan}" "${3:--}"
    ;;
  otlab|otlab-quitar)
    # ot-lab (github.com/Pbarbecho/ot-lab) vive en 172.28.0.0/24; aqui se le
    # da ademas una pata en tab_lan para que su SCADA/PLC/Node-RED hablen con
    # los Controllino (192.168.1.1n) y el broker de los tableros (.50).
    # Convivencia automatica: los puertos no chocan (nuestro Node-RED 1890, FUXA 1891) y la
    # pasarela los enchufa sola; esto lo hace al momento, y otlab-quitar lo desactiva.
    if [[ "$1" == otlab ]]; then rm -f run/otlab_no; else touch run/otlab_no; fi
    for par in openplc:200 ignition:201 fuxa:202 node-red:203 mosquitto:204 \
               modbus-sim:205 opcua-py:206 opc-plc:207 conpot:208; do
      c=${par%%:*}; ip=192.168.1.${par##*:}
      docker inspect "$c" >/dev/null 2>&1 || continue
      if [[ "$1" == otlab ]]; then
        docker network connect --ip "$ip" tab_lan "$c" 2>/dev/null && echo "  $c -> $ip" \
          || echo "  $c ya estaba en tab_lan"
      else
        docker network disconnect -f tab_lan "$c" 2>/dev/null && echo "  $c fuera de tab_lan"
      fi
    done
    ;;
  descablear)
    rm -f run/cableado.json && echo "cableado borrado (reinicia la pasarela)"
    ;;
  *)
    sed -n '2,12p' "$0"; exit 1 ;;
esac
