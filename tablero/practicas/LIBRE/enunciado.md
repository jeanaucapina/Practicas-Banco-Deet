# Laboratorio libre: arma y prueba tu propia topología

Aquí no hay guía ni autocorrector: es **tu banco**. «Preparar el tablero» lo deja limpio (sin cables, PLC de fábrica, todo con corriente) y tú decides qué armar.

## Qué puedes hacer

- **Redes:** enchufa los RJ45 de los PLC y del PC a los switches de cada tablero (cada switch es su propia red; para unir los dos tableros, un latiguillo entre sus puertos 4). Mira el tráfico en Wireshark (`.\lab.ps1 wireshark`) y prueba `ping`, `mbpoll`, `nmap`… desde el PC del banco.
- **Programar los PLC:** sube tus `.ino` (Controllino y ESP32 PLC) con «Subir», o una escalera con OpenPLC.
- **Módulos y medidas:** el **potenciómetro** (sirve igual para el Controllino, a 24 V y A0, que para el ESP32, a 5 V, GND e I0.7), el DHT11, los dos pulsadores, el motor, el LED y el foco de 24 V. Mide con el **multímetro** (rojo y negro) la tensión del cursor, la de los relés o la de una salida.
- **Servidores propios:** levanta con `docker compose` lo que quieras en el segmento `tab_lan` (192.168.1.0/24), o los de otras prácticas (Node-RED, ChirpStack, Odoo, OPC UA…) desde sus carpetas en `~/trabajo`.
- **Dos tableros:** RS-485 entre los Controllino (A con A, B con B), Modbus TCP, MQTT, LoRa…

## Reglas del 3D

- Un borne de **señal** (I0.7, Q0.2, A0…) admite **un solo hilo**; los de **alimentación** (5V, GND, +24V, 0V) admiten varios apilados.
- Si desenchufas un hilo de un módulo, **el terminal no desaparece**: queda colgando y lo puedes volver a enchufar donde quieras.
- Pulsadores: clic = pulso de ~0,8 s; **Shift+clic** los deja enclavados hasta el siguiente clic.
- Nada de lo que hagas aquí se evalúa ni toca la planta física.
