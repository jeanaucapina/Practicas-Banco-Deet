// modbus-esp8266: Modbus TCP sobre WiFi (ESP32). Guia L9.
//   #include <ModbusIP_ESP8266.h>
//   ModbusIP mb; mb.server(); mb.addHreg(0); ... mb.task();
#pragma once
#include "WiFi.h"
#include "ModbusTCP.h"

class ModbusIP : public ModbusTCP {};
