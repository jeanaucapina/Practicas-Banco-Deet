// Practica L7 - Parte I. Esbozo de red del ESP32 PLC 14 (Listado L7.2 de la guia):
// direccion estatica y puerto 502 a la escucha, SIN registros todavia.
// Validar la red (ping, arp, nc -vz) antes de escribir una sola linea de Modbus.
// Despues, Parte II: sustituirlo por el servidor con el mapa de ocho registros (Listado L7.3).
#include <ModbusEthernet.h>   // libreria modbus-esp8266 4.1.x

// MAC administrada localmente; el ultimo byte 0x0A = 10 recuerda a la IP
byte MAC[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0x0A };
IPAddress IP(192, 168, 1, 10), GW(192, 168, 1, 1), MASCARA(255, 255, 255, 0);
ModbusEthernet mb;

void setup() {
  Serial.begin(115200);
  Ethernet.begin(MAC, IP, GW, GW, MASCARA);   // DNS = pasarela: no se usa
  mb.server();                                // escucha en el puerto 502
  Serial.print(F("Servidor en "));
  Serial.println(Ethernet.localIP());
}

void loop() { mb.task(); }                    // motor de la pila Modbus
