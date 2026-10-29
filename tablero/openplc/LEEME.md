# Programar en escalera (LD) y bloques (FBD) con OpenPLC

Es la forma de programar de TIA Portal (KOP/FUP): contactos, bobinas y bloques
unidos con líneas. Usa el estándar **IEC 61131-3** con herramientas libres, y
**todo viene en Docker: no hay que instalar nada**.

- **OpenPLC Editor**: dibujas el programa en LD, FBD, SFC, ST o IL. Corre en un
  contenedor y se usa **en el navegador** (escritorio virtual con noVNC).
- **OpenPLC Runtime**: la "CPU" que ejecuta tu programa. Hay una por tablero.

En el tablero, la CPU es OpenPLC y sus **entradas y salidas son las del
Controllino** de ese tablero, leídas y escritas por Modbus TCP cada 100 ms.
Es la arquitectura de planta "PLC + periferia descentralizada": pulsas I16 en
las gafas, OpenPLC lo lee por la red, ejecuta tu escalera y enciende las luces
del Controllino. En la pantalla del PC de las gafas ves las tramas
`OpenPLC1 -> CTL1 FC15 Write Multiple Coils…`.

## Ponerlo en marcha (desde el panel)

1. `.\lab.ps1 arrancar` abre el **panel del laboratorio**: <http://localhost:8090>.
2. En la tarjeta *Escalera y bloques · OpenPLC* pulsa **Encender editor y CPUs**.
3. **Abrir el editor gráfico** abre <http://localhost:6080>: el editor real, ya con
   un ejemplo (`marcha_paro`) abierto.
4. Dibujas, guardas (Ctrl+S) y pulsas el botón naranja **Generate program for
   OpenPLC Runtime**. El programa aparece en el panel.
5. **Cargar en T1** o **Cargar en T2**: se compila y la CPU queda en RUN. Los botones
   salen grises mientras las CPUs estén paradas (pulsa **Encender CPUs**).
6. **Apagar** cuando termines (ver abajo por qué).

**Atajo, sin ir al panel:** en la tarjeta *Escalera y bloques* elige en *«Al pulsar
la flecha naranja del editor, cargar en:»* el **Controllino 1**, el **2** o **los
dos**. Desde ese momento, cada vez que pulses la **flecha naranja ↓** del editor
(*Generate program for OpenPLC Runtime*), el panel enciende las CPUs si hacía
falta y carga el programa solo. Con *ninguna* vuelve a ser manual.

> **No uses el botón del chip** (*Transfer Program to PLC*): graba una **placa
> real** por USB (Controllino, ESP32…). El editor no ve los equipos virtuales; el
> atajo de arriba es el equivalente.

Tus proyectos se guardan en el PC, en `tablero/openplc/proyectos/` (los ejemplos,
en `proyectos/ejemplos/`); no se pierden al apagar.

Desde PowerShell, si prefieres: `.\lab.ps1 openplc` (enciende) y
`.\lab.ps1 openplc parar` (apaga). También sigue funcionando la web de cada CPU:
<http://localhost:8081> (tablero 1) y <http://localhost:8082> (tablero 2), usuario
`openplc`, clave `openplc`; en *Monitoring* ves tus variables en vivo.

**En las gafas**, enchufa el cable Ethernet del Controllino al switch y deja su
HMI en **ESCLAVO**.

**Mientras OpenPLC corre, manda él:** escribe las 24 salidas del Controllino
cada 100 ms. Por eso no arranca solo con `.\lab.ps1 arrancar`, y por eso hay que
apagarlo para los tutoriales o para otros modos del Controllino.

## Mapa de E/S (igual en los dos tableros)

| Dirección IEC | Controllino | |
|---|---|---|
| `%IX100.0` … `%IX100.7` | A0 … A7 | entradas, leídas como digitales |
| `%IX101.0` … `%IX101.7` | A8 … A15 | |
| `%IX102.0`, `%IX102.1`, `%IX102.2` | **pulsadores I16, I17, I18** | |
| `%IX102.3`, `%IX102.4` | IN0, IN1 | |
| `%QX100.0` … `%QX100.7` | D0 … D7 | salidas |
| `%QX101.0` … `%QX101.7` | D8 … D15 | |
| `%QX102.0` … `%QX102.7` | D16 … D23 | |
| `%IW100` … `%IW115` | A0 … A15 analógicas (0-1023) | p. ej. el potenciómetro |

Matriz 3x3 de luces: la fila de arriba es D0, D6, D12 (`%QX100.0`, `%QX100.6`,
`%QX101.4`); la del medio D1, D7, D13; la de abajo D2, D8, D14.

## Tu primer programa en escalera

1. En el editor (o parte del ejemplo `marcha_paro`): *Nuevo proyecto* → añade un **programa (POU) en lenguaje LD**.
2. En la tabla de variables declara, por ejemplo:
   - `MARCHA`, BOOL, ubicación `%IX102.0`
   - `PARO`, BOOL, ubicación `%IX102.2`
   - `MOTOR`, BOOL, ubicación `%QX102.2`
3. Dibuja el enclavamiento, conectado con líneas a las barras de alimentación:
   - en un escalón, el contacto `MARCHA` en paralelo con el contacto `MOTOR`;
   - en serie con ellos, el contacto **negado** `PARO`;
   - al final, la bobina `MOTOR`.
4. Pruébalo primero con el simulador del editor si quieres. Después:
   *Generate program for OpenPLC Runtime* (botón naranja de la barra).
5. En el panel: **Cargar en T1** (o T2). También vale subir un `.st` suelto con
   `.\lab.ps1 subir t1.openplc C:\ruta\programa.st`, o por la web de la CPU
   (*Programs → Upload Program → Launch program*, y *Start PLC*).
6. En las gafas: pulsa I16 y se enciende D18; pulsa I18 y se apaga.

### Ejercicio: pulsar un botón y que se encienda la matriz

El editor (<http://localhost:6080>) abre ya con la solución, `boton_matriz`, para
comparar. Para hacerlo tú, en un proyecto nuevo:

1. **File → New** y elige una carpeta nueva dentro de `/proyectos` (por ejemplo
   `/proyectos/mi_boton`). Añade un programa con el **+** gris del árbol del
   proyecto: nombre `mi_boton`, tipo *Program*, lenguaje **LD**.
2. En la tabla de variables (botón verde **+**), una fila por variable. Todas
   `Local`, tipo `BOOL`:

   | Name | Location | Qué es |
   |---|---|---|
   | `BOTON` | `%IX102.0` | pulsador I16 |
   | `D0` | `%QX100.0` | luz D0 |
   | `D1` | `%QX100.1` | luz D1 |
   | `D2` | `%QX100.2` | luz D2 |
   | `D6` | `%QX100.6` | luz D6 |
   | `D7` | `%QX100.7` | luz D7 |
   | `D8` | `%QX101.0` | luz D8 |
   | `D12` | `%QX101.4` | luz D12 |
   | `D13` | `%QX101.5` | luz D13 |
   | `D14` | `%QX101.6` | luz D14 |

3. Dibuja con la barra de herramientas del editor (herramientas: selección,
   mano, comentario, **riel de alimentación**, **contacto**, **bobina**, variable,
   bloque):
   - un riel de alimentación a la izquierda y otro a la derecha;
   - un **contacto** y elige `BOTON`;
   - una **bobina** y elige `D0`;
   - une con una línea arrastrando de un conector al siguiente:
     riel → contacto → bobina → riel derecho.
4. Prueba con **una** luz primero (arranca la CPU y pulsa I16). Luego copia la
   bobina (Ctrl+C / Ctrl+V), cámbiale la variable a `D1`, y conéctala **al
   mismo contacto** con otra línea (las bobinas quedan en paralelo) y a la barra
   derecha. Repite hasta las 9 luces.
5. Guarda (Ctrl+S) y pulsa el botón naranja **Generate program for OpenPLC
   Runtime**. Si algo está mal, la consola de abajo lo dice.
6. En el panel: **Encender CPUs** → **Cargar en T1**. En las gafas, con el cable del
   Controllino 1 al switch y su HMI en ESCLAVO, pulsa I16: se encienden las 9 luces.

El editor traduce tu escalera a texto estructurado; la de este ejercicio queda
`D0 := BOTON; D1 := BOTON; …`.

El ejemplo [ejemplos/filas.st](ejemplos/filas.st) hace eso mismo y además
enciende una fila de la matriz con cada pulsador. Está escrito en ST, que es lo
que el editor genera a partir del LD.

## Límites

- **No es TIA Portal.**
  - La idea es la misma: escalera, temporizadores `TON` y contadores `CTU` del
    estándar.
  - La interfaz y los nombres cambian; Siemens usa `%I0.0`, aquí `%IX102.0`.
  - No se carga en un S7: el S7-1200 simulado (`tab-s7`) tiene su propio programa fijo.
- Es la imagen `tuttas/openplc_v3`, una versión de 2019 basada en Python 2.
  - Un fallo suyo ya está sorteado en `preparar.py`: dividía por los baudios
    incluso en dispositivos TCP.
- El proyecto del editor se conserva en tu PC (`tablero/openplc/proyectos/`), pero el
  programa **cargado en la CPU** se pierde si se recrea el contenedor
  (`docker compose down`): vuelve a pulsar **Cargar**.
- El editor es la imagen `advian/openplc_editor` (OpenPLC Editor de 2024,
  Ubuntu 22.04) con un escritorio virtual encima; la primera vez se descarga
  (~1 GB) y se construye.
