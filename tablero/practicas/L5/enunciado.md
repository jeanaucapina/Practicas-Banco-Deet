# L5 · Planificación de red: topologías, VLAN, colas y redundancia

Dimensionar la red de la línea LB-3, comparar dos topologías, y ensayar sobre una red emulada la segregación por VLAN, el cuello de botella del troncal, las disciplinas de cola y el enlace redundante. Sigue la guía (enlace arriba). Las Partes I y II son de cálculo y croquis (hoja de cálculo); no usan el tablero.

## Partes III y IV · itinerario C: la red emulada en tu Docker

La guía propone GNS3 (itinerario A) o SINETPLAN (itinerario B). El banco añade un **itinerario C**: la versión reducida de la Parte III en un contenedor de tu Docker, con espacios de red y los mismos `tc`, `iperf3`, `ping` y `tcpdump` de los Listados L5.2–L5.5.

```
sw2 = conmutador de celda y gestor del anillo   sw1 = conmutador troncal
controlador 192.168.10.10 ─┐                 ┌─ servidor_control 192.168.10.50
camara      192.168.20.10 ─┤ sw2 ══ eth5 ══ sw1 ├─ servidor_vision  192.168.20.50
                           │     ── eth6 ──    └─ hmi              192.168.99.10
```

**Preparar el tablero** deja `docker-compose.yml` y `red.sh` en `tablero/run/pc/L5`. En una terminal de tu computador:

«Preparar el tablero» **ya levanta esta pila** en segundo plano (la primera vez baja sus imágenes y puede tardar varios minutos). Los comandos de abajo sirven para reiniciarla, verla o bajarla.

```
cd tablero/run/pc/L5
docker compose -p l5 up -d
docker exec -it l5 nodo sw2                       # una shell en sw2 (tc sobre eth5)
docker exec -it l5 nodo controlador sh            # una shell en el controlador
docker exec l5 nodo servidor_control iperf3 -s -p 5010 -D
docker exec l5 nodo servidor_vision iperf3 -s -p 5020 -D
docker exec l5 cortar         /   docker exec l5 reponer      # el troncal eth5 (Paso 12)
docker compose -p l5 down                         # al terminar
```

- **VLAN** (Tabla L5.5): 10 control, 20 vídeo, 99 supervisión. Los accesos van sin etiqueta y `eth5`/`eth6` son troncales 802.1Q. Compruébalo con `bridge vlan show` en sw2; desde el controlador, `ping 192.168.20.50` no llega (otra VLAN, sin router).
- **Listado L5.1**: aquí los conmutadores son puentes Linux, no Open vSwitch. `ovs-vsctl add-port br0 eth1 tag=10` equivale a `bridge vlan add dev eth1 vid 10 pvid untagged`; tradúcelo en el informe.
- **Listados L5.2 y L5.4**: tal cual sobre `eth5` de sw2, que es la salida del troncal hacia sw1. El control del Listado L5.3, márcalo EF con `-S 0xb8` (iperf3) o `-Q 0xb8` (ping).
- **Listado L5.5, una errata que vas a encontrar**: `eth5` es un troncal etiquetado y `tc` ve sus tramas como **802.1Q**, no como IP. El filtro `protocol ip … match ip tos 0xb8 0xfc` no clasifica nada (míralo con `tc -s filter show dev eth5`) y el control sigue en la cola del vídeo. Para un troncal:

  ```
  tc filter add dev eth5 protocol 802.1q parent 1:0 prio 1 flower vlan_ethtype ipv4 ip_tos 0xb8/0xfc flowid 1:10
  ```

  Mídelo en el banco con el vídeo saturando: FIFO, unos 25 ms y pérdidas; prioridad estricta, por debajo del milisegundo.
- **Paso 12, enlace redundante**: sw2 hace de gestor del anillo, como un MRM de MRP. `eth6` queda bloqueado mientras `eth5` vive. Con `docker exec l5 cortar` el anillo se reconfigura en unos 200 ms (`T_RECONF_MS` en el `docker-compose.yml`). Cuenta los paquetes perdidos del `ping -i 0.01`. `docker logs l5` muestra los instantes.

Las capturas que hagas con `tcpdump -w /l5/l5_….pcapng` dentro de `nodo …` quedan en `tablero/run/pc/L5`, que es `~/trabajo/L5` del PC del banco.

> **Comprobar mi solución** mira tres cosas:
> - que tu red `l5` esté levantada, con las VLAN separando control y vídeo;
> - que en `~/trabajo/L5` estén las capturas `l5_*.pcapng` de los cuatro escenarios de la Tabla L5.9;
> - que en `eth5` de sw2 haya un filtro de troncal (`protocol 802.1q`) que mande el tráfico EF (TOS 0xb8) a su clase. El filtro de la errata no cuenta.
