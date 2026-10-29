// Modbus TCP de modbus-esp8266 en el tablero virtual (ModbusEthernet / ModbusIP):
// servidor en el 502 con hasta MODBUSIP_MAX_CLIENTS conexiones a la vez (8: la
// novena se acepta y se cierra en el acto, como la libreria con la tabla llena) y
// cliente con transacciones asincronas, callback y timeout de MODBUSIP_TIMEOUT ms.
#pragma once
#include "Modbus.h"
#include "red.h"

class ModbusTCP : public Modbus {
public:
    void server(uint16_t puerto = MODBUSIP_PORT);
    void client() { cliente_ = true; }
    void task();

    bool connect(IPAddress ip, uint16_t puerto = MODBUSIP_PORT);
    bool isConnected(IPAddress ip);
    bool disconnect(IPAddress ip);
    void dropTransactions();
    bool isTransaction(uint16_t tid);

    uint16_t readHreg(IPAddress ip, uint16_t o, uint16_t* v, uint16_t n = 1, cbTransaction cb = nullptr, uint8_t unit = MODBUSIP_UNIT) {
        return pedir(ip, unit, FC_READ_REGS, o, n, nullptr, v, cb);
    }
    uint16_t readIreg(IPAddress ip, uint16_t o, uint16_t* v, uint16_t n = 1, cbTransaction cb = nullptr, uint8_t unit = MODBUSIP_UNIT) {
        return pedir(ip, unit, FC_READ_INPUT_REGS, o, n, nullptr, v, cb);
    }
    uint16_t readCoil(IPAddress ip, uint16_t o, bool* v, uint16_t n = 1, cbTransaction cb = nullptr, uint8_t unit = MODBUSIP_UNIT) {
        return pedir(ip, unit, FC_READ_COILS, o, n, nullptr, v, cb);
    }
    uint16_t readIsts(IPAddress ip, uint16_t o, bool* v, uint16_t n = 1, cbTransaction cb = nullptr, uint8_t unit = MODBUSIP_UNIT) {
        return pedir(ip, unit, FC_READ_INPUT_STAT, o, n, nullptr, v, cb);
    }
    uint16_t writeHreg(IPAddress ip, uint16_t o, uint16_t v, cbTransaction cb = nullptr, uint8_t unit = MODBUSIP_UNIT) {
        uint8_t d[2] = {(uint8_t)(v >> 8), (uint8_t)v};
        return pedir(ip, unit, FC_WRITE_REG, o, 1, d, nullptr, cb);
    }
    uint16_t writeHreg(IPAddress ip, uint16_t o, uint16_t* v, uint16_t n, cbTransaction cb = nullptr, uint8_t unit = MODBUSIP_UNIT);
    uint16_t writeCoil(IPAddress ip, uint16_t o, bool v, cbTransaction cb = nullptr, uint8_t unit = MODBUSIP_UNIT) {
        uint8_t d[2] = {(uint8_t)(v ? 0xFF : 0), 0};
        return pedir(ip, unit, FC_WRITE_COIL, o, 1, d, nullptr, cb);
    }
    uint16_t writeCoil(IPAddress ip, uint16_t o, bool* v, uint16_t n, cbTransaction cb = nullptr, uint8_t unit = MODBUSIP_UNIT);

    // Mapa de registros local (se hereda de Modbus) + estos atajos de la libreria
    using Modbus::Hreg;
    using Modbus::Coil;
    using Modbus::Ireg;
    using Modbus::Ists;

private:
    struct Conexion {
        ClienteTCP c;
        std::vector<uint8_t> buf;
        IPAddress ip;
    };
    ServidorTCP* srv_ = nullptr;
    bool cliente_ = false;
    std::vector<Conexion> entrantes_;              // clientes del servidor
    std::vector<Conexion> salientes_;              // conexiones como cliente
    std::vector<ModbusTransaccion> pendientes_;
    uint16_t tid_ = 0;

    uint16_t pedir(IPAddress ip, uint8_t unit, uint8_t fc, uint16_t o, uint16_t n,
                   const uint8_t* datos, void* destino, cbTransaction cb, size_t nb = 0);
    Conexion* conexion(IPAddress ip);
    void atender(Conexion& x);
    void respuestas(Conexion& x);
};
