// Controllino MEGA: cada pulsador del panel enciende una fila de la matriz
// 3x3 y el potenciometro (en A0) marca el ritmo de parpadeo de D18.
// Mismo codigo en el tablero real (placa "CONTROLLINO MEGA" en el Arduino IDE)
// y en el virtual:  .\lab.ps1 subir t1.controllino ruta\controllino_filas.ino
#include <Controllino.h>

const int FILAS[3][3] = {
  {CONTROLLINO_D0, CONTROLLINO_D6, CONTROLLINO_D12},
  {CONTROLLINO_D1, CONTROLLINO_D7, CONTROLLINO_D13},
  {CONTROLLINO_D2, CONTROLLINO_D8, CONTROLLINO_D14},
};
const int PULSADORES[3] = {CONTROLLINO_I16, CONTROLLINO_I17, CONTROLLINO_I18};

unsigned long t_parpadeo = 0;
bool led = false;

void setup() {
  Serial.begin(9600);
  for (int f = 0; f < 3; f++) {
    pinMode(PULSADORES[f], INPUT);
    for (int c = 0; c < 3; c++) pinMode(FILAS[f][c], OUTPUT);
  }
  pinMode(CONTROLLINO_D18, OUTPUT);
  Serial.println("controllino_filas: listo");
}

void loop() {
  for (int f = 0; f < 3; f++) encenderFila(f, digitalRead(PULSADORES[f]) == HIGH);

  int pot = analogRead(CONTROLLINO_A0);          // 0..1023
  unsigned long periodo = map(pot, 0, 1023, 100, 1000);
  if (millis() - t_parpadeo > periodo) {
    t_parpadeo = millis();
    led = !led;
    digitalWrite(CONTROLLINO_D18, led);
    Serial.print("A0 = ");
    Serial.print(pot);
    Serial.print("  periodo = ");
    Serial.println(periodo);
  }
}

// Definida despues de loop(): como en el IDE, no hace falta declararla antes.
void encenderFila(int f, bool on) {
  for (int c = 0; c < 3; c++) digitalWrite(FILAS[f][c], on ? HIGH : LOW);
}
