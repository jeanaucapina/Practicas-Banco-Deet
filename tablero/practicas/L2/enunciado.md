# L2 · HMI industrial STONE y motor con encoder (EPC)

El nivel de supervisión sobre el de control: una pantalla **STONE STWC050WT-01** (5", 800×480, RS-232 a 115 200 baudios) habla con el **Controllino** por `Serial2`. El Controllino manda el motor del **EPC** (Entrenador de Planta de Control) por PWM, mide su velocidad con el encoder (36 pulsos por vuelta) usando una interrupción externa y el **Timer1** en modo CTC, y la pinta en la HMI. Sigue la guía (enlace arriba).

## Parte I · STONE Designer

Herramientas → **Diseñador de HMI** (portal) es el STONE Designer del banco: página `home_page`, widgets con **nombre** y botón «Descargar a la HMI» (equivale al USB A–A + *download*). El botón **Ejemplo L2** trae la pantalla del Paso 3 ya hecha:

- `label1` a `label5`;
- `spin_box1` (0–100);
- `slider1` vertical;
- `chart_view1` con `line_series1` (duty, 0–100) y `line_series2` (rpm, 0–4000).

Hazla tú o parte de ella. Con «▶ Probar» la tocas con el ratón y ves las tramas reales: JSON `ST<{…}>ET` hacia la HMI, eventos binarios con CRC hacia el Controllino.

Cuando tu programa corre en el Controllino, **la HMI del tablero en el 3D muestra tu pantalla**, con los valores que manda tu `.ino`, y la puedes **tocar ahí mismo**: el slider, el spin_box (mitad izquierda resta, mitad derecha suma), los botones y los switch mandan su evento por Serial2. Con el programa de fábrica vuelve la pantalla de fábrica (las teclas de MODO).

## Parte II · Cableado X1 ↔ EPC (Tabla L2.5)

El EPC está en la mesa, delante de la bandeja de componentes: motor, disco del encoder y tres hilos. El puerto **X1** es el primer conector negro de pines del frente del Controllino, con D0, IN1, 5V y GND, todos a 5 V.

1. **GND MOTOR DC** → GND de X1. Siempre lo primero.
2. **IN MOTOR DC** → D0 de X1.
3. **MDC ENCODER** → IN1 de X1.

Si llevas el mando a la borna D0 de 24 V del Controllino, el banco te avisa (en el real lo dañarías).

## Programas

Usa las librerías del banco `Stone_HMI_Define.h` y `Procesar_HMI.h`, como en la guía. Ya están en el núcleo, no hay que copiarlas. Las funciones son:

- `Stone_HMI_Init()`
- `Uart_HMI_Data_Receive()`
- `HMI_get_value("spin_box", "spin_box1")`, que devuelve −1 si no hay dato nuevo
- `Stone_HMI_Set_Text("label4", buf)`
- `STONE_push_series("chart_view1", "line_series2", r)`

El núcleo del Controllino tiene el **Timer1** del ATmega2560 (`TCCR1A/B`, `OCR1A`, `TIMSK1`, `ISR(TIMER1_COMPA_vect)`, `noInterrupts()`) y `attachInterrupt(…, FALLING)` en IN1.

La **plantilla** es el Listado L2.1 (spin box → PWM). La solución de referencia de la Parte III es el ejemplo `controllino_stone_epc` (Listado L2.2).

> El motor del EPC tiene zona muerta (por debajo de ~12 % no gira) y una constante de tiempo de unos 0,35 s. A fondo da ~3800 rpm. Anótalo en la Tabla L2.8.

> **Comprobar mi solución** mira cuatro cosas:
> - que la HMI tenga los widgets de la Parte I y que el EPC esté cableado a X1;
> - que con `slider1` al 50 % `label4` muestre ~1600 rpm y que la gráfica reciba las dos series;
> - que la medida se renueve cada segundo;
> - que con el slider a 0 la lectura sea exactamente 0.
