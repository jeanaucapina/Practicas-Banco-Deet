# L13 · OPC UA · nivel de entrada: tu servidor del tablero y UaExpert

*(Práctica 1 del manual de Informática Industrial, adaptada al tablero de comunicaciones.)*

OPC UA es el estándar de interoperabilidad de la Industria 4.0. A diferencia de Modbus, que solo mueve registros de 16 bits sin nombre ni unidad, OPC UA ofrece **datos con significado**: un árbol de nodos con nombre, tipo, permisos y seguridad, y avisos por suscripción en vez de preguntar todo el tiempo. En esta práctica modelas el tablero como un **objeto OPC UA** y lo exploras con **UaExpert**, la herramienta de diagnóstico de referencia.

> **Qué es real y qué se emula.** El PLC es el **ESP32 PLC de la L7**, con su servidor Modbus TCP (192.168.1.10:502), sin tocar. El servidor OPC UA es un programa del banco (`servidor_opcua.py`, librería *asyncua*): una **pasarela Modbus ↔ OPC UA**, como las que hay en planta cuando un PLC sin OPC UA se conecta a un SCADA moderno. Tú defines **qué publica** en `modelo.json`. UaExpert es el programa real de Unified Automation.

## Objetivos

- **OE1.** Crear el objeto del tablero con sus variables (nombre, `NodeId`, tipo, permisos).
- **OE2.** Comprender los atributos de una variable OPC UA.
- **OE3.** Elegir un *endpoint* y entender qué ofrece cada política de seguridad.
- **OE4.** Ver la ventaja de la **suscripción** frente al *polling*, y escribir con un interbloqueo de control remoto.

## Montaje

*Preparar el tablero* deja el ESP32 PLC encendido y **ya programado** con el servidor Modbus TCP de la L7 (192.168.1.10:502): ese programa no es lo que se evalúa aquí, así que no hace falta que lo subas. Deja los archivos de la práctica en `~/trabajo/L13` (carpeta `tablero\run\pc\L13` de tu PC).

**Cablea tú el tablero 1** (esa es parte de la práctica; el docente tiene un botón que lo hace de golpe):

| # | Hilo | Desde | Hasta |
|---|---|---|---|
| 1 | Ethernet (RJ45) | PC | switch del tablero 1, puerto 1 |
| 2 | Ethernet (RJ45) | ESP32 PLC | switch del tablero 1, puerto 2 |
| 3 | Potenciómetro, hilo **amarillo** (SEÑAL) | módulo *potenciómetro* | borne **I0.7** del bloque MODULOS |
| 4 | Potenciómetro, hilo **rojo** (VCC) | módulo *potenciómetro* | **5V** |
| 5 | Potenciómetro, hilo **negro** (GND) | módulo *potenciómetro* | banana negra **GND** (arriba a la derecha del panel de bananas) |

Al preparar, los bornes quedan resaltados. Sin el cableado del potenciómetro, el registro [0] se queda en 0. El potenciómetro es **el mismo módulo** para el Controllino (L6: 24V y A0) y para el ESP32 (aquí: 5V, GND e I0.7).

Mapa de registros holding que ya conoces:

| Reg | Qué es |
|----:|--------|
| 0 | potenciómetro de I0.7, escalado a 0–1023 (lo mueves en el 3D) |
| 1 | realimentación del relé A |
| 3 | contador de escrituras recibidas |
| 4, 5, 6, 7 | relé A, relé B, Q0.2, Q0.3 (distinto de cero = cerrado) |

## Parte A · El modelo del tablero

La información del tablero se organiza así (**Tabla 1**; el `NodeId` es numérico, en el *namespace* `http://ucuenca.edu.ec/banco`, índice 2):

| Dispositivo | Variable | NodeId | Tipo | Registro | Permiso |
|---|---|---:|---|:---:|---|
| Control remoto | `Remote` | 1010 | Boolean | — (solo en el servidor) | lectura/escritura |
| Potenciómetro I0.7 | `Potenciometro` | 1011 | UInt16 | 0 | lectura |
| Realimentación del relé A | `RealimRelA` | 1012 | Boolean | 1 | lectura |
| Escrituras recibidas | `Escrituras` | 1013 | UInt16 | 3 | lectura |
| Relé A | `RelA` | 1014 | Boolean | 4 | lectura/escritura |
| Relé B | `RelB` | 1015 | Boolean | 5 | lectura/escritura |
| Salida Q0.2 | `Q02` | 1016 | Boolean | 6 | lectura/escritura |
| Salida Q0.3 | `Q03` | 1017 | Boolean | 7 | lectura/escritura |

`Remote` hace de **interbloqueo**: mientras valga `false`, el servidor **rechaza** las escrituras de los clientes hacia el PLC.

1. Abre `~/trabajo/L13/modelo.json`. Solo trae `Remote` y `Potenciometro`.
2. **Añade las seis variables que faltan** de la Tabla 1, con el mismo formato (`nombre`, `nodeid`, `tipo`, `registro`, `escribible`).
3. Levanta (o reinicia) el servidor y revisa que arranque sin errores:

«Preparar el tablero» **ya levanta tu servidor OPC UA** (tarda unos 40 s en estar listo la primera vez). Si lo apagas o quieres reiniciarlo:

```
cd tablero\run\pc\L13
docker compose -p l13 up -d        # la primera vez instala asyncua (~30 s)
docker restart l13-opcua           # cada vez que cambies modelo.json
docker logs l13-opcua              # debe decir «con 8 variables» (si no, dice qué falla)
```

## Parte B · Endpoints y seguridad

1. Instala y abre **UaExpert** (gratuito con registro en Unified Automation).
2. Menú **Server → Add…**. En *Custom Discovery* haz doble clic en *Double click to Add Server…* y escribe `opc.tcp://localhost:4841/banco/`. Pulsa Enter y despliega la flecha `>`.
3. Observa las opciones de conexión (**endpoints**) que ofrece el servidor:
   - **None** (inseguro)
   - **Basic256Sha256 – Sign** (firmado)
   - **Basic256Sha256 – Sign & Encrypt** (firmado y cifrado)
4. Para esta primera prueba elige **None – None** (*Anonymous*) y **OK**.
5. Clic derecho sobre el servidor → **Connect**.
6. **Repite con Sign & Encrypt:** UaExpert pide confiar en el certificado del servidor (autofirmado, en `pki/`). Mira sus datos antes de aceptar. ¿Por qué hay que confiar en él manualmente?

## Parte C · Navegar el *Address Space*

1. Despliega **Root → Objects → Tablero1**. Verás las variables que modelaste.
2. Diferencia visual: icono de bloque = *Object* (agrupador); icono de etiqueta = *Variable* (dato final).
3. Selecciona `RelA` y mira el panel **Attributes**. Anota **NodeId**, **DataType**, **AccessLevel**/**UserAccessLevel** y **Value**. Compáralos con `Potenciometro`.
4. Arrastra todas las variables al panel central (*Data Access View*). Observa la columna **Status** (`Good`); si apagas el servidor (`docker compose -p l13 stop`) pasa a `Bad`.
5. Mueve el potenciómetro en el 3D: `Potenciometro` cambia **sin que preguntes** (es una suscripción).

## Parte D · Escritura e interbloqueo

1. Con `Remote = false`, escribe `true` en `RelA` (doble clic sobre su *Value*, o clic derecho → *Write…*). **El servidor lo rechaza**: el valor vuelve a `false`. El relé del tablero no se mueve.
2. Escribe `true` en `Remote` y vuelve a escribir `true` en `RelA`. Ahora el relé **se cierra en el 3D**, y puedes verlo por Modbus: `mbpoll -m tcp -a 1 -t 4 -0 -r 4 -c 4 -1 192.168.1.10` (terminal del PC) muestra `[4]: 1`.
3. Intenta escribir en `Potenciometro` (solo lectura): ¿qué código de estado devuelve el servidor?

**Ver la alarma funcionando (opcional pero recomendado).** Conecta una carga al relé que controla tu script:
- **Foco piloto de 24 V:** el **+** del FOCO 24 V (bandeja de componentes) a la borna **REL-A** de la bornera del carril (a la derecha del switch) y su **−** a **0V**. Se enciende cuando el relé A se cierra, y se apaga cuando se abre.
- **Motor:** el **+** del módulo MOTOR al borne **Q0.2** del bloque MODULOS y su **−** a **GND**. Gira mientras la salida Q0.2 vale 1: en UaExpert escribe `true` en el nodo `Q02` (con `Remote = true`) y míralo girar.


**Probar con los pulsadores (opcional).** El programa del PLC también lee los dos pulsadores extra (I0.1 y I0.2) en los registros [8] y [9]. Añade a tu `modelo.json` `Pulsador1` (NodeId **1019**, Boolean, registro **8**, solo lectura) y `Pulsador2` (NodeId **1020**, registro **9**), reinicia el servidor y cablea cada pulsador: hilo **VCC** a **5V** y **SEÑAL** al borne **I0.1** (EXTRA1) o **I0.2** (EXTRA2) del bloque MODULOS. Al pulsar en el 3D, el nodo pasa a `true` en UaExpert sin que preguntes. **Un clic normal solo dura ~0,8 s** (como un pulsador real); con **Shift+clic** lo dejas **enclavado** hasta el siguiente clic, útil para probar tu lógica.

## Reto de laboratorio

El tablero tiene una **anomalía**: el potenciómetro (nivel) no debe pasar de un umbral.

1. Crea en `modelo.json` una variable `SetPoint_Alarma` (**NodeId 1018**, UInt16, **escribible**, `valor` inicial 800; no tiene registro: vive solo en el servidor).
2. Con UaExpert monitoriza `Potenciometro` y `SetPoint_Alarma`.
3. Observa los datos durante 1 minuto moviendo el potenciómetro.
4. Genera con UaExpert un **gráfico** (*Trend View*) con ambas señales superpuestas y captúralo para el informe.

## Preguntas para el informe

1. **Identificación:** copia el `NodeId` exacto de `Potenciometro`. ¿Qué significa `ns=2`?
2. **Tipos de datos:** según Attributes, ¿es `Potenciometro` entero o decimal? ¿Y `RelA`? ¿Por qué `RelA` es Boolean si en Modbus es un registro de 16 bits?
3. **Diagnóstico:** si la columna *Status Code* se pone en rojo y dice `BadConnectionRejected`, ¿qué crees que está pasando con el servidor?
4. **Seguridad:** ¿qué amenazas cubre *Sign* y cuáles *Sign & Encrypt*? ¿Qué pasa con `None`? Relaciónalo con la U6.
5. **Suscripción:** con Modbus, ¿cuántas peticiones por segundo haría un cliente para ver cambiar 5 variables al ritmo de 500 ms? ¿Y con una suscripción OPC UA?

## Qué comprueba «Comprobar mi solución»

1. El PLC responde por Modbus (192.168.1.10:502).
2. Tu servidor OPC UA corre y escucha en 192.168.1.64:4841.
3. El servidor ve al PLC por Modbus.
4. **OE1** · tu `modelo.json` define las ocho variables de la Tabla 1 con sus NodeId.
5. **Reto** · creaste `SetPoint_Alarma` (1018, UInt16).
6. Te conectaste con un cliente OPC UA y exploraste.
7. Se creó una suscripción (UaExpert la crea al arrastrar nodos al *Data Access View*).
8. Intentaste escribir con `Remote = false` y el servidor lo rechazó.
9. Con `Remote = true`, una escritura OPC UA llegó al PLC.

El servidor cuenta conexiones, suscripciones, escrituras y rechazos desde que arrancó: **no lo reinicies justo antes de comprobar** y deja UaExpert abierto. Si lo reinicias para cambiar el modelo, repite las pruebas de las Partes C y D. Estado del servidor, para depurar: `curl http://192.168.1.64:8096/api/estado` desde la terminal del PC.

## Entregable

Informe IEEE (LaTeX, doble columna) con: capturas de UaExpert (árbol de nodos, *Attributes*, *Data Access View*, la escritura rechazada y la aceptada, y la gráfica del reto), tu `modelo.json` final y las respuestas a las preguntas.
