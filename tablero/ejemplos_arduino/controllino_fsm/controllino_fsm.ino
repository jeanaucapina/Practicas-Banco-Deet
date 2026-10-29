// Controllino MEGA: maquina de estados (practica L1). Un semaforo de 3 estados
// sobre la matriz 3x3 de luces: cada pulsacion de I16 pasa al siguiente estado
// (VERDE -> AMARILLO -> ROJO -> VERDE) y I17 vuelve a VERDE. Cada estado enciende
// una fila de la matriz. Los cambios salen por el monitor serie.
// Mismo codigo en el tablero real (placa "CONTROLLINO MEGA") y en el virtual.
#include <Controllino.h>

enum Estado { VERDE, AMARILLO, ROJO };

// Filas de la matriz: arriba D0 D6 D12, medio D1 D7 D13, abajo D2 D8 D14
const int FILA[3][3] = {
  {CONTROLLINO_D0, CONTROLLINO_D6, CONTROLLINO_D12},
  {CONTROLLINO_D1, CONTROLLINO_D7, CONTROLLINO_D13},
  {CONTROLLINO_D2, CONTROLLINO_D8, CONTROLLINO_D14},
};
const char* NOMBRE[3] = {"VERDE", "AMARILLO", "ROJO"};

Estado estado = VERDE;
int antes_avanza = LOW;

void mostrar() {
  for (int f = 0; f < 3; f++)
    for (int c = 0; c < 3; c++)
      digitalWrite(FILA[f][c], f == (int)estado ? HIGH : LOW);
  Serial.print("estado: ");
  Serial.println(NOMBRE[estado]);
}

void setup() {
  pinMode(CONTROLLINO_I16, INPUT);
  pinMode(CONTROLLINO_I17, INPUT);
  for (int f = 0; f < 3; f++)
    for (int c = 0; c < 3; c++) pinMode(FILA[f][c], OUTPUT);
  Serial.begin(9600);
  mostrar();
}

void loop() {
  int avanza = digitalRead(CONTROLLINO_I16);
  if (avanza == HIGH && antes_avanza == LOW) {     // flanco de subida
    estado = (Estado)((estado + 1) % 3);
    mostrar();
  }
  antes_avanza = avanza;
  if (digitalRead(CONTROLLINO_I17) == HIGH && estado != VERDE) {
    estado = VERDE;
    mostrar();
  }
}
