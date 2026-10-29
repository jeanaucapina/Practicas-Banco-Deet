# L3 · Comunicación serial RS-485 con tramas propias

Bus RS-485 entre el **Controllino** (maestro, `Serial3` con `Controllino_RS485TxEnable/RxEnable`) y el **ESP32 PLC 14** (esclavo 0x01, `RS485.h` de Industrial Shields). Primero un eco de byte a 9600 baudios, después una **trama propia** (INICIO | DIR | CMD | LEN | DATOS | CRC-16) con su analizador como máquina de estados, y al final el diálogo semidúplex con timeout y reintentos. Sigue la guía (enlace arriba).

## El bus del banco virtual se comporta como el real

- Cada byte ocupa el par lo que dura a sus baudios: 1,04 ms a 9600 8N1.
- `Serial3.flush()` **espera** a que salga el último bit.
- Paso 8:
  - (a) Sin `Controllino_RS485RxEnable()` el maestro no oye nada.
  - (b) Sin `flush()`, el `RxEnable()` corta el último carácter (verás «trama truncada» o un eco erróneo).
- Paso 16: cambia los baudios de los dos nodos (19 200, 38 400). Si cambias **solo uno**, llega basura: es lo que lee la UART de verdad.
- V.3, dos maestros a la vez: el Controllino 2 puede ser el segundo maestro (cablea sus A/B al mismo par). Las tramas solapadas colisionan en el par y el CRC las rechaza.
- A/B cruzados (prueba a invertir un par en el 3D): la UART no sincroniza nunca.
- **Parte I y ensayo V.4, con componentes de verdad**: en la bandeja «COMPONENTES Y MULTÍMETRO» tienes dos resistencias de 120 Ω y dos de 560 Ω, con sus hilos.
  - Terminación: una de 120 Ω entre A y B de cada extremo; sus hilos entran en las bananas A/B y en los bornes A/B del ESP32.
  - Polarización: 560 Ω de A a 5V y 560 Ω de B a GND, en el bloque MÓDULOS.
  - El multímetro mide unos 60 Ω entre A y B con las dos terminaciones, ~120 con una y ~40 con tres. En V⎓ mide la tensión de reposo V_AB: ~0,25 V polarizado, ~0 sin polarizar.
  - Sin la terminación correcta, a **38 400 baudios** o más aparecen errores de CRC (V.4); a 9600–19 200 un par tan corto funciona igual, como en el real.
- La ida y vuelta medida incluye unos 4 ms del banco virtual (los procesos que mueven las tramas), además de las dos tramas y el proceso del esclavo: descuéntalos en el análisis de la sección i).

## Montaje

**Preparar el tablero** cablea A–A y B–B entre el Controllino (bananas A y B de la bandeja) y el ESP32 (bornes A/B del frente), y los dos USB de programación. Dos monitores serie: cambia de equipo en el portal.

## Programas

- Parte II: la **plantilla** es el maestro de eco (Listado L3.1); el esclavo de eco es el ejemplo `esp32plc_eco_485` (L3.2).
- Partes III y IV: los ejemplos `esp32plc_trama_esclavo` y `controllino_trama_maestro` son una solución de referencia; compárala con la tuya.
- La entrada I0.7 del ESP32 la mueve el módulo *potenciómetro* del 3D (hilo amarillo al borne I0.7 del bloque MÓDULOS).

> **Comprobar mi solución** necesita el sondeador de la Parte IV en el Controllino y tu esclavo en el ESP32. Mira que llegue A0 con su tiempo de ida y vuelta y que el valor sea el de I0.7. Después apaga el esclavo con su interruptor: deben salir los tres reintentos y «esclavo ausente». Al volver a encenderlo, el sondeo se tiene que recuperar solo.
