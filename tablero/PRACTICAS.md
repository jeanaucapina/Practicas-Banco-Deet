# Prácticas adicionales del tablero

Complementan la **Práctica 1** (Modbus entre dos tableros) de [README.md](README.md). Todas usan solo direcciones, temas y IP documentados en ese README (mapa Modbus y MQTT). Sin probar en el laboratorio aún: al ejecutarlas, corregir aquí lo que difiera.

Requisitos: `./tablero.sh arrancar`, Wireshark (`./tablero.sh capturar tab-lan | wireshark -k -i -`) y, para la P4, ot-lab (`./tablero.sh otlab`).

---

## P2 — Diagnóstico de un bus RS-485

**Objetivo:** reconocer por la captura los fallos típicos de un bus serie.

1. Cablea el RS-485 de C1 a C2 (banana **A con A**, **B con B**) y pon C1 en **MAESTRO 485** (Holding 0 = 3).
2. Captura `tab-485` (`./tablero.sh capturar tab-485 bus.pcap`); en Wireshark: *Decode As… → UDP 4850 → Modbus RTU*.
3. Anota una petición y su respuesta: dirección del esclavo, función, CRC.
4. Provoca cada fallo y anota **qué ves en la captura** y **qué contadores cambian** en C1 (Holding 4 = OK, Holding 5 = sin respuesta):

| Fallo | Cómo provocarlo | Qué debe verse |
|---|---|---|
| A y B cruzados | intercambia las bananas | peticiones del maestro sin respuesta (el esclavo recibe los bits invertidos) |
| Esclavo caído | interruptor de energía del Controllino 2 | peticiones sin respuesta, Holding 5 sube |
| Bus abierto | quita una banana | ídem |
| Dirección errónea | cambia Holding 3 (esclavo remoto) a una inexistente | peticiones sin respuesta, sin CRC malo |

**Entregable:** tabla rellena con capturas de cada caso.

## P3 — MQTT con el ESP32 PLC

**Objetivo:** ver el patrón publicar/suscribir y mandar órdenes a una salida.

1. Enchufa el ESP32 PLC del tablero 1 al switch y al broker (`192.168.10.50`).
2. Desde el PC: `mosquitto_sub -h 192.168.10.50 -t 'tablero1/#' -v` (verás `tablero1/esp32plc/estado` cada segundo y `tablero1/controllino/estado` al cambiar algo o cada 2 s).
3. Publica `mosquitto_pub -h 192.168.10.50 -t tablero1/esp32plc/set/Q0.0 -m 1` (y `0`). Comprueba el LED/Q0.0 en el tablero y en Modbus (bobina 0 del ESP32, `192.168.10.21:502`).
4. Pulsa I16 en el Controllino y observa cómo cambia `tablero1/controllino/estado`.
5. Apaga el ESP32 PLC (interruptor): ¿qué pasa con el tema `estado`? ¿Cuánto tarda el suscriptor en notarlo? Discute por qué MQTT necesita *last will* para detectarlo.

**Entregable:** captura de Wireshark con CONNECT, SUBSCRIBE y PUBLISH identificados.

## P4 — SCADA sobre el tablero (OpenPLC / Ignition / FUXA)

**Objetivo:** que un SCADA/PLC externo lea y escriba el Controllino por Modbus TCP.

1. `./tablero.sh otlab` (los contenedores de ot-lab quedan en `192.168.10.100–108`).
2. En FUXA o Ignition da de alta un dispositivo Modbus TCP: `192.168.10.11:502`, esclavo 1.
3. Mapea: bobinas 0–23 (D0–D23), discretas 16–18 (I16–I18), registros de entrada 0–15 (A0–A15).
4. Haz un panel que muestre I16–I18 y un botón que active D0.
5. En OpenPLC (`192.168.10.100`) programa en ladder: *si I16 y I17 entonces D6*. Configura el driver Modbus maestro apuntando a `192.168.10.11`.
6. Observa en Wireshark quién es cliente y quién servidor, y el intervalo de sondeo.

Esta práctica es la vía recomendada para "programar el Controllino" mientras no exista la integración arduino-cli + simavr (ver *Pendiente* en el README).

## P5 — Módulos analógicos y digitales

**Objetivo:** cablear sensores a los bornes del bloque MÓDULOS y leerlos por Modbus/MQTT.

1. Enchufa el **potenciómetro** a `AI-1` y el **DHT11** (hilos `T` y `H`) a `AI-2` y `AI-3`.
2. Lee los registros de entrada del ESP32 PLC (entradas analógicas 1–3) con QModMaster.
3. Mueve el potenciómetro (11 topes, 0–100 %) y grafica registro vs. posición: ¿es lineal? ¿resolución?
4. Enchufa un pulsador extra a `DI-1` y comprueba I0.1; enchufa el **motor** a `Q-1` y activa la bobina 0 por Modbus.
5. Quita un cable y comprueba que el valor deja de llegar (el módulo "sin cablear" no manda nada).

Recuerda: estos cables no pasan por Docker ni Wireshark; solo el tráfico Modbus/MQTT resultante.
