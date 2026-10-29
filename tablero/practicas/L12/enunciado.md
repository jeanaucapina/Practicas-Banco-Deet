# L12 · Comunicación entre tableros: RS-485 y Ethernet entre dos bancos

En las guías L3, L6 y L7 los equipos que hablan están en el **mismo tablero**. Aquí se unen **dos tableros distintos**: el Controllino del tablero 1 hace de maestro y el Controllino del tablero 2 de esclavo, primero por **RS-485** y después por **Ethernet**. Así se ve qué hace falta en cada medio para que dos bancos se hablen.

| | Tablero 1 | Tablero 2 |
|---|---|---|
| Controllino | **maestro** (MODO 3 = RS-485, MODO 4 = TCP) | **esclavo** (MODO 0), dirección RTU 2 |
| IP | 192.168.1.11 | 192.168.1.12 |
| Switch | el suyo | el suyo |

Cada switch es **una red aparte**. Mientras no los una un cable, el tablero 1 no ve al tablero 2: ni ping, ni Modbus TCP, ni ARP. En el laboratorio pasa lo mismo: dos switches sin enlace son dos LAN distintas.

Los programas son los de **fábrica**: no hay que subir nada. El maestro manda un **FC 15** (escribir bobinas 0-14) cada vez que cambia un pulsador, y una vez por segundo para refrescar. La fila remota sigue al pulsador: se enciende **mientras lo mantienes apretado**.

- **I16** del tablero 1 enciende la fila de arriba del tablero 2 (D0, D6, D12);
- **I17** enciende la del medio (D1, D7, D13);
- **I18** enciende la de abajo (D2, D8, D14).

## Montaje

*Preparar el tablero* deja hecho lo de **cada** tablero:

- el Controllino 1 al puerto 1 del switch del tablero 1;
- el PC al puerto 2 del switch del tablero 1;
- el Controllino 2 al puerto 1 del switch del tablero 2;
- los dos Controllino en MODO 0.

Los cables **entre** tableros los pones tú. En el 3D están marcados.

## Parte A · RS-485 entre tableros

1. Une los bornes del bus: **485A del Controllino 1 con 485A del Controllino 2**, y **485B con 485B**. Si los cruzas (A con B), el maestro solo recibe silencio.
2. En la HMI del tablero 1 toca **MAESTRO 485**.
3. Pulsa **I16** del tablero 1: se enciende la fila de arriba del tablero 2.

El RS-485 no pasa por los switches: es un par de hilos entre los dos equipos. Por eso funciona aunque las dos redes Ethernet estén separadas.

## Parte B · Ethernet entre tableros

1. Antes de unir nada, desde la **Terminal del PC** prueba `ping -c 4 192.168.1.12`. No llega: el PC está en la red del tablero 1.
2. En la HMI del tablero 1 toca **MAESTRO TCP** y pulsa I17. No pasa nada: el maestro cuenta peticiones **sin respuesta** (registro holding 5).
3. Pon un **latiguillo entre los switches**: puerto 4 del tablero 1 ↔ puerto 4 del tablero 2.
4. Repite el `ping` (ahora sí responde) y pulsa I17: se enciende la fila del medio del tablero 2.
5. Quita el latiguillo y vuelve a pulsar: el maestro se queda otra vez sin respuesta.

En Wireshark (red LAN) verás la conexión TCP al puerto 502 del 192.168.1.12 con el FC 15 dentro de la cabecera MBAP.

## Parte C · Hoja

Rellena `~/trabajo/L12/respuestas.txt` (carpeta `tablero/run/pc/L12`):

- el porcentaje de pérdida del ping sin latiguillo y con latiguillo;
- cuántas peticiones quedaron sin respuesta en MAESTRO TCP sin latiguillo;
- en una frase, por qué el RS-485 entre tableros no necesita los switches.

## Qué comprueba «Comprobar mi solución»

1. **Parte A**: pone al Controllino 1 en MAESTRO 485, pulsa I16 y mira que el tablero 2 encienda D0, D6 y D12.
2. **Parte A**: que esa orden haya ido por Modbus RTU.
3. **Parte B**: que el PC del tablero 1 alcance al 192.168.1.12. Para eso **el latiguillo entre switches tiene que estar puesto**.
4. **Parte B**: pone MAESTRO TCP, pulsa I17 y mira D1, D7 y D13 del tablero 2.
5. **Parte B**: que esa orden haya ido por Modbus TCP.
6. **Parte C**: la hoja.

Para que los pasos 1 a 5 pasen a la vez, deja puestos **el bus RS-485 y el latiguillo** al comprobar.
