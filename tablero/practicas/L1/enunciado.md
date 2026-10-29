# L1 · E/S digitales, rebote y máquina de estados

Ciclo de scan y salidas sin bloqueo sobre los nueve focos, medida del **rebote** de los pulsadores y su antirrebote por software, conmutación de una carga con el **relé 4**, y el cruce de dos semáforos como **máquina de estados** con estado de fallo. Sigue la guía (enlace arriba).

## Lo propio del banco virtual

- **La matriz del tablero real** (mira el panel CONTROLLINO del 3D):
  - fila de arriba D0 D6 D12 (rojos), fila del medio D1 D7 D13 (ámbar), fila de abajo D2 D8 D14 (verdes);
  - pulsadores I16, I17 e I18 a la derecha;
  - debajo, las bananas D3…D20 y GND.

  La guía numera la matriz «en orden de lectura» D0, D1, D2…, pero en el tablero esa secuencia baja por la **columna** izquierda. Tenlo en cuenta para la espiral del Reto.
- **Los pulsadores rebotan** como los reales, sin antirrebote de fábrica:
  - al pulsar, entre 2 y 8 flancos espurios en 1–5 ms;
  - al soltar, menos.

  Con el medidor del Listado L1.3 (ejemplo `controllino_rebote`) los verás en el monitor serie; con el antirrebote de L1.4, diez pulsaciones cuentan diez. Pulsa en el 3D, o desde el panel del portal.
- **Tiempo de ciclo** (Listado L1.2): un `loop()` vacío del núcleo virtual ronda los pocos microsegundos; compáralo con el `delay(500)` del Paso 3.
- **Relé 4 con carga** (Parte III, Tabla L1.4): en la bornera del carril, a la derecha del switch, tienes +24V, 0V y los dos bornes de «Relay 4». Haz un puente de +24V a un borne del relé (coge un borne y suéltalo en el otro). Lleva el + del **FOCO 24 V** de la bandeja de componentes al otro borne y su − a 0V. Antes de energizar, comprueba la continuidad con el multímetro (selector en ·)))). El foco solo luce con el relé cerrado.

## Programas

La **plantilla** es la secuencia del Listado L1.1. Ejemplos de referencia: `controllino_rebote` (L1.3) y `controllino_semaforo` (L1.4 + L1.5, el cruce completo, que además imprime cada cambio de estado).

> **Comprobar mi solución** necesita el cruce de la Parte IV cargado y reinicia el Controllino para empezar en A_VERDE. Cronometra 8 s de verde y 2 s de ámbar, mira el latido de D14 y que nunca coincidan D2 y D8. Después pulsa I18 (intermitente ámbar con D13) e I16 (vuelve a A_VERDE), con el rebote de verdad.
