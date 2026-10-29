// Controllino MEGA, practica L3: trama RS-485 PROPIA (sin Modbus). Cada 500 ms
// manda una trama de 6 bytes con el estado de los pulsadores:
//   0xAA | direccion destino | longitud | pulsadores (bits 0-2) | XOR | 0x55
// Cablea A+ con A+ y B- con B- hacia el otro tablero y carga controllino_trama485_rx
// en el otro Controllino. Para analizarla: captura tab-485 en Wireshark.
#include <Controllino.h>

const byte DESTINO = 2;

void setup() {
  Serial.begin(9600);
  Controllino_RS485Init(9600);
  pinMode(CONTROLLINO_I16, INPUT);
  pinMode(CONTROLLINO_I17, INPUT);
  pinMode(CONTROLLINO_I18, INPUT);
}

void loop() {
  byte botones = digitalRead(CONTROLLINO_I16) | (digitalRead(CONTROLLINO_I17) << 1) |
                 (digitalRead(CONTROLLINO_I18) << 2);
  byte trama[6] = {0xAA, DESTINO, 1, botones, 0, 0x55};
  trama[4] = trama[1] ^ trama[2] ^ trama[3];       // XOR de direccion, longitud y datos
  Controllino_RS485TxEnable();
  Serial3.write(trama, 6);
  Serial3.flush();
  Controllino_RS485RxEnable();
  Serial.print("enviada: botones=");
  Serial.println(botones, BIN);
  delay(500);
}
