# L10 · IIoT de largo alcance con LoRaWAN

El mismo registro de L6 y L9 (A0 del Controllino), ahora por LoRaWAN. El ESP32 PLC 14 hace de maestro Modbus RTU y de nodo de clase A en US915. La pasarela del laboratorio lo reenvía a **tu servidor de red** y de ahí al tablero de Node-RED de L9. Sigue la guía (enlace arriba). Aquí va lo propio del banco.

Qué es de verdad y qué se emula:

- **Módulo RN2903.** Se emula con sus comandos de texto (`sys`, `mac`, `radio`) y con la MAC LoRaWAN 1.0.x real: AES-128, MIC, FCnt, ventanas RX1/RX2 y comandos MAC. Un ChirpStack o un The Things Stack aceptan sus tramas.
- **Pasarela HT-M7603.** Tiene 8 canales en la FSB 2 y está en 192.168.1.70. Usa el *packet forwarder* Semtech UDP real.
- **El aire.** Se calcula para cada trama: pérdida según la posición (P1/P2/P3), antenas, sombra aleatoria, ruido, SNR mínima por SF y colisiones.
- **Servidor de red.** Es un **ChirpStack real en tu Docker** (Anexo C). La instancia de The Things Stack del laboratorio no está en el banco virtual.

## Montaje (Tabla L10.4)

- **Preparar el tablero** hace cuatro cosas:
  - cablea el bus RS-485 entre el Controllino y el ESP32 (A con A, B con B);
  - conecta el USB del PC a los dos PLC;
  - enchufa el RJ45 de la pasarela al puerto 4 del switch;
  - deja el nodo en P1.
- **La antena NO viene puesta.** Atorníllala antes de cargar el programa: toca el conector SMA dorado **LORA**, arriba del ESP32, en el 3D.
  - Si el RN2903 emite sin antena, se daña. Sigue contestando, pero pierde unos 35 dB y solo llega a pocos metros.
  - El portal lo avisa. El botón *Cambiar el módulo RN2903 averiado* hace las veces del docente con un módulo nuevo.
- **Esclavo.** Carga en el Controllino el ejemplo `controllino_esclavo_l10`: es el esclavo de L6 con [8] = A1 y [9] = palabra de estado. También vale tu esclavo de L6 extendido.
- **Potenciómetros.**
  - **P1:** el cursor del potenciómetro del módulo va a **A0**, como en L6.
  - **P2:** va a **A1**. Usa el potenciómetro del tablero 2, cuyo hilo llega hasta el Controllino 1, o el puente de A1 (0 o 1023).
  - Las analógicas del Controllino del banco leen 0–24 V → 0–1023. Por eso el módulo va a 24 V, como en L6.
- **DS3231.** Va en el kit del nodo. `RTClib` da la hora UTC del laboratorio con `rtc.now().unixtime()`.

## Servidor de red: ChirpStack en tu Docker

*Preparar el tablero* deja en `~/trabajo/L10` (carpeta `tablero/run/pc/L10`) estos archivos:

- `docker-compose.yml` y `configuration/`: ChirpStack v4, gateway bridge, PostgreSQL y Redis;
- `decodificador.js`: el Listado L10.4;
- `funcion_nodered_l10.js`: el Listado L10.6.

«Preparar el tablero» **ya levanta esta pila** en segundo plano (la primera vez baja sus imágenes y puede tardar varios minutos). Los comandos de abajo sirven para reiniciarla, verla o bajarla.

```
cd tablero/run/pc/L10
docker compose -p l10 up -d          # web: http://localhost:8089  (admin / admin)
```

El gateway bridge queda enchufado al switch del banco en **192.168.1.80**. La pasarela le manda sus tramas por UDP 1700; la dirección se puede cambiar en la web de la pasarela. ChirpStack publica en el **broker del laboratorio, 192.168.1.50**.

Paso 4, en la web de ChirpStack:

1. **Gateways → Add gateway.** El *Gateway ID* es `A84041FFFE1F7603`; lo muestra la web de la pasarela (botón *Pasarela LoRaWAN* del portal).
2. **Device profiles → Add.** Rellena así:
   - Region *US915* y region configuration **us915_1** (FSB 2);
   - MAC version *LoRaWAN 1.0.4* y regional parameters *RP002-1.0.3*;
   - *Supports OTAA* marcado;
   - en *Codec*, elige *JavaScript functions* y pega `decodificador.js`.
3. **Applications → Add → Add device.**
   - Nombre: `nombre-apellido`.
   - DevEUI: el que imprime el nodo (`0004A30B001F7A01` en el tablero 1, `…7A02` en el 2).
   - JoinEUI: genéralo.
   - En *OTAA keys*, genera la *Application key*: en LoRaWAN 1.0.x es la AppKey.
   - Copia el JoinEUI y la AppKey al programa.

Comprobación desde la terminal del PC (Listado L10.2):

```
mosquitto_sub -h 192.168.1.50 -v -t 'application/+/device/+/event/up'
```

La captura en vivo de la red LAN muestra el backhaul:

- con el filtro `udp.port == 1700`: PUSH_DATA con el `rxpk` en JSON, la trama en base64, PULL_RESP y TX_ACK;
- con el filtro `mqtt`: el resto del camino.

## Partes I y II · Nodo, plan de frecuencias y unión

- **Listado L10.1** es el ejemplo `esp32plc_lora_otaa`.
  - En este paquete de placas el puerto del slot se llama **`loraSerial`**.
  - Con `Serial1` le hablarías al bus RS-485 y `sysver` no contestaría: es la trampa del recuadro.
- **Sin `setFrequencyPlan(TTN_US)`**, el nodo salta por los 64 canales. La web de la pasarela solo muestra los JoinRequest que caen en los canales 8 a 15: en torno a uno de cada ocho.
- **Pasos 5 y 6.** Mira la unión en ChirpStack, en el dispositivo, pestañas *LoRaWAN frames* y *Events*:
  - el JoinRequest;
  - el JoinAccept, en RX1 a los 5 s;
  - el primer ascendente, con FCnt 0.

  La web de la pasarela da la hora, el canal, el RSSI, la SNR y el tiempo en el aire de cada trama.
- **El JoinAccept trae una máscara de canales** (CFList). ChirpStack deja activos solo los de su región: 8-15 y el 65. La tarjeta del ESP32 en el portal pasa de «canales 8-15,64-71» a «8-15,65».
- **Reiniciar el nodo.** Vuelve a subir el programa. `initOTAA` empieza con `mac reset` y repite la unión, así que la DevAddr y las claves cambian.
- **Paso 7: fallo provocado, de dos maneras.**
  - Como con TTS: en la web de la pasarela, elige el plan **FSB 1**.
  - Como con ChirpStack, en PowerShell:

    ```
    $env:REGION="us915_0"; docker compose -p l10 up -d chirpstack-gateway-bridge
    ```

  Para volver, deja `us915_1` (o FSB 2). Compáralo con una AppKey equivocada: en ese caso el JoinRequest sí llega al servidor, pero se rechaza.

## Parte III · Del registro Modbus a la trama binaria

- **Listado L10.3** es la **plantilla**; la solución completa está en el ejemplo `esp32plc_lora_pasarela`.
- `RS485.begin(19200, SERIAL_8N1)` funciona sin `#include`, porque el paquete de placas lo da. El ejemplo manda el primer ascendente nada más leer el PLC, sin esperar los 10 min.
- La trama de la Fig. L10.4 ocupa **22 B de carga física**. En DR0 (SF10) son **370,7 ms**.
- `alarma_temp` cambia en el **siguiente** ascendente, no al mover P1: es clase A.

## Parte IV · Barrido de SF y de distancia

- **El SF se fija a mano.** `rn2xx3` ya manda `mac set adr off`. Fija el SF con `lora.setDR(3)` (SF7) o `lora.setDR(1)` (SF9).
- **Posición.** Usa el selector *LoRa en P1 / P2 / P3* de la tarjeta del ESP32 en el portal:
  - P1: laboratorio, unos 5 m;
  - P2: otro piso, dos losas, unos 40 m;
  - P3: exterior, sin línea de vista, unos 300 m.
- **Tiempo en el aire.** Lo da la **web de la pasarela**. ChirpStack da RSSI y SNR, pero no el tiempo en el aire.
- **Ciclo de trabajo del 1 %.** Con 22 B:
  - SF7: 56,6 ms, al menos 5,7 s entre envíos;
  - SF9: 205,8 ms, al menos 20,6 s.
- **SF12 en modo radio** (Listado L10.5).
  - El emisor es el ejemplo `esp32plc_lora_sf12`.
  - El receptor es el ESP32 del **tablero 2**, con `esp32plc_lora_rx` y su antena puesta.
  - `radio rx 0` termina con el perro guardián del módulo, 15 s de fábrica. Con `radio set wdt 0` la escucha es indefinida.

## Parte V · Al tablero de L9

En Node-RED (el del banco, 192.168.1.60, o tu `nodered_l9`), monta tres nodos:

1. `mqtt in`: broker 192.168.1.50, tema `application/+/device/+/event/up`, salida *objeto JSON*.
2. El *function* de `funcion_nodered_l10.js`. Con una salida devuelve `[[…]]`; lee la nota del archivo.
3. `mqtt out` al **mismo broker 192.168.1.50**.

Superpón en el tablero de L9 la serie WiFi y la de LoRaWAN, y añade el indicador de `ts_nodo`.

> **Comprobar mi solución** mira siete cosas. Necesita al menos un ascendente en los últimos 25 min.
> - La antena está puesta y el módulo sano.
> - ChirpStack corre.
> - La pasarela tiene backhaul y respuesta del servidor.
> - El nodo está unido y solo usa la sub-banda 2.
> - El último ascendente es la trama de 9 B, con TEMP, NIV y las alarmas iguales a A0 y A1 del Controllino. No muevas los potenciómetros después del último envío.
> - ChirpStack la decodificó: `temperatura`, `nivel`, `alarma_temp` y `ts_nodo`.
> - Node-RED publicó `planta/lorawan/temperatura` en el broker del laboratorio.
