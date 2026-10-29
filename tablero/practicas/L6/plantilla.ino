// Practica L6 - Parte III (Listado L6.2 de la guia): maestro Modbus RTU en el ESP32 PLC 14,
// sondeo con FC3 y automata con timeout y reintentos.
#define MODBUSRTU_TIMEOUT 5000          // ANTES del include: lo compila la libreria
#include <ModbusRTU.h>                  // libreria modbus-esp8266
// Puerto RS-485 del ESP32 PLC 14 (GPIO 16/17, DE/RE por hardware: PIN_DE485 = -1).
const int8_t PIN_RX485 = 16, PIN_TX485 = 17, PIN_DE485 = -1;
const uint8_t ESCLAVO = 1, MAX_REINTENTOS = 3;
const uint16_t N_REGS = 8;
const unsigned long T_SONDEO = 500UL, T_TIMEOUT = 5000UL;   // sondeo y guarda [ms]
ModbusRTU mb;
uint16_t regs[N_REGS];
volatile bool enCurso = false;
volatile Modbus::ResultCode ultimo = Modbus::EX_SUCCESS;
enum Estado : uint8_t { ESPERA, SONDEO, FALLO };
Estado estado = ESPERA; unsigned long t_estado = 0; uint8_t reintentos = 0;

bool cbTransaccion(Modbus::ResultCode ev, uint16_t tid, void* datos) {
  ultimo = ev; enCurso = false; return true;
}
// Aqui muere el codigo de retorno de un bus sin protocolo y nace el
// diagnostico tipificado: cada excepcion dice QUE ha fallado.
void diagnosticar(Modbus::ResultCode ev) {
  Serial.print(F("resultado 0x")); Serial.print(ev, HEX); Serial.print(F(" -> "));
  switch (ev) {
    case Modbus::EX_SUCCESS:          Serial.println(F("OK")); break;
    case Modbus::EX_ILLEGAL_FUNCTION: Serial.println(F("exc 01 funcion ilegal")); break;
    case Modbus::EX_ILLEGAL_ADDRESS:  Serial.println(F("exc 02 direccion ilegal")); break;
    case Modbus::EX_ILLEGAL_VALUE:    Serial.println(F("exc 03 valor ilegal")); break;
    case Modbus::EX_SLAVE_FAILURE:    Serial.println(F("exc 04 fallo del esclavo")); break;
    case Modbus::EX_TIMEOUT:          Serial.println(F("TIMEOUT: esclavo ausente")); break;
    default:                          Serial.println(F("codigo interno")); break;
  }
}

void setup() {
  Serial.begin(115200);
  Serial1.begin(19200, SERIAL_8N1, PIN_RX485, PIN_TX485);
  mb.begin(&Serial1, PIN_DE485); mb.master();     // este nodo impone el turno
  t_estado = millis();
  Serial.println(F("Maestro Modbus RTU listo: 19200 8N1, esclavo 1"));
}

void loop() {
  mb.task();                                      // motor interno de la libreria
  switch (estado) {
    case ESPERA:                                  // el bus descansa entre transacciones
      if (millis() - t_estado >= T_SONDEO) {
        mb.readHreg(ESCLAVO, 0x0000, regs, N_REGS, cbTransaccion);   // FC3
        enCurso = true; t_estado = millis(); estado = SONDEO;
      }
      break;
    case SONDEO:                                  // se espera la ADU de respuesta
      if (!enCurso) {
        diagnosticar(ultimo);
        if (ultimo == Modbus::EX_SUCCESS) {
          reintentos = 0;
          for (uint8_t i = 0; i < N_REGS; i++) {
            Serial.print(F("[")); Serial.print(i);
            Serial.print(F("]=")); Serial.print(regs[i]); Serial.print(F(" "));
          }
          Serial.println();
        } else if (++reintentos >= MAX_REINTENTOS) { estado = FALLO; break; }
        t_estado = millis(); estado = ESPERA;
      } else if (millis() - t_estado >= T_TIMEOUT) {
        ultimo = Modbus::EX_TIMEOUT; enCurso = false;   // guarda propia
      }
      break;
    case FALLO:                                   // solo se sale por rearme explicito
      Serial.println(F("FALLO: 3 reintentos sin respuesta. Rearme manual."));
      delay(2000); break;
  }
}
