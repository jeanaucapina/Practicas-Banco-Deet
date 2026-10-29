# L4 · Captura y análisis de tráfico (Wireshark + Docker)

Capturar bien antes de interpretar: elegir la interfaz y el punto de observación, filtrar y diseccionar una trama Modbus TCP campo a campo, y medir ciclo, jitter y carga. Sigue la guía (enlace arriba).

## Parte I · Sobre el banco

**Preparar el tablero** conecta el ESP32 PLC 1 al puerto 1 del switch y el **PC del banco** al puerto 2: 192.168.1.100/24, ya configurado; léelo con `ip -brief address`. El ESP32 debe tener su programa de fábrica (192.168.1.10). Si cargaste otro, usa «Volver al programa de fábrica».

Todo se hace en el **Escritorio del PC**: terminal y Wireshark sobre la interfaz que tiene 192.168.1.100, que es la tarjeta del PC, no la de gestión ni `pn_lab`.

```
ip -brief link show
ip -brief address show
tcpdump -D
sudo tcpdump -i eth2 -c 5 -n        # la interfaz que anotaste
sudo ip neigh flush all
ping -c 20 -i 1 192.168.1.10
```

Guarda la captura como `~/trabajo/L4/l4_banco.pcapng`. En tu computador es la carpeta `tablero/run/pc/L4`.

**Paso 6 (la pareja vecina)**: el tablero 2 hace de pareja. Su Controllino, en modo MAESTRO TCP, escribe cada segundo en el Controllino 1 (192.168.1.11) a través de los switches. Desde el PC solo verás sus ARP de difusión, no su Modbus de unidifusión: el puente de Docker aprende MAC como un switch.

## Partes II a IV · Docker en tu computador

La guía se hace tal cual en **tu Docker**, que ya tienes porque el banco corre en él: `planta_net`, `plc_sim`, `hmi_sim` y los dos sniffers A y B. `servidor.py` y `cliente.py` (Listados L4.4 y L4.5) ya están en `tablero/run/pc/L4`. Monta esa carpeta como `~/l4` (`-v <ruta>/run/pc/L4:/app`) y deja `planta.pcap` y `l4_planta.pcapng` en la misma carpeta. El Paso 11 (`mkfifo` + `wireshark -k`) se hace en Linux/WSL. En Windows abre `planta.pcap` al terminar, o usa el Wireshark del PC del banco sobre el archivo.

## Tres erratas de la guía (v2) que vas a encontrar

- **Listado L4.4**: con pymodbus 3.6.9, `registros.getValues(3, 0, 1)` es la firma del *contexto*, no del bloque de datos. La tarea que simula el proceso muere con `TypeError` y [0] se queda fijo en 512. El `servidor.py` del banco ya lo trae corregido: `getValues(0, 1)` y `setValues(0, [...])`. Explícalo en el informe.
- **Paso 18 y Listado L4.9**: el filtro `mbtcp.modbus.func_code == 3` no existe en Wireshark. El campo es `modbus.func_code`: `modbus.func_code == 3 && tcp.len > 0 && ip.src == 172.28.0.100`.
- **Subred 172.28.0.0/24 y ot-lab**: el *ot-lab* de los talleres ya usa esa subred, y con él arriba `docker network create … planta_net` falla con «Pool overlaps». No hace falta pararlo: crea la red en **172.27.0.0/24** (`--subnet 172.27.0.0/24`), da a `plc_sim` la 172.27.0.10 y a `hmi_sim` la 172.27.0.100, y lanza el cliente con `-e PLC_IP=172.27.0.10`. En los filtros de Wireshark, cambia `172.28.0.` por `172.27.0.`.

> **Comprobar mi solución** mira, desde el PC, que alcanzas el ESP32. En `~/trabajo/L4` mira tres cosas:
> - `l4_banco.pcapng`: el ARP *is-at* de 192.168.1.10 y al menos diez ecos ICMP con respuesta;
> - `l4_planta.pcapng`: Modbus TCP con peticiones FC3 cada 250 ms y el comentario de paquete del Paso 15;
> - `serie_ciclo.csv`, del Listado L4.9.
