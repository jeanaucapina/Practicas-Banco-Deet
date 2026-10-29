# Núcleo Arduino virtual (para quien mantiene el tablero)

Guía de uso para estudiantes: [../../ejemplos_arduino/LEEME.md](../../ejemplos_arduino/LEEME.md).

## Cómo encaja

```
lab.ps1 subir  ->  tablero/programas/<equipo>/fuente/*.ino
               ->  docker exec <contenedor> python compilar.py   (g++ + este núcleo)
               ->  /programas/<equipo>/programa  +  docker restart
arranque.py    ->  programa.py si hay programa, si no controllino.py / esp32plc.py
programa.py    <-> programa (tuberías de texto, ver cabecera de nucleo.cpp)
```

- `compilar.py` imita al IDE:
  - añade `#include <Arduino.h>`;
  - genera prototipos de las funciones definidas a nivel 0;
  - mantiene los números de línea del `.ino` con `#line`.
- El núcleo se compila una vez por contenedor, en `/tmp/nucleo_<tipo>`.
- **Pines:** son números propios del núcleo, no los del micro real.
  - Controllino: D 100-123, R 130-145, A 160-175, I16-18 180-182, IN0/1 183-184.
  - ESP32: Q 200-203, R0_1 204, I0_1..8 211-218.
  - El pin 255 lleva los bits del ADC.
  - Si cambias alguno, cambia también `PERFILES` en `programa.py`.
- **Red:** son sockets del contenedor. `Ethernet` y `WiFi` miran si existe una IP
  del segmento del banco (192.168.1.x), que la pasarela pone y quita con
  `docker network connect` cuando el RJ45 se enchufa al switch o la WiFi se enciende.
- **Puertos serie:** `Serial` (0) = monitor (stdout). El RS-485 del bus es `Serial3`
  en el Controllino y `Serial1`/`RS485` en el ESP32. `Serial2` es la HMI STONE del
  tablero (protocolo STONE por UDP con `panel/hmi_stone.py`). `loraSerial` (solo ESP32)
  es el slot LORA: el RN2903 emulado de `dispositivos/rn2903.py` (ver `rn2xx3.h`).
- **RS-485:** capa física real (`bus485.py`): el programa manda bytes a sus baudios y
  el núcleo los agrupa en tramas por silencio t3.5 o al hacer `flush()`; baudios
  distintos o A/B cruzados dan basura y dos emisores a la vez colisionan. `programa.py`
  los pasa al bus con `enviar_485_crudo`/`crudo_485` de `base.py`.
- **Librerías incluidas** (en `arduino/`): `Ethernet.h`, `WiFi.h`, `ArduinoRS485.h` y
  `RS485.h` (Industrial Shields), `ArduinoModbus.h`, `ModbusRTU.h`, `ModbusEthernet.h`,
  `ModbusIP_ESP8266.h`, `PubSubClient.h`, `WebServer.h`, `Wire.h`, `EEPROM.h`,
  `Procesar_HMI.h`/`Stone_HMI_Define.h` (HMI STONE), `rn2xx3.h` y `RTClib.h` (LoRa, L10).
- **Estado hacia las gafas:**
  - mismas claves que la imitación de fábrica;
  - Controllino con `modo` 9, que la HMI muestra como `PROGRAMA <nombre>`;
  - el ESP32 añade `lora` (antena, posición, unión, canales) para el portal.

## Lo que NO funciona (y en el real sí)

- Registros del microcontrolador (`PORTB`, …): es la API de Arduino, no un emulador del
  chip. `Timer1` y sus ISR sí están (lo pide la L2).
- I2C (`Wire`): el bus está vacío; todo responde NACK (salvo el DS3231 de `RTClib.h`,
  que da la hora del anfitrión en UTC).

## Probado (2026-10-16, Docker Desktop)

- `controllino_filas`: I17 enciende D1/D7/D13, `analogRead(A0)` sigue al
  potenciómetro y el `Serial` llega a la consola.
- `esp32plc_mqtt`: espera la WiFi hasta que se enciende, publica las entradas en el
  broker y obedece `q00`.
- `controllino_rtu` (maestro del alumno) frente al Controllino 2 de fábrica:
  - lee sus pulsadores;
  - con A/B cruzados, "sin respuesta" y `crc_mal` en el esclavo.
- Error de compilación: sale como `malo.ino:8:37: error: expected ';'`.
- Escribir en el bus sin `TxEnable`: aviso en la consola.
