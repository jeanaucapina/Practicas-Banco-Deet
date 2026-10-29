// Controllino MEGA, lo mas sencillo posible: mientras pulsas el boton I16 del
// panel se enciende toda la matriz 3x3 de luces; al soltarlo se apaga.
// Mismo codigo en el tablero real (placa "CONTROLLINO MEGA" en el Arduino IDE)
// y en el virtual:  .\lab.ps1 subir t1.controllino tablero\ejemplos_arduino\controllino_boton\controllino_boton.ino
#include <Controllino.h>

// Las 9 luces de la matriz 3x3 (D0, D1, D2 / D6, D7, D8 / D12, D13, D14)
const int LUCES[9] = {
  CONTROLLINO_D0, CONTROLLINO_D1, CONTROLLINO_D2,
  CONTROLLINO_D6, CONTROLLINO_D7, CONTROLLINO_D8,
  CONTROLLINO_D12, CONTROLLINO_D13, CONTROLLINO_D14,
};

void setup() {
  pinMode(CONTROLLINO_I16, INPUT);          // el boton
  for (int i = 0; i < 9; i++) {
    pinMode(LUCES[i], OUTPUT);              // las luces
  }
  Serial.begin(9600);
  Serial.println("listo: pulsa I16");
}

void loop() {
  int pulsado = digitalRead(CONTROLLINO_I16);    // HIGH = pulsado
  for (int i = 0; i < 9; i++) {
    digitalWrite(LUCES[i], pulsado);
  }
}
