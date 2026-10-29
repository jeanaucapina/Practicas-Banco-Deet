// Mapa de registros y PDU de Modbus (servidor y cliente), comun a TCP y RTU.
#include "Modbus.h"

uint16_t modbus_crc16(const uint8_t* b, size_t n) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < n; i++) {
        crc ^= b[i];
        for (int k = 0; k < 8; k++) crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
    }
    return crc;
}

bool Modbus::add(TAddressType t, uint16_t o, uint16_t v, uint16_t n) {
    for (uint16_t i = 0; i < n; i++) {
        TAddress a{t, (uint16_t)(o + i)};
        if (!regs.count(a)) regs[a] = TRegister{a, v};
    }
    return true;
}

bool Modbus::poner(TAddressType t, uint16_t o, uint16_t v) {
    auto it = regs.find(TAddress{t, o});
    if (it == regs.end()) return false;
    it->second.value = v;
    return true;
}

uint16_t Modbus::leer(TAddressType t, uint16_t o) {
    auto it = regs.find(TAddress{t, o});
    return it == regs.end() ? 0 : it->second.value;
}

bool Modbus::quitar(TAddressType t, uint16_t o, uint16_t n) {
    for (uint16_t i = 0; i < n; i++) regs.erase(TAddress{t, (uint16_t)(o + i)});
    return true;
}

bool Modbus::enganchar(std::map<TAddress, cbModbus>& m, TAddressType t, uint16_t o, cbModbus cb, uint16_t n) {
    for (uint16_t i = 0; i < n; i++) {
        TAddress a{t, (uint16_t)(o + i)};
        if (cb) m[a] = cb;
        else m.erase(a);
    }
    return true;
}

bool Modbus::existe(TAddressType t, uint16_t o, uint16_t n) {
    for (uint32_t i = 0; i < n; i++)
        if (!regs.count(TAddress{t, (uint16_t)(o + i)})) return false;
    return true;
}

uint16_t Modbus::leerRemoto(TAddressType t, uint16_t o) {
    TAddress a{t, o};
    TRegister& r = regs[a];
    auto it = cbGet.find(a);
    if (it != cbGet.end()) return it->second(&r, r.value);
    return r.value;
}

void Modbus::escribirRemoto(TAddressType t, uint16_t o, uint16_t v) {
    TAddress a{t, o};
    TRegister& r = regs[a];
    auto it = cbSet.find(a);
    r.value = it != cbSet.end() ? it->second(&r, v) : v;
}

static std::vector<uint8_t> excepcion(uint8_t fc, uint8_t cod) { return {(uint8_t)(fc | 0x80), cod}; }

std::vector<uint8_t> Modbus::atenderPDU(const uint8_t* p, size_t n) {
    if (n < 1) return {};
    uint8_t fc = p[0];
    auto u16 = [&](size_t i) { return (uint16_t)((p[i] << 8) | p[i + 1]); };
    switch (fc) {
    case FC_READ_COILS:
    case FC_READ_INPUT_STAT: {
        if (n < 5) return excepcion(fc, EX_ILLEGAL_VALUE);
        uint16_t o = u16(1), q = u16(3);
        if (q < 1 || q > 2000) return excepcion(fc, EX_ILLEGAL_VALUE);
        TAddressType t = fc == FC_READ_COILS ? TCOIL : TISTS;
        if (!existe(t, o, q)) return excepcion(fc, EX_ILLEGAL_ADDRESS);
        std::vector<uint8_t> r{fc, (uint8_t)((q + 7) / 8)};
        r.resize(2 + r[1], 0);
        for (uint16_t i = 0; i < q; i++)
            if (leerRemoto(t, o + i)) r[2 + i / 8] |= 1 << (i % 8);
        return r;
    }
    case FC_READ_REGS:
    case FC_READ_INPUT_REGS: {
        if (n < 5) return excepcion(fc, EX_ILLEGAL_VALUE);
        uint16_t o = u16(1), q = u16(3);
        if (q < 1 || q > 125) return excepcion(fc, EX_ILLEGAL_VALUE);
        TAddressType t = fc == FC_READ_REGS ? THREG : TIREG;
        if (!existe(t, o, q)) return excepcion(fc, EX_ILLEGAL_ADDRESS);
        std::vector<uint8_t> r{fc, (uint8_t)(q * 2)};
        for (uint16_t i = 0; i < q; i++) {
            uint16_t v = leerRemoto(t, o + i);
            r.push_back(v >> 8);
            r.push_back(v & 0xFF);
        }
        return r;
    }
    case FC_WRITE_COIL: {
        if (n < 5) return excepcion(fc, EX_ILLEGAL_VALUE);
        uint16_t o = u16(1), v = u16(3);
        if (v != 0x0000 && v != 0xFF00) return excepcion(fc, EX_ILLEGAL_VALUE);
        if (!existe(TCOIL, o, 1)) return excepcion(fc, EX_ILLEGAL_ADDRESS);
        escribirRemoto(TCOIL, o, v);
        return std::vector<uint8_t>(p, p + 5);
    }
    case FC_WRITE_REG: {
        if (n < 5) return excepcion(fc, EX_ILLEGAL_VALUE);
        uint16_t o = u16(1), v = u16(3);
        if (!existe(THREG, o, 1)) return excepcion(fc, EX_ILLEGAL_ADDRESS);
        escribirRemoto(THREG, o, v);
        return std::vector<uint8_t>(p, p + 5);
    }
    case FC_WRITE_COILS: {
        if (n < 6) return excepcion(fc, EX_ILLEGAL_VALUE);
        uint16_t o = u16(1), q = u16(3);
        uint8_t nb = p[5];
        if (q < 1 || q > 1968 || nb != (q + 7) / 8 || n < (size_t)(6 + nb)) return excepcion(fc, EX_ILLEGAL_VALUE);
        if (!existe(TCOIL, o, q)) return excepcion(fc, EX_ILLEGAL_ADDRESS);
        for (uint16_t i = 0; i < q; i++) escribirRemoto(TCOIL, o + i, (p[6 + i / 8] >> (i % 8)) & 1 ? 0xFF00 : 0);
        return std::vector<uint8_t>(p, p + 5);
    }
    case FC_WRITE_REGS: {
        if (n < 6) return excepcion(fc, EX_ILLEGAL_VALUE);
        uint16_t o = u16(1), q = u16(3);
        uint8_t nb = p[5];
        if (q < 1 || q > 123 || nb != q * 2 || n < (size_t)(6 + nb)) return excepcion(fc, EX_ILLEGAL_VALUE);
        if (!existe(THREG, o, q)) return excepcion(fc, EX_ILLEGAL_ADDRESS);
        for (uint16_t i = 0; i < q; i++) escribirRemoto(THREG, o + i, u16(6 + 2 * i));
        return std::vector<uint8_t>(p, p + 5);
    }
    default:
        return excepcion(fc, EX_ILLEGAL_FUNCTION);
    }
}

Modbus::ResultCode Modbus::leerRespuesta(uint8_t fc, const std::vector<uint8_t>& r, void* destino, uint16_t num) {
    if (r.empty()) return EX_UNEXPECTED_RESPONSE;
    if (r[0] == (uint8_t)(fc | 0x80)) return r.size() > 1 ? (ResultCode)r[1] : EX_UNEXPECTED_RESPONSE;
    if (r[0] != fc) return EX_UNEXPECTED_RESPONSE;
    switch (fc) {
    case FC_READ_REGS:
    case FC_READ_INPUT_REGS:
        if (r.size() < 2 || r[1] != num * 2 || r.size() < (size_t)(2 + num * 2)) return EX_DATA_MISMACH;
        if (destino)
            for (uint16_t i = 0; i < num; i++) ((uint16_t*)destino)[i] = (uint16_t)((r[2 + 2 * i] << 8) | r[3 + 2 * i]);
        return EX_SUCCESS;
    case FC_READ_COILS:
    case FC_READ_INPUT_STAT:
        if (r.size() < 2 || r[1] != (num + 7) / 8) return EX_DATA_MISMACH;
        if (destino)
            for (uint16_t i = 0; i < num; i++) ((bool*)destino)[i] = (r[2 + i / 8] >> (i % 8)) & 1;
        return EX_SUCCESS;
    default:
        return EX_SUCCESS;                // escrituras: el eco ya es la confirmacion
    }
}
