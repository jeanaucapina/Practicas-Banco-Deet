# L6 · Modbus RTU maestro-esclavo sobre RS-485

Esclavo Modbus RTU en el **Controllino** (dirección 1, 19 200 8N1, mapa de ocho registros holding) con `ArduinoRS485` + `ArduinoModbus`, y maestro en el **ESP32 PLC 14** con `ModbusRTU.h` (modbus-esp8266). Después, diagnóstico con **QModMaster** y **mbpoll** por el convertidor USB-RS485 del PC. Sigue la guía (enlace arriba); aquí va lo propio del banco virtual.

## El bus en el banco virtual

- **Preparar el tablero** cablea A con A y B con B entre el Controllino (bananas A y B de la bandeja) y el ESP32 (bornes A/B de su frente), conecta el convertidor USB-RS485 del PC al mismo par y pone los dos USB de programación.
- El bus es **físico de verdad**:
  - cada byte tarda lo que manda su baudio;
  - `Serial.flush()` espera al último bit;
  - el silencio t3,5 cierra la trama.
  - Errores que se ven igual que en el real:
    - baudios o formato distintos, o A/B cruzados → la UART lee basura;
    - dos maestros a la vez → colisión.
  - Lo ves en Wireshark con «Abrir Wireshark en vivo» → *Bus RS-485*.
- **Parte I (Pasos 2–4)**: pon las dos terminaciones de 120 Ω de la bandeja «COMPONENTES Y MULTÍMETRO» (una entre A y B en cada extremo) y mide con el multímetro.
  - ≈ 60 Ω con las dos, ≈ 120 Ω si falta una, ≈ 40 Ω con tres.
  - Entre A o B y GND: decenas de kΩ (solo los transceptores).
  - La tensión de reposo V_AB: con la polarización de 560 Ω (A a 5V, B a GND), positiva y estable; sin ella, ~0.
- **Potenciómetro en A0** (Tabla L6.6): el módulo *potenciómetro* con su rojo a **+24V** y su negro a **0V** de la bornera del carril, y el amarillo (cursor) a la banana **A0** de la bandeja (con el hilo en la mano, haz clic en la banana). A0 lee 0–1023 de 0 a 24 V. Sin hilo, el clic en la banana pone el puente a 24 V (1023).

## Partes II y III · Esclavo y maestro

Ejemplos listos para comparar con lo tuyo: `controllino_esclavo_rtu` (Listado L6.1) y `esp32plc_maestro_rtu` (L6.2). Sube el esclavo al **Controllino 1** y el maestro al **ESP32 PLC 1**; mira los dos monitores serie cambiando de equipo en el portal.

## Parte V · Diagnóstico desde el PC

Un bus RTU admite **un solo maestro**: antes de usar el convertidor, apaga el ESP32 con su interruptor del tablero (3D, panel trasero) o quítale A. En la **Terminal del PC**:

```
ls -l /dev/ttyUSB0
mbpoll -m rtu -b 19200 -P none -a 1 -t 4 -r 1 -c 8 /dev/ttyUSB0
mbpoll -m rtu -b 19200 -P none -a 1 -t 4 -0 -r 0 -c 8 /dev/ttyUSB0
```

QModMaster está en el **Escritorio del PC** (puerto `/dev/ttyUSB0`). Para las tramas crudas del Listado L6.4 usa `od -An -tx1` en lugar de `hexdump`. El esclavo de avería (L6.5) es el ejemplo `esp32plc_esclavo_averia`. Para el Paso 19.5 pide a la dirección 9, o cambia los baudios con `-b 9600` y mira qué pasa.

> **Comprobar mi solución** mira el monitor serie del maestro (FC3 sin timeout, [0] que sigue a A0, contadores iguales). Después apaga el ESP32 y, desde el PC, lee el mapa, escribe [4] (R0), y provoca las excepciones 02, 01 y 03. Al final vuelve a encender el ESP32.
