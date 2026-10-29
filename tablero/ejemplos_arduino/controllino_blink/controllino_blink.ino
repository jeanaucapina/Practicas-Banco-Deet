// Blink para el Controllino MEGA: el "hola mundo" de Arduino.
// Hace parpadear D0 (la luz de arriba a la izquierda de la matriz 3x3) cada
// medio segundo, y cuenta los parpadeos por el monitor serie.
//
// Mismo codigo en el tablero real (placa "CONTROLLINO MEGA" en el Arduino IDE)
// y en el virtual. Para subirlo al virtual: panel (localhost:8090) > "Programar
// un equipo" > elegir este ejemplo, o
//   .\lab.ps1 subir t1.controllino tablero\ejemplos_arduino\controllino_blink\controllino_blink.ino
#include <Controllino.h>

const int LED = CONTROLLINO_D0;      // salida digital D0
const unsigned long MEDIO_SEGUNDO = 500;

int contador = 0;

void setup() {
  pinMode(LED, OUTPUT);
  Serial.begin(9600);
  Serial.println("blink: arrancando");
}

void loop() {
  digitalWrite(LED, HIGH);           // enciende
  delay(MEDIO_SEGUNDO);
  digitalWrite(LED, LOW);            // apaga
  delay(MEDIO_SEGUNDO);

  contador++;
  Serial.print("parpadeo n.");
  Serial.println(contador);
}
