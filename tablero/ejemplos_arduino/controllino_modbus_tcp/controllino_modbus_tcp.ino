// Controllino MEGA, practica L7: maestro Modbus TCP escrito a mano sobre Ethernet.
// Cada segundo pide al otro Controllino (192.168.1.12, puerto 502) sus entradas
// discretas 16-18 (los pulsadores) con la funcion 02 y las copia en D0-D2. Las
// tramas MBAP salen en la captura de tab-lan (filtro `mbtcp`). Cablea el Ethernet
// de los dos Controllino al switch.
#include <Controllino.h>
#include <Ethernet.h>

byte mac[] = {0x02, 0x00, 0x00, 0x00, 0x00, 0x11};
IPAddress yo(192, 168, 1, 11);
IPAddress esclavo(192, 168, 1, 12);
EthernetClient cliente;
uint16_t transaccion = 0;

void setup() {
  Serial.begin(9600);
  Ethernet.begin(mac, yo);
  pinMode(CONTROLLINO_D0, OUTPUT);
  pinMode(CONTROLLINO_D1, OUTPUT);
  pinMode(CONTROLLINO_D2, OUTPUT);
}

void loop() {
  if (!cliente.connected()) {
    cliente.stop();
    if (!cliente.connect(esclavo, 502)) {
      Serial.println("sin conexion con 192.168.1.12:502: revisa el cable al switch");
      delay(1000);
      return;
    }
  }
  transaccion++;
  // MBAP: id transaccion(2) | protocolo 0(2) | longitud(2) | unidad(1), luego PDU
  byte q[12] = {highByte(transaccion), lowByte(transaccion), 0, 0, 0, 6, 1,
                0x02, 0x00, 16, 0x00, 3};
  cliente.write(q, 12);
  unsigned long t0 = millis();
  while (cliente.available() < 10 && millis() - t0 < 500) delay(5);
  if (cliente.available() >= 10) {
    byte r[10];
    for (int i = 0; i < 10; i++) r[i] = cliente.read();
    for (int i = 0; i < 3; i++) digitalWrite(CONTROLLINO_D0 + i, bitRead(r[9], i));
    Serial.print("pulsadores remotos: ");
    Serial.println(r[9], BIN);
  } else {
    Serial.println("sin respuesta del esclavo");
  }
  delay(1000);
}
