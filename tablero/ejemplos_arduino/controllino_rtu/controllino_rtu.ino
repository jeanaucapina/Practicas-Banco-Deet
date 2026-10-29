// Controllino MEGA como MAESTRO Modbus RTU por RS-485, escrito a mano (sin
// librerias) para ver la trama byte a byte: cada segundo pide al esclavo 2
// (el Controllino del tablero 2, con su programa de fabrica) sus entradas
// discretas 16-18 (los pulsadores) con la funcion 02, y las copia en D0-D2.
// Cablea A+ con A+ y B- con B- entre los dos tableros.
#include <Controllino.h>

const byte ESCLAVO = 2;

uint16_t crc16(const byte* b, int n) {
  uint16_t crc = 0xFFFF;
  for (int i = 0; i < n; i++) {
    crc ^= b[i];
    for (int k = 0; k < 8; k++) crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
  }
  return crc;
}

void setup() {
  Serial.begin(9600);
  Controllino_RS485Init(9600);
  Controllino_RS485RxEnable();
  pinMode(CONTROLLINO_D0, OUTPUT);
  pinMode(CONTROLLINO_D1, OUTPUT);
  pinMode(CONTROLLINO_D2, OUTPUT);
}

void loop() {
  // Peticion: esclavo, FC 02, direccion 16, cantidad 3, CRC (bajo, alto)
  byte p[8] = {ESCLAVO, 0x02, 0x00, 16, 0x00, 3, 0, 0};
  uint16_t crc = crc16(p, 6);
  p[6] = lowByte(crc);
  p[7] = highByte(crc);

  while (Serial3.available()) Serial3.read();    // vaciar restos
  Controllino_RS485TxEnable();
  Serial3.write(p, 8);
  Serial3.flush();
  Controllino_RS485RxEnable();

  // Respuesta esperada: esclavo, 02, 1 byte, bits, CRC  = 6 bytes
  byte r[6];
  Serial3.setTimeout(300);
  int n = Serial3.readBytes(r, 6);
  if (n == 6 && r[0] == ESCLAVO && r[1] == 0x02 && crc16(r, 4) == (r[4] | (r[5] << 8))) {
    for (int i = 0; i < 3; i++) digitalWrite(CONTROLLINO_D0 + i, bitRead(r[3], i));
    Serial.print("pulsadores remotos: ");
    Serial.println(r[3], BIN);
  } else {
    Serial.print("sin respuesta valida (");
    Serial.print(n);
    Serial.println(" bytes): revisa el cableado A/B");
  }
  delay(1000);
}
