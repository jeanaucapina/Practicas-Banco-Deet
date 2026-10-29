// Practica L9 - Parte I (Listado L9.1 de la guia): ESP32 PLC 14 en modo estacion,
// servidor web de diagnostico en el puerto 80 y servidor Modbus TCP con el mapa
// canonico de ocho registros holding de la Practica L7.
#include <WiFi.h>
#include <WebServer.h>
#include <ModbusIP_ESP8266.h>            // libreria modbus-esp8266, valida en ESP32

const char* ssid = "SSID_LAB";            // NO subir credenciales al repositorio
const char* password = "CLAVE_LAB";
// Direccion fija: un servidor no puede cambiar de direccion en cada arranque.
IPAddress ip(192, 168, 1, 10), gw(192, 168, 1, 1), mask(255, 255, 255, 0), dns(192, 168, 1, 1);
WebServer server(80);                     // Practica 6 del tablero: puerto 80
ModbusIP mb;                              // servidor Modbus TCP, puerto 502

void handle_estado() {                    // ruta /estado: diagnostico en JSON
  server.send(200, "application/json", "{\"ssid\":\"" + WiFi.SSID() + "\",\"ip\":\""
    + WiFi.localIP().toString() + "\",\"bssid\":\"" + WiFi.BSSIDstr() + "\",\"canal\":"
    + String(WiFi.channel()) + ",\"rssi\":" + String(WiFi.RSSI())
    + ",\"gw\":\"" + WiFi.gatewayIP().toString() + "\"}");
}
void handle_raiz() {                      // pagina minima de mando y diagnostico
  server.send(200, "text/html", "<html><body><h2>ESP32 PLC 14 - L9</h2><p>RSSI: "
    + String(WiFi.RSSI()) + " dBm | Canal: " + String(WiFi.channel())
    + "</p><p><a href='/releOn'>Rele ON</a> | <a href='/releOff'>Rele OFF</a></p></body></html>");
}
void handle_releOn() { mb.Hreg(4, 1); server.send(200, "text/plain", "OK ON"); }
void handle_releOff() { mb.Hreg(4, 0); server.send(200, "text/plain", "OK OFF"); }

void setup() {
  Serial.begin(115200); delay(3000);
  pinMode(Q0_1, OUTPUT); pinMode(S1_24v, OUTPUT);
  digitalWrite(S1_24v, HIGH);             // Q0.1 en modo Vdc: 24 V
  WiFi.mode(WIFI_STA);
  WiFi.config(ip, gw, mask, dns);         // comente esta linea para probar DHCP
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.printf("\nSSID %s | IP %s | canal %d | RSSI %d dBm\n", WiFi.SSID().c_str(),
                WiFi.localIP().toString().c_str(), WiFi.channel(), WiFi.RSSI());
  server.on("/", handle_raiz); server.on("/estado", handle_estado);
  server.on("/releOn", handle_releOn); server.on("/releOff", handle_releOff);
  server.begin();                         // servidor HTTP en el puerto 80
  mb.server();                            // arranca el servidor Modbus TCP (502)
  for (uint16_t i = 0; i < 8; i++) mb.addHreg(i, 0);   // el contrato: 8 holding
  Serial.println("HTTP en :80 y Modbus TCP en :502 con 8 holding registers");
}

void loop() {
  server.handleClient();                  // atiende el navegador
  mb.task();                              // atiende al cliente Modbus TCP
  mb.Hreg(0, analogRead(I0_7));           // [0] variable de proceso cruda
  mb.Hreg(1, digitalRead(Q0_1));          // [1] realimentacion de la salida digital
  digitalWrite(Q0_1, mb.Hreg(4) ? HIGH : LOW);   // [4] mando de la salida Q0.1
  delay(10);
}
