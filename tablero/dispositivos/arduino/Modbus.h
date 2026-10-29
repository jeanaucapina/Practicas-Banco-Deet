// Nucleo de modbus-esp8266 (Alexander Emelianov, v4.1) en el tablero virtual: el
// mapa de registros, los callbacks y los codigos de resultado que usan las guias
// (L6, L7, L9). Los transportes estan en ModbusEthernet.h / ModbusIP_ESP8266.h
// (Modbus TCP) y ModbusRTU.h (Modbus RTU sobre el RS-485 del banco).
#pragma once
#include <Arduino.h>

#include <functional>
#include <map>
#include <vector>

#ifndef MODBUSIP_PORT
#define MODBUSIP_PORT 502
#endif
#ifndef MODBUSIP_TIMEOUT
#define MODBUSIP_TIMEOUT 1000
#endif
#ifndef MODBUSIP_MAX_CLIENTS
#define MODBUSIP_MAX_CLIENTS 8
#endif
#ifndef MODBUSIP_UNIT
#define MODBUSIP_UNIT 255
#endif

enum TAddressType { TCOIL, TISTS, TIREG, THREG, TNONE };

struct TAddress {
    TAddressType type = TNONE;
    uint16_t address = 0;
    bool operator<(const TAddress& o) const { return type != o.type ? type < o.type : address < o.address; }
    bool operator==(const TAddress& o) const { return type == o.type && address == o.address; }
    bool isCoil() const { return type == TCOIL; }
    bool isIsts() const { return type == TISTS; }
    bool isIreg() const { return type == TIREG; }
    bool isHreg() const { return type == THREG; }
};

struct TRegister {
    TAddress address;
    uint16_t value = 0;
};

class Modbus {
public:
    enum FunctionCode : uint8_t {
        FC_READ_COILS = 0x01, FC_READ_INPUT_STAT = 0x02, FC_READ_REGS = 0x03, FC_READ_INPUT_REGS = 0x04,
        FC_WRITE_COIL = 0x05, FC_WRITE_REG = 0x06, FC_WRITE_COILS = 0x0F, FC_WRITE_REGS = 0x10,
        FC_READWRITE_REGS = 0x17,
    };
    enum ResultCode : uint8_t {
        EX_SUCCESS = 0x00, EX_ILLEGAL_FUNCTION = 0x01, EX_ILLEGAL_ADDRESS = 0x02, EX_ILLEGAL_VALUE = 0x03,
        EX_SLAVE_FAILURE = 0x04, EX_ACKNOWLEDGE = 0x05, EX_SLAVE_DEVICE_BUSY = 0x06,
        EX_MEMORY_PARITY_ERROR = 0x08, EX_PATH_UNAVAILABLE = 0x0A, EX_DEVICE_FAILED_TO_RESPOND = 0x0B,
        EX_GENERAL_FAILURE = 0xE1, EX_DATA_MISMACH = 0xE2, EX_UNEXPECTED_RESPONSE = 0xE3,
        EX_TIMEOUT = 0xE4, EX_CONNECTION_LOST = 0xE5, EX_CANCEL = 0xE6, EX_PASSTHROUGH = 0xE7,
        EX_FORCE_PROCESS = 0xE8,
    };

    using cbModbus = std::function<uint16_t(TRegister*, uint16_t)>;
    using cbTransaction = std::function<bool(ResultCode, uint16_t, void*)>;

    // ── Registros locales (servidor/esclavo) ──────────────────────────────
    bool addHreg(uint16_t o, uint16_t v = 0, uint16_t n = 1) { return add(THREG, o, v, n); }
    bool addIreg(uint16_t o, uint16_t v = 0, uint16_t n = 1) { return add(TIREG, o, v, n); }
    bool addCoil(uint16_t o, bool v = false, uint16_t n = 1) { return add(TCOIL, o, v ? 0xFF00 : 0, n); }
    bool addIsts(uint16_t o, bool v = false, uint16_t n = 1) { return add(TISTS, o, v ? 0xFF00 : 0, n); }
    bool Hreg(uint16_t o, uint16_t v) { return poner(THREG, o, v); }
    bool Ireg(uint16_t o, uint16_t v) { return poner(TIREG, o, v); }
    bool Coil(uint16_t o, bool v) { return poner(TCOIL, o, v ? 0xFF00 : 0); }
    bool Ists(uint16_t o, bool v) { return poner(TISTS, o, v ? 0xFF00 : 0); }
    uint16_t Hreg(uint16_t o) { return leer(THREG, o); }
    uint16_t Ireg(uint16_t o) { return leer(TIREG, o); }
    bool Coil(uint16_t o) { return leer(TCOIL, o) != 0; }
    bool Ists(uint16_t o) { return leer(TISTS, o) != 0; }
    bool removeHreg(uint16_t o, uint16_t n = 1) { return quitar(THREG, o, n); }
    bool removeIreg(uint16_t o, uint16_t n = 1) { return quitar(TIREG, o, n); }
    bool removeCoil(uint16_t o, uint16_t n = 1) { return quitar(TCOIL, o, n); }
    bool removeIsts(uint16_t o, uint16_t n = 1) { return quitar(TISTS, o, n); }

    bool onSetHreg(uint16_t o, cbModbus cb = nullptr, uint16_t n = 1) { return enganchar(cbSet, THREG, o, cb, n); }
    bool onSetCoil(uint16_t o, cbModbus cb = nullptr, uint16_t n = 1) { return enganchar(cbSet, TCOIL, o, cb, n); }
    bool onGetHreg(uint16_t o, cbModbus cb = nullptr, uint16_t n = 1) { return enganchar(cbGet, THREG, o, cb, n); }
    bool onGetIreg(uint16_t o, cbModbus cb = nullptr, uint16_t n = 1) { return enganchar(cbGet, TIREG, o, cb, n); }
    bool onGetCoil(uint16_t o, cbModbus cb = nullptr, uint16_t n = 1) { return enganchar(cbGet, TCOIL, o, cb, n); }
    bool onGetIsts(uint16_t o, cbModbus cb = nullptr, uint16_t n = 1) { return enganchar(cbGet, TISTS, o, cb, n); }

    // Atiende un PDU de peticion contra el mapa local y devuelve el de respuesta
    // (o el de excepcion). Lo usan los transportes.
    std::vector<uint8_t> atenderPDU(const uint8_t* pdu, size_t n);

    // Decodifica la respuesta de un esclavo/servidor (lado cliente/maestro).
    static ResultCode leerRespuesta(uint8_t fc, const std::vector<uint8_t>& pdu, void* destino, uint16_t num);

protected:
    std::map<TAddress, TRegister> regs;
    std::map<TAddress, cbModbus> cbSet, cbGet;

    bool add(TAddressType t, uint16_t o, uint16_t v, uint16_t n);
    bool poner(TAddressType t, uint16_t o, uint16_t v);
    uint16_t leer(TAddressType t, uint16_t o);
    bool quitar(TAddressType t, uint16_t o, uint16_t n);
    bool enganchar(std::map<TAddress, cbModbus>& m, TAddressType t, uint16_t o, cbModbus cb, uint16_t n);
    bool existe(TAddressType t, uint16_t o, uint16_t n);
    uint16_t leerRemoto(TAddressType t, uint16_t o);          // con onGet
    void escribirRemoto(TAddressType t, uint16_t o, uint16_t v);   // con onSet
};

// Una peticion de cliente/maestro pendiente de respuesta.
struct ModbusTransaccion {
    uint16_t tid = 0;
    uint8_t unidad = 1, fc = 0;
    uint16_t num = 0;
    void* destino = nullptr;
    Modbus::cbTransaction cb;
    unsigned long t0 = 0;
};

uint16_t modbus_crc16(const uint8_t* b, size_t n);
