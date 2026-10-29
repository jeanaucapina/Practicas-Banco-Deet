# L15 · OPC UA · control ON/OFF con histéresis y migración de NodeIds

*(Práctica 3 del manual de Informática Industrial, adaptada al tablero de comunicaciones.)*

En la L14 tu script **preguntaba** cada segundo. En esta práctica construyes un controlador mejor: **se suscribe** y el servidor le avisa cuando algo cambia. Además cierras un lazo con **histéresis** y haces lo que más se hace en planta: **migrar** un cliente de un servidor a otro cambiando solo los identificadores de nodo.

> **El «proceso».** El tablero no tiene tanques: el proceso es el **potenciómetro del ESP32 PLC** (I0.7, 0–1023), que mueves en el 3D como si fuera el nivel de un depósito. El **controlador** es tu script, que corre en tu computador y habla con el tablero **solo por OPC UA**. El actuador es el **relé A** (REL-A), una alarma o ventilador.

## Objetivos

1. Implementar un cliente OPC UA con **suscripción** (monitored items) en Python.
2. Implementar control **ON/OFF con histéresis** (banda muerta) y entender para qué sirve.
3. **Migrar** el cliente de NodeIds de **texto** (gemelo digital) a NodeIds **numéricos** (planta real).

## Montaje

*Preparar el tablero* deja el ESP32 PLC encendido y **ya programado** con el servidor Modbus TCP de la L7 (no es lo que se evalúa). Los archivos quedan en `~/trabajo/L15` (`tablero\run\pc\L15`): el servidor OPC UA y la plantilla `control.py`. «Preparar el tablero» baja solo la pila de la práctica anterior (usan el mismo puerto); tus datos y archivos se conservan.

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
cd tablero\run\pc\L15
docker compose -p l15 up -d
docker logs l15-opcua              # «con 9 variables»
```

## Parte I · Controlador contra el «gemelo» (NodeIds de texto)

El servidor arranca en modo **`"nodeid": "texto"`** (en `modelo.json`): los nodos se llaman `ns=2;s=Tablero1.Potenciometro`, `ns=2;s=Tablero1.Remote`, `ns=2;s=Tablero1.RelA`. Así los publica un gemelo digital.

Completa `control.py`:

1. **Suscríbete** al potenciómetro con un periodo de 500 ms (`create_subscription` + `subscribe_data_change`).
2. Implementa la **histéresis**:
   - `pot > 700` → cierra REL-A (si no está cerrado);
   - `pot < 500` → lo abre (si está cerrado);
   - entre 500 y 700 **no hagas nada** (mantiene el estado).
3. Ejecuta (`pip install asyncua` si no lo tienes): `python control.py`. Mueve el potenciómetro en el 3D, de bajo a alto y de vuelta, y observa el relé.

**Pregunta I1:** ¿qué pasaría con un umbral único de 600 (sin banda) si el potenciómetro vibra alrededor de 600? ¿Qué ventaja tiene la histéresis?

**Ver la alarma funcionando (opcional pero recomendado).** Conecta una carga al relé que controla tu script:
- **Foco piloto de 24 V:** el **+** del FOCO 24 V (bandeja de componentes) a la borna **REL-A** de la bornera del carril (a la derecha del switch) y su **−** a **0V**. Se enciende cuando el relé A se cierra, y se apaga cuando se abre.
- **Motor:** el **+** del módulo MOTOR al borne **Q0.2** del bloque MODULOS y su **−** a **GND**. Gira mientras la salida Q0.2 vale 1: en UaExpert escribe `true` en el nodo `Q02` (con `Remote = true`) y míralo girar.


**Pulsadores.** El servidor publica además `Pulsador1` y `Pulsador2` (EXTRA1 y EXTRA2, NodeId 1019 y 1020, o `Tablero1.Pulsador1` en modo texto). Cablea uno (VCC a 5V; SEÑAL a I0.1) y úsalo como **paro de emergencia** suscribiéndote también a él: mientras esté pulsado, el relé debe abrirse sin importar el potenciómetro. **Un clic normal solo dura ~0,8 s** (como un pulsador real); con **Shift+clic** lo dejas **enclavado** hasta el siguiente clic, útil para probar tu lógica.

## Parte II · Migración a la «planta real» (NodeIds numéricos)

Una planta real publica sus nodos con identificadores **numéricos** (`ns=2;i=1011`), como en las prácticas anteriores. En un cliente bien hecho, migrar solo debería cambiar los identificadores.

1. En `modelo.json` cambia `"nodeid": "texto"` por `"nodeid": "numerico"` y reinicia: `docker restart l15-opcua`.
2. Tu script deja de funcionar: ¿qué error da? (Los NodeIds de texto ya no existen.)
3. Cambia **solo** las tres constantes `NODO_*` de `control.py`: `ns=2;i=1011` (potenciómetro), `ns=2;i=1010` (`Remote`), `ns=2;i=1014` (`RelA`).
4. Verifica que la respuesta del lazo es **la misma** que en la Parte I.

**Deja el script corriendo** mientras pulsas «Comprobar mi solución»: el autocorrector mueve el potenciómetro (900 → 600 → 300 → 600) y comprueba cada decisión de tu controlador.

## Reto de laboratorio

Registra el lazo y genera la gráfica de su respuesta: potenciómetro (con las bandas 500 y 700 marcadas) y estado de REL-A en el tiempo, durante un barrido de subida y bajada. Compárala con el comportamiento esperado de un control ON/OFF con histéresis y mide **cuántas conmutaciones** hace el relé con y sin banda muerta.

> **En el laboratorio real:** con el multitanque físico (`opc.tcp://10.21.162.10:4840`, solo en el Laboratorio de Sistemas de Control) el procedimiento es el mismo: solo cambian los NodeIds y la URL. Allí sé el único cliente conectado.

## Preguntas para el informe

1. **I1** (arriba).
2. ¿Qué diferencia hay, en tráfico y en retardo, entre tu controlador suscrito y el termostato con *polling* de la L14?
3. ¿Qué parte del código tuviste que tocar en la migración? ¿Qué otra información cambia entre un gemelo y una planta real (ruido, retardos, no linealidades)?
4. Si el cliente pierde la conexión con el servidor con el relé cerrado, ¿en qué estado queda el actuador? ¿Qué mecanismo de seguridad (*watchdog*, fallo seguro) agregarías?

## Qué comprueba «Comprobar mi solución»

1. El PLC responde por Modbus y tu servidor corre.
2. **Parte II** · el servidor usa NodeIds numéricos.
3. Tu controlador se **suscribió** al potenciómetro.
4. **Histéresis:** con pot > 700 cierra REL-A; con pot = 600 lo mantiene cerrado; con pot < 500 lo abre; y con pot = 600 de nuevo lo mantiene abierto.
5. El control llegó al PLC por OPC UA.

## Entregable

Informe IEEE (LaTeX, doble columna) con: tu `control.py` final, la gráfica del reto, la comparación gemelo / planta y las respuestas.
