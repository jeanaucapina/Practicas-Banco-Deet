# Programar el Controllino y el ESP32 PLC del tablero

Escribes un `.ino` normal de Arduino y lo cargas en el **tablero virtual**: lo
ves funcionar en las gafas y en la red del laboratorio, sin tocar el equipo
real. El mismo archivo se carga después en la placa real con el Arduino IDE.

## En el tablero virtual

Lo más cómodo: en el panel (<http://localhost:8090>), tarjeta *Programar un equipo*,
elige un **ejemplo** de la lista y pulsa *Subir el ejemplo a este equipo*.
Por consola:

Con el laboratorio arrancado (`.\lab.ps1 arrancar`):

```powershell
.\lab.ps1 subir t1.controllino C:\mis_practicas\filas\filas.ino   # compila y carga
.\lab.ps1 serie t1.controllino                                   # monitor serie
.\lab.ps1 subir t1.controllino fabrica                           # vuelve al de fabrica
```

Equipos: `t1.controllino`, `t2.controllino`, `t1.esp32plc`, `t2.esp32plc`.

- Si no compila, salen los errores con la línea de tu `.ino` y el equipo sigue con
  el programa anterior.
- La HMI del tablero muestra `PROGRAMA <nombre>` mientras corre el tuyo.
- Si tu programa se cuelga o falla, se reinicia solo a los 2 s (como un reset).
- Las últimas líneas de `Serial` salen también en la consola del equipo en las
  gafas (como mucho 5 por segundo).

## Nombres de pines

| Controllino MEGA (`#include <Controllino.h>`) | ESP32 PLC 14 (sin include) |
|---|---|
| Salidas `CONTROLLINO_D0` … `D23`, relés `CONTROLLINO_R0` … `R15` | Salidas `Q0_0` … `Q0_3`, relé `R0_1` |
| Entradas analógicas `CONTROLLINO_A0` … `A15` (0-1023) | Entradas `I0_1` … `I0_8`; `I0_5` … `I0_8` también analógicas (0-4095) |
| Pulsadores del panel `CONTROLLINO_I16`, `I17`, `I18`; `IN0`, `IN1` | |
| RS-485 en `Serial3`: `Controllino_RS485Init()`, `TxEnable()`, `RxEnable()` | RS-485 con `RS485.begin(9600, HALFDUPLEX, SERIAL_8N1)` |

Usa siempre los nombres, nunca números de pin.

## Qué funciona

- `pinMode`, `digitalRead/Write`, `analogRead/Write`, `millis`, `delay`,
  `attachInterrupt`, `String`, `Serial`, `EEPROM` (se borra al reiniciar).
- **RS-485** de verdad sobre el bus del tablero: si cruzas A/B, tu programa recibe
  basura o nada, como en el real. En el Controllino, si escribes sin
  `Controllino_RS485TxEnable()` no sale nada y la consola te lo avisa.
- **Ethernet** (`Ethernet.h`) y **WiFi** (`WiFi.h`) con sockets reales: hay enlace
  si en las gafas el cable del equipo está en el switch, o si la WiFi del ESP32 está
  encendida. El segmento del banco es **192.168.1.0/24** (ESP32 .10, Controllino .11,
  PC .100); la IP la pone el laboratorio, y si pides otra en `Ethernet.begin()`/
  `WiFi.config()`, la consola te lo avisa.
- **MQTT** con `PubSubClient.h`. Broker del banco en `192.168.1.50`.
- **Modbus**: `ArduinoRS485`/`ArduinoModbus` (esclavo), `ModbusRTU.h` (maestro,
  `modbus-esp8266`), `ModbusEthernet.h`/`ModbusIP_ESP8266.h` (TCP). Están incluidas.
- **HMI STONE** (`Procesar_HMI.h`): `Serial2` habla con la pantalla del tablero.
- **LoRa** (solo ESP32, L10): `rn2xx3.h` sobre `loraSerial` (el RN2903 del slot LORA),
  `RTClib.h` para el DS3231. Atornilla la antena en el 3D antes de emitir.
- Puedes poner `.h` y `.cpp` propios junto al `.ino`; se suben con él.

## Qué no funciona (y en el real sí)

- Registros del microcontrolador (`PORTB`, …): es la API de Arduino, no un emulador del
  chip. `Timer1` y sus ISR sí están (lo pide la L2).
- I2C (`Wire`): el bus está vacío y todo responde NACK (salvo el DS3231 de `RTClib.h`).

## Ejemplos (uno o dos por guía)

| Carpeta | Equipo | Guía · qué hace |
|---|---|---|
| `l0_blink_controllino` / `l0_blink_esp32plc` | ambos | L0 · blink de D0 / Q0.0 con el selector de tensión |
| `controllino_semaforo`, `controllino_rebote` | Controllino | L1 · FSM de semáforo y antirrebote de los pulsadores |
| `controllino_stone_pwm`, `controllino_stone_epc` | Controllino | L2 · HMI STONE y lazo del motor EPC con encoder |
| `controllino_eco_485`, `esp32plc_eco_485`, `controllino_trama_maestro`, `esp32plc_trama_esclavo` | ambos | L3 · RS-485 con trama propia |
| `controllino_esclavo_rtu`, `esp32plc_maestro_rtu`, `esp32plc_esclavo_averia` | ambos | L6 · Modbus RTU maestro-esclavo |
| `esp32plc_modbus_tcp` | ESP32 PLC | L7 · servidor Modbus TCP por Ethernet |
| `esp32plc_wifi_web`, `esp32plc_mqtt` | ESP32 PLC | L9 · WiFi, servidor web y MQTT |
| `controllino_esclavo_l10`, `esp32plc_lora_otaa`, `esp32plc_lora_pasarela`, `esp32plc_lora_sf12`, `esp32plc_lora_rx` | ambos | L10 · nodo LoRaWAN y pasarela Modbus→LoRa |
| `controllino_blink`, `controllino_boton`, `controllino_filas` | Controllino | ejemplos sueltos de E/S |

## En la placa real

- **Controllino:** en el Arduino IDE, Preferencias → URLs adicionales:
  `https://raw.githubusercontent.com/CONTROLLINO-PLC/CONTROLLINO_Library/master/Boards/package_ControllinoHardware_index.json`.
  Instala *CONTROLLINO AVR Boards* y la librería *CONTROLLINO*, elige la placa
  **CONTROLLINO MEGA**, el puerto USB y pulsa Subir.
- **ESP32 PLC 14:** instala el paquete de placas de Industrial Shields y elige
  *ESP32 PLC 14*.
  - Comprueba que los nombres de pin y la API RS-485 de tu versión del paquete
    coincidan con los de la tabla.
  - En WiFi pon el SSID, la clave y la IP del broker de tu red.
