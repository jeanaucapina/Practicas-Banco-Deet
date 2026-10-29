# L14 · OPC UA con Python: datalogger y termostato del tablero

*(Práctica 2 del manual de Informática Industrial, adaptada al tablero de comunicaciones.)*

Hasta ahora usaste software cerrado (UaExpert, SCADA) para hablar con los equipos. Aquí rompes esa barrera: con **Python** te conectas al tablero por OPC UA y lo tratas como una **fuente de datos abierta**. Es la base de la **convergencia IT/OT**:

- **Dataloggers propios:** datos en CSV, Excel o SQL sin licencias de *historian*.
- **Lógica que un PLC no hace fácil:** enviar un correo, consultar una API, avisar por Telegram.
- **Puente a la IA:** lo que registres hoy es la materia prima de un modelo predictivo mañana.

## Objetivo

Crear un programa propio que se conecte solo al servidor OPC UA del tablero, lea el potenciómetro cada segundo, lo guarde en un CSV y, como reto, **actúe** (termostato).

## Montaje

*Preparar el tablero* deja el ESP32 PLC encendido y **ya programado** con el servidor Modbus TCP de la L7 (no es lo que se evalúa). Los archivos quedan en `~/trabajo/L14` (`tablero\run\pc\L14`): el servidor OPC UA con su `modelo.json` **ya completo** (el de la L13) y la plantilla `datalogger.py`.

**Cablea tú el tablero 1** (esa es parte de la práctica; el docente tiene un botón que lo hace de golpe):

| # | Hilo | Desde | Hasta |
|---|---|---|---|
| 1 | Ethernet (RJ45) | PC | switch del tablero 1, puerto 1 |
| 2 | Ethernet (RJ45) | ESP32 PLC | switch del tablero 1, puerto 2 |
| 3 | Potenciómetro, hilo **amarillo** (SEÑAL) | módulo *potenciómetro* | borne **I0.7** del bloque MODULOS |
| 4 | Potenciómetro, hilo **rojo** (VCC) | módulo *potenciómetro* | **5V** |
| 5 | Potenciómetro, hilo **negro** (GND) | módulo *potenciómetro* | banana negra **GND** (arriba a la derecha del panel de bananas) |

Al preparar, los bornes quedan resaltados. Sin el cableado del potenciómetro, el registro [0] se queda en 0. El potenciómetro es **el mismo módulo** para el Controllino (L6: 24V y A0) y para el ESP32 (aquí: 5V, GND e I0.7).

«Preparar el tablero» **ya levanta tu servidor OPC UA** (tarda unos 40 s en estar listo la primera vez). Si lo apagas o quieres reiniciarlo:

```
cd tablero\run\pc\L14
docker compose -p l14 up -d        # «Preparar el tablero» ya bajó la pila de la L13 (usan el mismo puerto)
docker logs l14-opcua              # «con 9 variables»
```

Endpoint: `opc.tcp://localhost:4841/banco/`. Variables que usarás (NodeId numérico, `ns=2`):

| Variable | NodeId | Tipo | Qué es |
|---|---:|---|---|
| `Remote` | `ns=2;i=1010` | Boolean | control remoto: sin él el servidor rechaza tus escrituras |
| `Potenciometro` | `ns=2;i=1011` | UInt16 | I0.7, 0–1023 (lo mueves en el 3D) |
| `RelA` | `ns=2;i=1014` | Boolean | relé A (REL-A) |

## Parte A · Instalar y ejecutar el datalogger

Necesitas Python 3.7 o superior en tu computador:

```
pip install asyncua
```

(Si no tienes Python, `docker compose -p l14 run --rm cliente python datalogger.py` lo ejecuta dentro de Docker.)

Abre `datalogger.py`. Lee el potenciómetro y lo guarda con su marca de tiempo. **Ejecútalo en `tablero\run\pc\L14`**, para que `datos_planta.csv` quede ahí:

```
python datalogger.py
```

Mueve el potenciómetro en el 3D durante un minuto y detén el script con Ctrl+C. Abre el CSV en Excel.

**Pregunta A1:** ¿para qué sirve el `archivo.flush()` del script? Quítalo, ejecuta y mira cuándo aparecen las filas en el CSV.

## Reto · Termostato

Modifica el script para que actúe como un **termostato** (el potenciómetro hace de sensor y REL-A de ventilador):

- Obtén los nodos `Remote` y `RelA` y **escribe `True` en `Remote`** (sin esto el servidor rechaza tus escrituras: lo viste en la L13).
- Si el valor leído es **> 500**, escribe `True` en `RelA` (se cierra en el 3D); en caso contrario, `False`.
- Escribe solo cuando el estado deba **cambiar** (no cada segundo).

Pista: `await nodo_rele.write_value(True)`. **Deja el script corriendo** mientras pulsas «Comprobar mi solución»: el autocorrector mueve el potenciómetro y mira qué hace el relé.

**Ver la alarma funcionando (opcional pero recomendado).** Conecta una carga al relé que controla tu script:
- **Foco piloto de 24 V:** el **+** del FOCO 24 V (bandeja de componentes) a la borna **REL-A** de la bornera del carril (a la derecha del switch) y su **−** a **0V**. Se enciende cuando el relé A se cierra, y se apaga cuando se abre.
- **Motor:** el **+** del módulo MOTOR al borne **Q0.2** del bloque MODULOS y su **−** a **GND**. Gira mientras la salida Q0.2 vale 1: en UaExpert escribe `true` en el nodo `Q02` (con `Remote = true`) y míralo girar.


**Pulsadores.** El servidor ya publica `Pulsador1` (`ns=2;i=1019`) y `Pulsador2` (`ns=2;i=1020`), los pulsadores EXTRA1 y EXTRA2. Cablea cada uno (VCC a 5V; SEÑAL a I0.1 o I0.2) y pruébalos: puedes usar uno como pulsador de **paro de emergencia** en tu termostato (si está pulsado, abre el relé aunque el potenciómetro esté alto). **Un clic normal solo dura ~0,8 s** (como un pulsador real); con **Shift+clic** lo dejas **enclavado** hasta el siguiente clic, útil para probar tu lógica.

## Preguntas para el informe

1. **A1** (arriba).
2. Tu datalogger **pregunta** cada segundo (*polling*). ¿Qué ocurre con un cambio que dura 300 ms? ¿Cómo lo resolverías? (Pista: L15.)
3. ¿Qué pasa con tu termostato si el servidor se apaga? ¿Y si el PLC se desconecta (`plc: false`)? ¿Cómo lo harías robusto?
4. ¿Qué ventaja tiene guardar en CSV frente a un *historian* comercial? ¿Y qué desventaja?
5. El umbral 500 está cableado en el código. ¿Cómo lo leerías del propio servidor (`SetPoint_Alarma`, NodeId 1018)?

## Qué comprueba «Comprobar mi solución»

1. El PLC responde por Modbus.
2. Tu servidor OPC UA corre.
3. El servidor publica el modelo completo.
4. **Parte A** · `datos_planta.csv` existe, con cabecera `Fecha`, `Hora` y al menos 10 muestras.
5. **Reto** · con el potenciómetro por encima de 500, tu script cierra REL-A.
6. **Reto** · por debajo de 500, lo abre.
7. Tu script activó `Remote` y escribió por OPC UA.

## Entregable

Informe IEEE (LaTeX, doble columna) con: tu `datalogger.py` final, `datos_planta.csv`, una gráfica del potenciómetro con la acción del relé superpuesta, y las respuestas.
