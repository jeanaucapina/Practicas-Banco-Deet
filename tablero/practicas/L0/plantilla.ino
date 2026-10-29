// L0 - Parte III - Verificacion de la cadena PC -> PLC -> actuador (Listado L0.1)
// Placa: Controllino MEGA | Salida: bornera D0 (24 V DC)
#include <Controllino.h>

const int SALIDA = CONTROLLINO_D0;      // foco de 24 V del tablero
const unsigned long T_ON = 1000;        // ms en estado alto
const unsigned long T_OFF = 1000;       // ms en estado bajo

void setup() {
  Serial.begin(9600);
  pinMode(SALIDA, OUTPUT);
  digitalWrite(SALIDA, LOW);
  Serial.println("L0: parpadeo de D0 iniciado");
}

void loop() {
  digitalWrite(SALIDA, HIGH);
  Serial.println("D0 = HIGH -> mida la bornera D0 contra 0 V");
  delay(T_ON);
  digitalWrite(SALIDA, LOW);
  Serial.println("D0 = LOW");
  delay(T_OFF);
}
