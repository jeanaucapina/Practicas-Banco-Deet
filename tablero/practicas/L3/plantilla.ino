// Practica L3 - Parte II (Listado L3.1 de la guia): maestro de eco sobre RS-485.
// Habilitar transmision, escribir, flush() y volver a recepcion.
#include <Controllino.h>
const unsigned long BAUD_BUS = 9600UL;   // velocidad del bus RS-485
const unsigned long T_ESPERA = 100UL;    // ms de espera del eco
void setup() {
  Serial.begin(115200);                  // consola del monitor serie por USB
  Controllino_RS485Init();               // habilita los pines DE/RE del transceptor
  Serial3.begin(BAUD_BUS);               // el RS-485 del Controllino Mega es Serial3
  Controllino_RS485RxEnable();           // en reposo SIEMPRE en recepcion
}
void loop() {
  static byte dato = 0x41;               // recorre 'A'..'Z'
  while (Serial3.available()) Serial3.read();   // limpia restos del bus
  unsigned long t0 = micros(), t0ms = millis(); // reloj: primer bit emitido
  Controllino_RS485TxEnable();           // el transceptor toma la linea
  Serial3.write(dato);
  Serial3.flush();                       // ESPERA a que salga el ultimo bit
  Controllino_RS485RxEnable();           // devuelve el bus de inmediato
  while (!Serial3.available() && (millis() - t0ms) < T_ESPERA) { }
  if (Serial3.available()) {
    Serial.print(F("tx 0x")); Serial.print(dato, HEX);
    Serial.print(F(" rx 0x")); Serial.print(Serial3.read(), HEX);
    Serial.print(F(" ida y vuelta [us] = ")); Serial.println(micros() - t0);
  } else Serial.println(F("sin eco: vencio el tiempo de espera"));
  dato = (dato < 0x5A) ? dato + 1 : 0x41;
  delay(500);
}
