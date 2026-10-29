#!/bin/sh
# Taller U6 - Parte I (Listado U6.1): reconocimiento del segmento, SOLO tu banco. Un escaneo
# de servicios industriales es en si una accion sensible; fuera del laboratorio aislado es un
# reconocimiento hostil. Aqui solo descubre el PLC victima (502) y el broker (1883/8883).
echo "== hosts vivos del segmento del banco =="
nmap -sn 192.168.1.0/24

echo "== puertos industriales del PLC y del broker =="
nmap -p 502,1883,8883 192.168.1.10 192.168.1.52
# 502  abierto -> servidor Modbus TCP (Practica L7)
# 1883 abierto -> broker MQTT en claro (Practica L9) | cerrado -> ya endurecido
# 8883 abierto -> broker con TLS (Parte IV de este taller)
