// Practica L10 - Parte III (Listado L10.3): el ESP32 PLC 14 como pasarela entre el
// Controllino (esclavo Modbus 1 por RS-485) y LoRaWAN (nodo de clase A, US915 FSB 2).
// Autores: ...
#include <ModbusRTU.h>              // modbus-esp8266 (maestro, como en L6)
#include <RTClib.h>                 // DS3231 por I2C
#include <rn2xx3.h>                 // RN2483-Arduino-Library (jpmeijers)

#define LORA_SERIAL loraSerial      // nombre del puerto del slot LORA en este paquete de placas
#define SLAVE_ID 1
#define N_REGS 10                   // [0..7] canonicos + [8] A1 + [9] estado

// Identidades OTAA del servidor de red. En tu repositorio, en credenciales.h (.gitignore).
const char* JOIN_EUI = "0000000000000000";
const char* APP_KEY  = "00000000000000000000000000000000";

ModbusRTU mb;
RTC_DS3231 rtc;
rn2xx3 lora(LORA_SERIAL);
uint16_t reg[N_REGS];
uint8_t trama[9];
volatile bool listo = false;

bool cbLectura(Modbus::ResultCode ev, uint16_t, void*) {
  listo = (ev == Modbus::EX_SUCCESS);
  if (!listo) Serial.printf("Modbus error 0x%02X\n", ev);
  return true;
}

uint16_t aDecimas(uint16_t c) { return (uint32_t)c * 1000UL / 1023UL; }

void empaquetar() {
  // TODO (Fig. L10.4): byte 0 = VER (b7-b4) = 1 | A_T (b3) | A_N (b2); bytes 1-2 TEMP
  // (decimas, big-endian, de [0]); 3-4 NIV (de [8]); 5-8 marca de tiempo del DS3231.
}

void setup() {
  Serial.begin(115200);
  RS485.begin(19200, SERIAL_8N1);   // valores canonicos del banco
  mb.begin(&RS485); mb.master();
  rtc.begin();
  LORA_SERIAL.begin(57600);
  delay(1000);
  lora.autobaud();
  Serial.println(lora.hweui());     // DevEUI de fabrica: el que se registra
  Serial.println(lora.sysver());
  // TODO (Parte I): plan de frecuencias de la sub-banda 2 y union OTAA con reintento.
}

void loop() {
  if (!mb.slave()) {                // bus libre: nueva consulta
    listo = false;
    mb.readHreg(SLAVE_ID, 0, reg, N_REGS, cbLectura);       // FC3, base 0
  }
  mb.task(); yield();

  static uint32_t ultimo = 0;
  if (listo && millis() - ultimo >= 600000UL) {             // 1 envio / 10 min
    ultimo = millis();
    empaquetar();
    lora.txBytes(trama, sizeof(trama));                     // 9 B de FRMPayload
  }
}
