# L7 · Modbus TCP por Ethernet industrial

Servidor Modbus TCP en el **ESP32 PLC 14** (192.168.1.10:502) con el mismo mapa de ocho registros de la L6, y el **PC del banco** (192.168.1.100) como cliente: mbpoll, QModMaster, pymodbus y Wireshark. Sigue la guía (enlace arriba): aquí solo va lo que cambia en el banco virtual.

## Montaje (Tabla L7.4)

- **Preparar el tablero** deja puestos: ESP32 → puerto 1 del switch, PC → puerto 2, y el USB del PC al micro USB del ESP32 (sin él no se puede programar).
- Potenciómetro: coge en el 3D el módulo *potenciómetro* y lleva su hilo amarillo (SEÑAL) al borne **I0.7** del bloque MÓDULOS; rojo a 5V y negro a GND.
- REL-A, REL-B, Q0.2 y Q0.3 se ven en los LED del frente del ESP32 y en el portal.

## Parte I · La red antes que Modbus

Sube la **plantilla** (esbozo L7.2: solo red y puerto 502). Abre la **Terminal del PC** y ejecuta los bloques 2–4 del Listado L7.1. El PC ya tiene 192.168.1.100 al estar enchufado al switch (en el laboratorio la fijarías tú): léela de vuelta.

```
ip -4 addr show            # 192.168.1.100/24
ip route show
ping -c 4 192.168.1.10
arp -a | grep 192.168.1.10 # de:ad:be:ef:fe:0a
nc -vz 192.168.1.10 502
```

Paso 5 (tres averías): quita en el 3D el cable del ESP32 al switch; vuelve al programa de fábrica con el cable puesto (el ping sigue, el 502 no); y prueba una máscara /25 en el PC con `sudo ip addr`.

## Parte II · El servidor

Sustituye el esbozo por el Listado L7.3 (mapa de ocho registros). Monitor serie: «Servidor Modbus TCP en 192.168.1.10». Comprueba con mbpoll en base 1 y en base 0 (Listado L7.4).

## Parte III · El cliente

mbpoll FC6 y FC16 (Listado L7.5), luego QModMaster (escritorio del PC → QModMaster, Modbus TCP 192.168.1.10:502) y el cliente Python: `cd ~/trabajo/L7 && python3 cliente_l7.py`.

## Parte IV · Wireshark

Captura en la interfaz del PC: en el **Escritorio del PC** abre Wireshark sobre su interfaz 192.168.1.100 (o `tshark -i eth1` en la terminal), o desde tu computador con «Abrir Wireshark en vivo» (red LAN). Filtro `mbtcp`. Guarda `L7_capturaSuApellido.pcapng`.

## Parte V · Estrés

Escritura concurrente con dos terminales (Listado L7.8), desconexión del cable a mitad de sondeo (quita el cable del ESP32 en el 3D y mira el timeout de 1000 ms), nueve conexiones (`nc 192.168.1.10 502 &` nueve veces: el servidor admite 8) y transacciones por segundo.

> **Comprobar mi solución** usa el PC del banco: hace ping, arp, nc y mbpoll contra 192.168.1.10, escribe por FC6 y FC16 y mira los relés. Necesita el servidor del Listado L7.3 cargado y el PC enchufado al switch.
