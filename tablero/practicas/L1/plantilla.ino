// Practica L1 - Parte I (Listado L1.1 de la guia): secuencia sobre los nueve focos con
// arreglo y temporizacion no bloqueante. Partes II-IV: amplialo con el antirrebote
// (L1.4) y la maquina de estados del cruce (L1.5).
#include <Controllino.h>
// Los nueve focos de la matriz 3x3 del tablero
const uint8_t LEDS[9] = {
  CONTROLLINO_D0, CONTROLLINO_D1, CONTROLLINO_D2,
  CONTROLLINO_D6, CONTROLLINO_D7, CONTROLLINO_D8,
  CONTROLLINO_D12, CONTROLLINO_D13, CONTROLLINO_D14 };
const uint8_t N_LEDS = 9;
const unsigned long T_PASO = 500UL;   // ms encendido cada foco
unsigned long t_ultimo = 0;           // instante del ultimo cambio
uint8_t indice = 0;                   // foco activo en este momento

void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < N_LEDS; i++) { pinMode(LEDS[i], OUTPUT); }
  digitalWrite(LEDS[0], HIGH); t_ultimo = millis();
}

void loop() {
  unsigned long ahora = millis();
  // Resta sin signo: inmune al desbordamiento de millis()
  if (ahora - t_ultimo >= T_PASO) {
    t_ultimo += T_PASO;               // base de tiempo sin deriva
    digitalWrite(LEDS[indice], LOW);
    indice = (indice + 1) % N_LEDS;
    digitalWrite(LEDS[indice], HIGH);
  }
  // El lazo queda libre: aqui cabria leer entradas o atender el bus
}
