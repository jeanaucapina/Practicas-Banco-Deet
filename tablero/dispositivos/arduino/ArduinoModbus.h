// ArduinoModbus (libreria oficial de Arduino, 1.0.x, sobre libmodbus) en el RS-485 del
// tablero. Guia L6: esclavo Modbus RTU en el Controllino.
//   ModbusRTUServer.begin(RS485bus, 1, 19200, SERIAL_8N1);
//   ModbusRTUServer.configureHoldingRegisters(0x0000, 8);
//   loop(): ModbusRTUServer.holdingRegisterWrite(0, v); if (ModbusRTUServer.poll()) ...
// Y el maestro: ModbusRTUClient.begin(RS485bus, 19200); ModbusRTUClient.holdingRegisterRead(1, 0)...
// Como libmodbus: la trama se cierra con 3,5 caracteres de silencio, una trama con CRC
// malo o para otra direccion se descarta en silencio, y las excepciones 01/02/03 salen
// del mapa configurado.
#pragma once
#include <Arduino.h>

#include <vector>

#include "ArduinoRS485.h"
#include "Modbus.h"

#define COILS 0
#define DISCRETE_INPUTS 1
#define HOLDING_REGISTERS 2
#define INPUT_REGISTERS 3

namespace vino_mb {

// Junta los bytes que llegan del bus en tramas RTU (silencio de 3,5 caracteres).
class Receptor {
public:
    // Devuelve true y deja la trama en `t` cuando hay una completa.
    bool trama(Stream& s, std::vector<uint8_t>& t) {
        while (s.available() > 0) {
            int b = s.read();
            if (b < 0) break;
            buf_.push_back((uint8_t)b);
            ultimo_ = micros();
        }
        if (buf_.empty() || micros() - ultimo_ < vino::bus_t35_us()) return false;
        t.swap(buf_);
        buf_.clear();
        return true;
    }
    void vaciar(Stream& s) { while (s.available() > 0) s.read(); buf_.clear(); }

private:
    std::vector<uint8_t> buf_;
    unsigned long ultimo_ = 0;
};

inline bool crc_ok(const std::vector<uint8_t>& t) {
    if (t.size() < 4) return false;
    uint16_t c = modbus_crc16(t.data(), t.size() - 2);
    return t[t.size() - 2] == (c & 0xFF) && t[t.size() - 1] == (c >> 8);
}

inline void emitir(RS485Class& rs, uint8_t id, const std::vector<uint8_t>& pdu) {
    std::vector<uint8_t> t{id};
    t.insert(t.end(), pdu.begin(), pdu.end());
    uint16_t c = modbus_crc16(t.data(), t.size());
    t.push_back(c & 0xFF);
    t.push_back(c >> 8);
    rs.beginTransmission();
    rs.write(t.data(), t.size());
    rs.endTransmission();               // flush + vuelta a recepcion
}

}  // namespace vino_mb

class ModbusRTUServerClass : public Modbus {
public:
    int begin(RS485Class& rs485, int id, unsigned long baudios, uint16_t config = SERIAL_8N1) {
        rs_ = &rs485;
        id_ = (uint8_t)id;
        rs485.begin(baudios, config);
        rs485.receive();
        return 1;
    }
    int begin(int id, unsigned long baudios, uint16_t config = SERIAL_8N1) { return begin(RS485, id, baudios, config); }
    void end() {}

    int configureCoils(int inicio, int n) { return addCoil(inicio, false, n); }
    int configureDiscreteInputs(int inicio, int n) { return addIsts(inicio, false, n); }
    int configureHoldingRegisters(int inicio, int n) { return addHreg(inicio, 0, n); }
    int configureInputRegisters(int inicio, int n) { return addIreg(inicio, 0, n); }

    int coilRead(int a) { return existe(TCOIL, a, 1) ? (Coil(a) ? 1 : 0) : -1; }
    int discreteInputRead(int a) { return existe(TISTS, a, 1) ? (Ists(a) ? 1 : 0) : -1; }
    long holdingRegisterRead(int a) { return existe(THREG, a, 1) ? (long)Hreg(a) : -1; }
    long inputRegisterRead(int a) { return existe(TIREG, a, 1) ? (long)Ireg(a) : -1; }
    int coilWrite(int a, uint8_t v) { return existe(TCOIL, a, 1) ? (Coil(a, v != 0), 1) : 0; }
    int discreteInputWrite(int a, uint8_t v) { return existe(TISTS, a, 1) ? (Ists(a, v != 0), 1) : 0; }
    int holdingRegisterWrite(int a, uint16_t v) { return existe(THREG, a, 1) ? (Hreg(a, v), 1) : 0; }
    int inputRegisterWrite(int a, uint16_t v) { return existe(TIREG, a, 1) ? (Ireg(a, v), 1) : 0; }

    // Atiende como mucho una peticion. != 0 si atendio una valida dirigida a el.
    int poll() {
        if (!rs_) return 0;
        std::vector<uint8_t> t;
        if (!rx_.trama(*rs_, t)) return 0;
        if (t.size() < 4 || !vino_mb::crc_ok(t)) return 0;          // CRC malo: silencio
        if (t[0] != id_ && t[0] != 0) return 0;                     // no es para mi
        std::vector<uint8_t> r = atenderPDU(&t[1], t.size() - 3);
        if (t[0] != 0 && !r.empty()) vino_mb::emitir(*rs_, id_, r); // a la difusion no se responde
        return 1;
    }

private:
    RS485Class* rs_ = nullptr;
    uint8_t id_ = 1;
    vino_mb::Receptor rx_;
};

class ModbusRTUClientClass {
public:
    int begin(RS485Class& rs485, unsigned long baudios, uint16_t config = SERIAL_8N1) {
        rs_ = &rs485;
        rs485.begin(baudios, config);
        rs485.receive();
        return 1;
    }
    int begin(unsigned long baudios, uint16_t config = SERIAL_8N1) { return begin(RS485, baudios, config); }
    void end() {}
    void setTimeout(unsigned long ms) { timeout_ = ms; }
    const char* lastError() { return error_; }

    int coilRead(int id, int a) { return requestFrom(id, COILS, a, 1) ? read() : -1; }
    int discreteInputRead(int id, int a) { return requestFrom(id, DISCRETE_INPUTS, a, 1) ? read() : -1; }
    long holdingRegisterRead(int id, int a) { return requestFrom(id, HOLDING_REGISTERS, a, 1) ? read() : -1; }
    long inputRegisterRead(int id, int a) { return requestFrom(id, INPUT_REGISTERS, a, 1) ? read() : -1; }
    int coilWrite(int id, int a, uint8_t v) {
        return transaccion(id, {Modbus::FC_WRITE_COIL, (uint8_t)(a >> 8), (uint8_t)a, (uint8_t)(v ? 0xFF : 0), 0});
    }
    int holdingRegisterWrite(int id, int a, uint16_t v) {
        return transaccion(id, {Modbus::FC_WRITE_REG, (uint8_t)(a >> 8), (uint8_t)a, (uint8_t)(v >> 8), (uint8_t)v});
    }

    // Lectura de varios: requestFrom(id, HOLDING_REGISTERS, 0, 8) y luego available()/read().
    int requestFrom(int id, int tipo, int a, int n) {
        static const uint8_t FC[] = {Modbus::FC_READ_COILS, Modbus::FC_READ_INPUT_STAT, Modbus::FC_READ_REGS,
                                     Modbus::FC_READ_INPUT_REGS};
        valores_.clear();
        if (tipo < 0 || tipo > 3) return 0;
        if (!transaccion(id, {FC[tipo], (uint8_t)(a >> 8), (uint8_t)a, (uint8_t)(n >> 8), (uint8_t)n})) return 0;
        if (tipo < 2)
            for (int i = 0; i < n && 2 + i / 8 < (int)resp_.size(); i++) valores_.push_back((resp_[2 + i / 8] >> (i % 8)) & 1);
        else
            for (int i = 0; i < n && 3 + 2 * i < (int)resp_.size(); i++) valores_.push_back((resp_[2 + 2 * i] << 8) | resp_[3 + 2 * i]);
        return (int)valores_.size();
    }
    int available() { return (int)valores_.size(); }
    long read() {
        if (valores_.empty()) return -1;
        long v = valores_.front();
        valores_.erase(valores_.begin());
        return v;
    }

    // Escritura de varios: beginTransmission(id, HOLDING_REGISTERS, 4, 4); write(v)...; endTransmission()
    int beginTransmission(int id, int tipo, int a, int n) {
        tx_id_ = id; tx_tipo_ = tipo; tx_a_ = a; tx_n_ = n; tx_v_.clear();
        return 1;
    }
    int write(unsigned int v) { tx_v_.push_back((uint16_t)v); return 1; }
    int endTransmission() {
        std::vector<uint8_t> pdu;
        if (tx_tipo_ == HOLDING_REGISTERS) {
            pdu = {Modbus::FC_WRITE_REGS, (uint8_t)(tx_a_ >> 8), (uint8_t)tx_a_, (uint8_t)(tx_n_ >> 8), (uint8_t)tx_n_,
                   (uint8_t)(2 * tx_n_)};
            for (int i = 0; i < tx_n_; i++) {
                uint16_t v = i < (int)tx_v_.size() ? tx_v_[i] : 0;
                pdu.push_back(v >> 8);
                pdu.push_back(v & 0xFF);
            }
        } else if (tx_tipo_ == COILS) {
            pdu = {Modbus::FC_WRITE_COILS, (uint8_t)(tx_a_ >> 8), (uint8_t)tx_a_, (uint8_t)(tx_n_ >> 8), (uint8_t)tx_n_,
                   (uint8_t)((tx_n_ + 7) / 8)};
            pdu.resize(6 + (tx_n_ + 7) / 8, 0);
            for (int i = 0; i < tx_n_ && i < (int)tx_v_.size(); i++)
                if (tx_v_[i]) pdu[6 + i / 8] |= 1 << (i % 8);
        } else {
            error_ = "Invalid argument";
            return 0;
        }
        return transaccion(tx_id_, pdu);
    }

private:
    RS485Class* rs_ = nullptr;
    unsigned long timeout_ = 1000;
    const char* error_ = "";
    std::vector<uint8_t> resp_;
    std::vector<long> valores_;
    int tx_id_ = 1, tx_tipo_ = 2, tx_a_ = 0, tx_n_ = 0;
    std::vector<uint16_t> tx_v_;
    vino_mb::Receptor rx_;

    // Emite la peticion y espera la respuesta (bloqueante, como libmodbus).
    int transaccion(int id, const std::vector<uint8_t>& pdu) {
        if (!rs_) { error_ = "Not connected"; return 0; }
        rx_.vaciar(*rs_);
        vino_mb::emitir(*rs_, (uint8_t)id, pdu);
        if (id == 0) { error_ = ""; return 1; }               // difusion: no hay respuesta
        unsigned long t0 = millis();
        std::vector<uint8_t> t;
        while (millis() - t0 < timeout_) {
            if (rx_.trama(*rs_, t)) {
                if (!vino_mb::crc_ok(t)) { error_ = "Invalid CRC"; return 0; }
                if (t[0] != (uint8_t)id) continue;
                if (t[1] & 0x80) {
                    static const char* EXC[] = {"", "Illegal function", "Illegal data address", "Illegal data value",
                                                "Slave device or server failure"};
                    error_ = t[2] < 5 ? EXC[t[2]] : "Exception";
                    return 0;
                }
                resp_.assign(t.begin() + 1, t.end() - 2);
                error_ = "";
                return 1;
            }
            delay(1);
        }
        error_ = "Connection timed out";
        return 0;
    }
};

inline ModbusRTUServerClass ModbusRTUServer;
inline ModbusRTUClientClass ModbusRTUClient;
