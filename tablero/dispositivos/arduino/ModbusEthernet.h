// modbus-esp8266: Modbus TCP sobre Ethernet (W5500 del ESP32 PLC 14). Guia L7.
//   #include <ModbusEthernet.h>
//   ModbusEthernet mb; mb.server(); mb.addHreg(0); ... mb.task();
#pragma once
#include "Ethernet.h"
#include "ModbusTCP.h"

class ModbusEthernet : public ModbusTCP {};
