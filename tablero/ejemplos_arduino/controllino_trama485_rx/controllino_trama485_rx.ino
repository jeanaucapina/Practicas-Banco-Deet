// Controllino MEGA, practica L3: receptor de la trama RS-485 propia (ver
// controllino_trama485_tx). Valida cabecera, direccion, longitud, XOR y cola;
// si todo cuadra copia los 3 bits a D0-D2. Si cruzas A/B recibe basura y lo dice.
#include <Controllino.h>

const byte YO = 2;

void setup() {
  Serial.begin(9600);
  Controllino_RS485Init(9600);
  Controllino_RS485RxEnable();
  pinMode(CONTROLLINO_D0, OUTPUT);
  pinMode(CONTROLLINO_D1, OUTPUT);
  pinMode(CONTROLLINO_D2, OUTPUT);
}

void loop() {
  byte t[6];
  Serial3.setTimeout(700);
  int n = Serial3.readBytes(t, 6);
  if (n == 6 && t[0] == 0xAA && t[5] == 0x55 && t[1] == YO && t[2] == 1 &&
      t[4] == (t[1] ^ t[2] ^ t[3])) {
    for (int i = 0; i < 3; i++) digitalWrite(CONTROLLINO_D0 + i, bitRead(t[3], i));
    Serial.print("trama valida: botones=");
    Serial.println(t[3], BIN);
  } else {
    Serial.print("trama invalida o ausente (");
    Serial.print(n);
    Serial.println(" bytes): revisa A/B");
    while (Serial3.available()) Serial3.read();    // resincronizar
  }
}
