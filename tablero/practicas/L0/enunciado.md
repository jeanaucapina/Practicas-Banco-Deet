# L0 · Reconocimiento del banco de control

Recorrido del banco sin energía, encendido en orden con medida de tensiones, la primera carga de firmware (el parpadeo de D0 en el Controllino y de Q0.0 en el ESP32 en sus dos modos) y la clasificación de cada elemento por nivel CIM, medio y protocolo. Sigue la guía (enlace arriba).

## Parte I · Dónde está cada cosa en el tablero 3D

| En la guía | En el 3D |
|---|---|
| Cinco interruptores (Fuente AC/DC, CONTROLLINO, ESP32 PLC14, HMI, Switch) | Panel trasero del tablero, «ENERGÍA» (gira la vista) |
| Matriz 3×3 de focos y pulsadores I16–I18 | Placa morada CONTROLLINO: filas D0 D6 D12 / D1 D7 D13 / D2 D8 D14 |
| Bornas de salida D0…D23 del Controllino | Fila de bornas verdes de arriba del Controllino («D0 … D23») |
| A0…A15, IN0, IN1, A(+)/B(−), GND y 5 V | Bandeja inclinada, bloque CONTROLLINO |
| Relés 4 y 5 (SPST), 8 y 9 con CMN (SPDT), REL-A/REL-B | Bornera del carril, a la derecha del switch |
| Bornero de distribución +24 V / 0 V | Bornera del carril, a la izquierda (rojas y azules) |
| ESP32 PLC 14: I0.1–I0.8, Q0.0–Q0.3, micro USB, RJ-45, antena | Frente del ESP32 (ventana) y bloque MÓDULOS de la bandeja |
| Multímetro, LED de 5 mm + 1 kΩ, foco de 24 V | Bandeja «COMPONENTES Y MULTÍMETRO», delante de los módulos |

## Parte II · Medir con el multímetro

El multímetro amarillo tiene sus dos puntas sueltas: **roja** (V/Ω) y **negra** (COM). Coge cada punta y enchúfala en el borne que quieras medir: bornera del carril, bornas D del Controllino, bananas de la placa morada y de la bandeja, bloque MÓDULOS o A/B del RS-485. Toca el selector para cambiar entre V⎓, Ω y continuidad.

Tabla L0.8 en el banco virtual:

- **Fila 1**: fuente, +24V contra 0V de la bornera.
- **Fila 5**: alimentación del ESP32, la misma de +24 V.
- **Filas 7–8**: borna D0 del Controllino contra 0V.
- **Filas 9 y 11**: Q0.0 (MÓDULOS) contra GND.
- **Fila 10**: A contra B del RS-485.

El banco no modela el puerto X1 ni la fuente propia de la HMI. Para esos puntos, anota el valor esperado y explica dónde lo medirías.

## Parte III · Primera carga

Conecta el USB del PC a cada PLC (lo deja hecho **Preparar el tablero**). Sube la **plantilla** (Listado L0.1) al **Controllino 1** y el ejemplo `l0_blink_esp32plc` (Listado L0.2), o el tuyo, al **ESP32 PLC 1**.

Monta la carga de la Tabla L0.6 con los hilos del **LED 5 mm + 1 kΩ**: + (ánodo) a **Q0.0** del bloque MÓDULOS y − a **GND**. Luce en la fase de 5 V. En la de 24 V el banco avisa de los ~22 mA, por encima de sus 20 mA: retíralo y pon el **FOCO 24 V**, como pide la guía.

> **Comprobar mi solución** reinicia el Controllino y mira cuatro cosas:
> - la traza del monitor serie;
> - que D0 esté 1 s encendido y 1 s apagado;
> - que el ESP32 parpadee Q0.0 primero con S0_24v en LOW (5 V)…
> - …y después en HIGH (24 V).
