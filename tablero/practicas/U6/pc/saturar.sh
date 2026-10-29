#!/bin/sh
# Taller U6 - Parte III (Listado U6.6): SATURACION del segmento, SOLO el de TU banco y
# acotada en el tiempo (etica: minima intensidad y duracion). Mide el tiempo de ciclo con
# operador_ciclo.py EN PARALELO, en otra terminal.
#
#   sh saturar.sh 25     # 25 % de 100 Mbit/s durante 30 s
#   sh saturar.sh 100    # peor caso
#   sh saturar.sh 0      # parar
#
# En el banco virtual un flood no "ocupa el medio" de los demas (Docker enruta por host),
# asi que la saturacion se modela en el banco: el nivel de carga degrada el tiempo de ciclo
# del PLC como lo haria un micro cuya pila de red compite con el lazo. El efecto es REAL y
# medible con operador_ciclo.py. Se pide por el panel del banco (172.30.99.6:8090 desde el PC); si tambien
# quieres trafico visible en Wireshark, lanza ademas iperf3 (hay iperf3 en este PC):
#     iperf3 -s &                      # en una terminal
#     iperf3 -c 192.168.1.100 -u -b 50M -t 30     # desde el atacante (192.168.1.101)
PCT="${1:-25}"
SEG="${2:-30}"
echo "Saturando el segmento al $PCT % durante $SEG s (acotado). Mide con: python3 operador_ciclo.py"
curl -s -X POST "http://172.30.99.6:8090/api/saturar?nivel=$PCT&seg=$SEG" && echo
echo "Para pararla antes: sh saturar.sh 0"
