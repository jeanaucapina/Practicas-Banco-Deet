# U4 · Taller: comparación de tramas y selección de protocolo

Es un taller de aula por grupos (en la guía figura como «Taller U5»). La matriz y la defensa se hacen en papel y se entregan en PDF. Al Ejercicio 1 le faltaban tramas de protocolos que no se montan; el banco las aporta como **capturas de muestra**, construidas byte a byte según su norma, para que Wireshark las diseccione como si vinieran de una planta.

*Preparar el tablero* deja en `~/trabajo/U4` (carpeta `tablero/run/pc/U4`) estos archivos:

| Archivo | Qué contiene |
|---|---|
| `u4_goose.pcap` | IEC 61850 GOOSE de dos IED: un relé de protección (`PROT_P1_PTOC`) y un interruptor (`CTRL_P1_XCBR`). Latido cada segundo; a los 2,5 s, una falta: disparo y apertura |
| `u4_dnp3.pcap` | DNP3 sobre TCP 20000 entre el SCADA (.100) y una estación remota (.30): sondeo de integridad, un evento **no solicitado** (RBE) y su confirmación |
| `u4_devicenet.pcap` | DeviceNet sobre CAN: el maestro sondea los esclavos MAC 10, 11 y 12 cada 10 ms |
| `l8_planta.pcapng` | PROFINET RT de la L8 (por si no guardaste la tuya) |
| `respuestas.txt` | la hoja de cifras que lee *Comprobar mi solución* |
| `revisar_matriz.py` | revisa la coherencia de tu matriz de decisión |

Ábrelas en el **Escritorio del PC** (Wireshark) o en tu computador. En DeviceNet: *Decode As… → CAN next level dissector → DeviceNet* (en tshark, `-d can.subdissector,devicenet`).

Para **Modbus RTU** usa tu captura de L6, o captúrala ahora: *Preparar* cablea el USB-RS485 al Controllino 1. Lanza `mbpoll -m rtu -b 19200 -P none -a 1 -t 4 -0 -r 0 -c 8 -1 /dev/ttyUSB0` con Wireshark en la red RS-485 y *Decode As mbrtu*. **Modbus TCP** sale de tus capturas de L4 o L7.

## Ejercicio 1 · Disección comparada

Rellena la Tabla U5.4 con las capturas y la Fig. U5.2. Las sobrecargas del Análisis 1 van en `respuestas.txt` con un decimal. Además, en las capturas del banco:

- **GOOSE**:
  - el EtherType;
  - el `stNum` del mensaje de disparo;
  - el intervalo hasta su primer reenvío y el `timeAllowedtoLive` que anuncia el disparo;
  - cuántos ms pasan entre el disparo del relé y el primer GOOSE del interruptor que publica la apertura.

  Mira `stNum`/`sqNum`: cuál sube con cada cambio de estado y cuál con cada repetición. Fíjate en cómo se espacian los reenvíos.
- **DNP3**:
  - los bytes de inicio de la trama de enlace;
  - cuántas entradas analógicas trae la respuesta al sondeo;
  - el índice y el valor del evento no solicitado.

  Mira dónde caen los CRC: uno cada 16 bytes de datos.
- **DeviceNet**:
  - los bits del identificador CAN;
  - qué esclavo cambia sus entradas a mitad de la captura.

## Ejercicios 2 y 3 · Casos y matriz de decisión

Con los pesos fijos de la §c.5, rellena la Tabla U5.5 de tu caso. En `respuestas.txt` van:

- `caso` (1–4);
- `ganador` y `segundo`: el nombre del protocolo, como en el enunciado del caso;
- sus S_j, con dos decimales;
- `ganador_sensibilidad`: el ganador tras el Análisis 3.

Compruébalo con:

```
python3 ~/trabajo/U4/revisar_matriz.py
```

El script no juzga tus puntuaciones: eso se defiende ante el grupo. Solo mira que la cuenta sea coherente. Si el margen sobre el segundo es menor que 0,3, te lo dice: la decisión es discutible.

> **Comprobar mi solución** mira cinco cosas en `respuestas.txt`:
> - las cuatro sobrecargas y los 40 B de IP+TCP;
> - los datos de la captura GOOSE (EtherType, stNum, primer reenvío, TAL y tiempo hasta la apertura);
> - los de DNP3 (puntos analógicos, índice y valor del evento);
> - los de DeviceNet (bits del identificador y esclavo que cambia);
> - la coherencia de la matriz.
>
> Las tablas de texto, la defensa y la discusión las evalúa el docente.
