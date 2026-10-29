# U6 · Taller: seguridad de redes industriales (IEC 62443)

Taller de banco por grupos (en la guía figura como «Taller U7»). Ataca y endurece **las dos redes que ya montaste**: el servidor Modbus TCP del ESP32 PLC 14 (L7) y el broker MQTT (L9). No hay hardware nuevo.

> **Ética y legalidad.** Estas técnicas —escucha, replay, saturación— se ejecutan **solo contra tu propio banco**, en este segmento aislado del laboratorio. Hacerlo contra la red de la Universidad, el banco de otro grupo o cualquier red de producción es un acceso no autorizado y motivo de sanción académica y penal. No conectes este segmento a ninguna toma de la red institucional. Enmascara las credenciales (`REDACTED`) antes de subir capturas o configuraciones.

Qué es real y qué se emula: el PLC, el broker, el switch y el PC son los mismos de L7 y L9. El atacante y el operador legítimo comparten el PC del banco (192.168.1.100); en el banco físico son dos máquinas (atacante .101). La captura usa la metodología de L4.

*Preparar el tablero* cablea el PC y el ESP32 al switch, conecta el USB para programar y deja en `~/trabajo/U6` (carpeta `tablero/run/pc/U6`) los scripts y configuraciones del taller.

| Archivo | Para qué |
|---|---|
| `reconocer.sh` | Parte I: nmap del segmento (solo tu banco) |
| `atacante_replay.py` | Parte II: replay de un mando FC6 [4]=ON |
| `frescura.py`, `revisar_frescura.py` | Parte II: filtro de frescura (Ec. U6.1) y su comprobación |
| `funcion_frescura_nodered.js` | Parte II: la misma frescura como nodo de Node-RED |
| `operador_ciclo.py`, `saturar.sh` | Parte III: medir el tiempo de ciclo bajo saturación |
| `mosquitto_seguro.conf`, `acl`, `docker-compose.yml`, `arranque_broker.sh` | Parte IV: el broker endurecido |
| `ids.py` | Reto: IDS por comportamiento |
| `zonas.md`, `respuestas.txt` | Parte V y hoja de cifras |

Antes de atacar, carga en el ESP32 el servidor Modbus TCP de la L7 (ejemplo `esp32plc_modbus_tcp`): es la víctima en 192.168.1.10:502, con el registro [4] que cierra el relé.

## Parte I · Escucha: qué viaja en claro

Con el operador sondeando (`mbpoll -m tcp ... 192.168.1.10`), captura en el PC con *Abrir Wireshark en vivo* (red LAN) y el filtro `mbtcp`. Lee, sin descifrar nada, el valor del registro [0], el código de función y el registro escrito. Repite con `mqtt` sobre el broker de L9 en 1883: el `topic`, la carga JSON y, en el CONNECT, el usuario y la clave en claro. Rellena la Tabla U6.6 y cuenta cuántos de los cinco elementos son legibles (`campos_claro_antes` en `respuestas.txt`).

## Parte II · Replay y frescura

`python3 atacante_replay.py` reinyecta el mando FC6 [4]=1: el relé obedece, indistinguible del legítimo (míralo en los LED del ESP32 o en el 3D). No hay que descifrar nada; por eso el cifrado no lo frena.

La defensa es la **frescura** (Ec. U6.1): cada mando lleva un contador monótono `seq` y una marca de tiempo `ts`, y se descarta si `seq` no crece o si `ts` está fuera de la ventana. `frescura.py` la implementa y `funcion_frescura_nodered.js` es el mismo filtro en Node-RED, delante del único nodo con permiso de escritura FC6. Compruébalo:

```
python3 ~/trabajo/U6/revisar_frescura.py
```

Mapea a SR 3.1 (integridad de la comunicación) y SR 3.8 (rechazo de repeticiones). Nota la trampa del contador persistente: si la pasarela reinicia y `seq` vuelve a cero, discútelo en el informe.

## Parte III · Saturación (disponibilidad)

Mide el tiempo de ciclo en calma y bajo carga creciente. En dos terminales del PC:

```
# terminal 1: satura el segmento (acotado; 0 para parar)
sh ~/trabajo/U6/saturar.sh 25        # luego 50, 100
# terminal 2, a la vez: mide el ciclo del PLC
python3 ~/trabajo/U6/operador_ciclo.py --n 100
```

La degradación es **real y medible**: en el banco virtual un flood no «ocupa el medio» de los otros equipos (Docker enruta por host), así que la saturación se modela en el propio PLC emulado, como un micro cuya pila de red compite con el lazo. En reposo el ciclo es ~0,5 ms; al 100 % supera los 100 ms del periodo de sondeo. Rellena la Tabla U6.8 y `respuestas.txt`: `Tc_0`, `Tc_25`, `Tc_50`, `Tc_100`, el factor `F = Tc(100 %)/Tc(0)` y el `carga_umbral_pct` a partir del cual el PLC deja de cumplir su plazo. Si además quieres tráfico visible en Wireshark, lanza `iperf3 -s` en el PC y `iperf3 -c 192.168.1.100 -u -b 50M` desde el atacante (.101).

## Parte IV · Endurecer, mapeado a IEC 62443-3-3

Levanta el broker endurecido (sustituye al de L9: autenticación FR1, ACL por rol FR2, TLS 8883 FR4, log FR6):

«Preparar el tablero» **ya levanta esta pila** en segundo plano (la primera vez baja sus imágenes y puede tardar varios minutos). Los comandos de abajo sirven para reiniciarla, verla o bajarla.

```
cd ~/trabajo/U6
docker compose -p u6 up -d          # se autoaprovisiona el cert y el pwfile
```

Verifica los tres hechos (todos benignos: confirman que la defensa funciona):

```
# anónimo rechazado (FR1)
mosquitto_pub --cafile server.crt --insecure -h 192.168.1.52 -p 8883 -t planta/sensor/x -m 1
# operador por TLS (FR4)
mosquitto_pub --cafile server.crt --insecure -h 192.168.1.52 -p 8883 -u operador -P banco -t planta/sensor/t -m 25
# el lector NO puede mandar (FR2); queda en el log (FR6)
mosquitto_pub --cafile server.crt --insecure -h 192.168.1.52 -p 8883 -u lector -P banco -t planta/actuador/rele -m x
docker logs u6-broker | grep "Denied PUBLISH"
```

El certificado es autofirmado con CN `broker.planta.local`; por eso se conecta por IP con `--insecure`. La clave de laboratorio es `banco`: cámbiala en un despliegue real. Segmenta además el switch por VLAN (FR5) separando control de supervisión; si tu switch no es gestionable, documenta la regla de firewall equivalente (qué IP, qué puerto y qué código de función permite).

> El endurecimiento **no** detiene por sí solo el replay de un cliente con credencial robada: por eso la frescura de la Parte II es complementaria de TLS, no sustituible. Anótalo en `lo_que_falta_tras_tls`.

## Parte V · Zonas, conductos y respuesta al compromiso

Rellena `zonas.md`: el diagrama de zonas (campo / control / supervisión) y conductos, un Security Level objetivo por zona y el procedimiento ante «RTU/IED comprometido». Lo evalúa el docente.

## Reto · IDS

`ids.py` vigila el segmento y publica una alarma en `planta/seguridad/incidente` cuando ve una escritura FC6 anómala sobre [4] o una tormenta. Mide el tiempo de detección (Ec. U6.2) del replay y de la saturación.

> **Comprobar mi solución** prueba las **defensas** contra tu banco endurecido:
> - el servidor Modbus TCP de la L7 responde (la víctima está en pie);
> - tu broker `u6-broker` está levantado;
> - la conexión anónima es rechazada (FR1), el operador publica por TLS (FR4) y la ACL deniega al lector, dejándolo en el log (FR2/FR6);
> - tu filtro de frescura acepta lo legítimo y descarta el replay (FR3);
> - en `respuestas.txt`: el factor `F` y los campos en claro antes/después.
>
> El diagrama de zonas, el procedimiento de respuesta, la Parte III medida y el reto los evalúa el docente.
