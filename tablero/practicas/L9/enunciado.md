# L9 · WiFi industrial, MQTT y pasarela Node-RED

La ruta completa del dato: el **ESP32 PLC 14 por WiFi** (192.168.1.10, servidor web en :80 y Modbus TCP en :502), una **pasarela Node-RED** que sondea por Modbus TCP y publica en **MQTT** con el espacio de nombres Sparkplug B, y un **panel** que manda de vuelta. Sigue la guía (enlace arriba); aquí va lo propio del banco virtual.

## Montaje (Tabla L9.4)

- **Preparar el tablero** enchufa el PC al switch, el USB del PC al ESP32 y **enciende la radio del ESP32** (la antena ya está enroscada). El punto de acceso del laboratorio está en el mismo segmento 192.168.1.0/24.
- Potenciómetro: módulo *potenciómetro* del 3D, hilo amarillo al borne **I0.7** del bloque MÓDULOS.
- El foco de 24 V es **Q0.1**: míralo en los LED del frente del ESP32 o en el portal.
- **Posición A / B** (Paso 5): el selector junto al botón WiFi del equipo, en el portal, mueve el banco respecto al AP. Lee `/estado` cinco veces en cada una y anota la mediana: el RSSI fluctúa como el real.

> El ADC del ESP32 del banco es de **12 bits** (0–4095, como dice la L7). La guía escala con 1023: decide la escala y justifícala.

## Parte I · El PLC en la WiFi

Carga la **plantilla** (Listado L9.1). El banco acepta cualquier SSID y clave (no subas las tuyas al repositorio). Paso 3: comenta `WiFi.config(...)` para ver qué IP da el DHCP del laboratorio (rango .150–.199) y vuelve a la fija. Paso 4, desde el **Escritorio del PC** (navegador) o la terminal:

```
curl http://192.168.1.10/estado
curl http://192.168.1.10/releOn
```

## Parte II · Broker y Node-RED

Dos caminos; el primero es el de la guía:

1. **Tu propio Docker** (en tu computador, que es donde corre el banco). En `~/trabajo/L9` del PC (carpeta `tablero/run/pc/L9`) tienes `docker-compose.yml` y `mosquitto.conf` adaptados: tu `mosquitto_broker_l9` (192.168.1.51) y tu `nodered_l9` (192.168.1.61, editor en http://localhost:1882) quedan **enchufados al switch del banco** (red `tab_lan`). Instala en Node-RED las paletas `node-red-contrib-modbus` y `@flowfuse/node-red-dashboard`.
2. **Los del banco**: broker 192.168.1.50 (también se llama `mosquitto_broker`) y Node-RED 192.168.1.60 (botón *Node-RED* del portal, ya con las dos paletas; `/historico` y hora de Ecuador listos).

Paso 8 desde la terminal del PC: `mosquitto_sub -h 192.168.1.51 -t "spBv1.0/Planta1/#" -v` (o .50).

## Parte III · La pasarela

Modbus-Read a 192.168.1.10:502, Unit 1, FC3, dirección 0, 8 registros, 500 ms. El nodo function del Listado L9.5 está en `~/trabajo/L9/funcion_pasarela.js`. Mando de vuelta con el Listado L9.6 (DCMD/KA-104 → FC6 sobre [4]).

## Partes IV y V

Latencia por QoS, sondeo frente a excepción, Last Will (`docker stop nodered_l9` o `tab-nodered`), vigilante del PLC (apaga el interruptor *ESP32 PLC* del tablero en el 3D, o el WiFi), histórico local con el broker parado y mensajes retenidos. Captura MQTT: «Abrir Wireshark en vivo» (red LAN) con el filtro `mqtt`.

> **Comprobar mi solución** usa el PC del banco: ping y `/estado` por la WiFi, los enlaces de relé, Modbus TCP, que llegue `TT-101` al broker (.50 o .51) y que un mando `DCMD/KA-104` encienda y apague Q0.1 pasando por tu Node-RED.
