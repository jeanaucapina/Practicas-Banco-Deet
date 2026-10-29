# L8 · PROFINET: anatomía, disección y generación de tramas

Igual que en el laboratorio, **no hay IO-Controller ni IO-Devices reales**: se analiza una captura provista, se fabrican tramas propias con scapy en una red aislada y se compara con el Modbus TCP de la L7. Sigue la guía (enlace arriba).

## Material en el PC del banco

**Preparar el tablero** deja en `~/trabajo/L8` del PC (carpeta `tablero/run/pc/L8` de tu computador):

- `l8_planta.pcapng`: la captura provista. Línea LB-3 con 1 IO-Controller (`plc-lb3`) y 4 IO-Devices de distintos fabricantes, ciclo de 4 ms y 30 s de duración. Contiene el arranque (DCP, LLDP, ARP, RPC) y el régimen permanente, con dos alarmas. La tomó un TAP de cuatro enlaces: la interfaz 0 ve todo el tráfico; las interfaces 1–3 solo el LLDP de los enlaces siguientes (lo necesitas para el **Reto** de topología; columna `frame.interface_name`).
- `GSDML-V2.42-DEET-LB3IO-20260801.xml`: un GSDML de ejemplo.

Ábrelos con Wireshark en el **Escritorio del PC**, o copia la carpeta a tu computador.

> Ojo con el filtro 3 del Listado L8.1: cuando Wireshark ha visto el RPC Connect, disecciona también las tramas cíclicas como `pn_io`. Compara con `(pn_io && !pn_rt) || udp.port == 34964 || arp` y explica la diferencia en el informe.

## Parte III · scapy en la red aislada

Tu PC ya está en la red aislada **pn_lab** (172.29.0.0/24, `--internal`). Busca su interfaz con `ip -br addr`: es la que tiene 172.29.0.10, casi siempre `eth1`. Pon esa interfaz en `IFACE` de los Listados L8.3 y L8.4 (scapy 2.5 ya está instalado). Captura en la misma interfaz:

```
cd ~/trabajo/L8
sudo tcpdump -Q out -i eth1 -s 0 -w l8_scapy.pcap 'ether proto 0x8892 or ether proto 0x88cc or (vlan and ether proto 0x8892)' &
python3 dcp_identify.py && python3 rt_generador.py
sudo pkill tcpdump; editcap -F pcapng l8_scapy.pcap l8_scapy.pcapng
```

`-Q out`: si capturas en la misma máquina que emite, tcpdump vería algunas tramas dos veces. Si prefieres el método de la guía (contenedores `pn_sniffer` y `pn_gen` en tu Docker), la red `pn_lab` ya existe: `docker network create` dirá que existe y tus contenedores entrarán en ella. Deja en `~/trabajo/L8` los guiones y `l8_scapy.pcapng`.

## Parte IV · Frente al Modbus TCP del banco

Usa tu `L7_captura….pcapng`, o captura 120 s en vivo con el servidor de la L7 cargado en el ESP32 (botón «Abrir Wireshark en vivo», red LAN, filtro `mbtcp`). Exporta `l8_ciclo_rt.csv` con el Listado L8.6 en `~/trabajo/L8`.

> **Comprobar mi solución** mira tus archivos en el PC: `dcp_identify.py` y `rt_generador.py`; que en `l8_scapy.pcapng` Wireshark reconozca una DCP Identify-All y tramas RT de 64 B con PCP 6, FrameID 0x8000 y contador de 128 en 128; y el CSV del Listado L8.6.
