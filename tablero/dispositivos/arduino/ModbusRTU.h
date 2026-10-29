// modbus-esp8266 4.1: Modbus RTU sobre el RS-485 del tablero (guia L6, maestro en el ESP32).
//   #define MODBUSRTU_TIMEOUT 5000          // antes del include
//   #include <ModbusRTU.h>
//   Serial1.begin(19200, SERIAL_8N1, 16, 17);
//   mb.begin(&Serial1, -1); mb.master();    // o mb.slave(2) + addHreg(...)
//   mb.readHreg(1, 0, regs, 8, cb);  mb.writeHreg(1, 4, 1, cb);  mb.writeHreg(1, 4, valores, 4, cb);
//   loop(): mb.task();
// Una transaccion en vuelo cada vez (como la libreria): mientras espera respuesta,
// las peticiones nuevas devuelven 0. La trama se cierra con 3,5 caracteres de silencio.
#pragma once
#include <Arduino.h>

#include <vector>

#include "Modbus.h"

#ifndef MODBUSRTU_TIMEOUT
#define MODBUSRTU_TIMEOUT 1000
#endif

class ModbusRTU : public Modbus {
public:
    bool begin(HardwareSerial* puerto, int16_t pin_tx = -1, bool directo = true) {
        puerto_ = puerto;
        pin_tx_ = pin_tx;
        directo_ = directo;
        if (pin_tx_ >= 0) { pinMode(pin_tx_, OUTPUT); digitalWrite(pin_tx_, directo_ ? LOW : HIGH); }
        return true;
    }
    bool begin(Stream* puerto, int16_t pin_tx = -1, bool directo = true) {
        return begin(static_cast<HardwareSerial*>(puerto), pin_tx, directo);
    }
    void master() { id_ = 0; }
    void slave(uint8_t id) { id_ = id; }
    uint8_t slave() { return id_; }
    void setBaudrate(uint32_t) {}

    bool isTransaction() { return en_vuelo_; }
    void cancelTransaction() { en_vuelo_ = false; }

    uint16_t readHreg(uint8_t id, uint16_t o, uint16_t* v, uint16_t n = 1, cbTransaction cb = nullptr, uint8_t = 0) {
        return pedir(id, FC_READ_REGS, o, n, v, cb);
    }
    uint16_t readIreg(uint8_t id, uint16_t o, uint16_t* v, uint16_t n = 1, cbTransaction cb = nullptr, uint8_t = 0) {
        return pedir(id, FC_READ_INPUT_REGS, o, n, v, cb);
    }
    uint16_t readCoil(uint8_t id, uint16_t o, bool* v, uint16_t n = 1, cbTransaction cb = nullptr, uint8_t = 0) {
        return pedir(id, FC_READ_COILS, o, n, v, cb);
    }
    uint16_t readIsts(uint8_t id, uint16_t o, bool* v, uint16_t n = 1, cbTransaction cb = nullptr, uint8_t = 0) {
        return pedir(id, FC_READ_INPUT_STAT, o, n, v, cb);
    }
    uint16_t writeHreg(uint8_t id, uint16_t o, uint16_t v, cbTransaction cb = nullptr, uint8_t = 0) {
        return enviarPDU(id, {FC_WRITE_REG, (uint8_t)(o >> 8), (uint8_t)o, (uint8_t)(v >> 8), (uint8_t)v}, FC_WRITE_REG, 1,
                         nullptr, cb);
    }
    uint16_t writeHreg(uint8_t id, uint16_t o, uint16_t* v, uint16_t n, cbTransaction cb = nullptr, uint8_t = 0) {
        std::vector<uint8_t> p{FC_WRITE_REGS, (uint8_t)(o >> 8), (uint8_t)o, (uint8_t)(n >> 8), (uint8_t)n, (uint8_t)(2 * n)};
        for (uint16_t i = 0; i < n; i++) { p.push_back(v[i] >> 8); p.push_back(v[i] & 0xFF); }
        return enviarPDU(id, p, FC_WRITE_REGS, n, nullptr, cb);
    }
    uint16_t writeCoil(uint8_t id, uint16_t o, bool v, cbTransaction cb = nullptr, uint8_t = 0) {
        return enviarPDU(id, {FC_WRITE_COIL, (uint8_t)(o >> 8), (uint8_t)o, (uint8_t)(v ? 0xFF : 0), 0}, FC_WRITE_COIL, 1,
                         nullptr, cb);
    }
    uint16_t writeCoil(uint8_t id, uint16_t o, bool* v, uint16_t n, cbTransaction cb = nullptr, uint8_t = 0) {
        std::vector<uint8_t> p{FC_WRITE_COILS, (uint8_t)(o >> 8), (uint8_t)o, (uint8_t)(n >> 8), (uint8_t)n,
                               (uint8_t)((n + 7) / 8)};
        p.resize(6 + (n + 7) / 8, 0);
        for (uint16_t i = 0; i < n; i++)
            if (v[i]) p[6 + i / 8] |= 1 << (i % 8);
        return enviarPDU(id, p, FC_WRITE_COILS, n, nullptr, cb);
    }

    void task() {
        if (!puerto_) return;
        while (puerto_->available() > 0) {
            int b = puerto_->read();
            if (b < 0) break;
            buf_.push_back((uint8_t)b);
            ultimo_ = micros();
        }
        if (!buf_.empty() && micros() - ultimo_ >= vino::bus_t35_us()) {
            std::vector<uint8_t> t;
            t.swap(buf_);
            procesar(t);
        }
        if (en_vuelo_ && millis() - t0_ >= MODBUSRTU_TIMEOUT) {
            en_vuelo_ = false;
            if (cb_) cb_(EX_TIMEOUT, tid_, nullptr);
        }
    }

private:
    HardwareSerial* puerto_ = nullptr;
    int16_t pin_tx_ = -1;
    bool directo_ = true;
    uint8_t id_ = 0;                 // 0 = maestro
    std::vector<uint8_t> buf_;
    unsigned long ultimo_ = 0;
    bool en_vuelo_ = false;
    uint8_t esclavo_ = 0, fc_ = 0;
    uint16_t num_ = 0, tid_ = 0;
    void* destino_ = nullptr;
    cbTransaction cb_;
    unsigned long t0_ = 0;

    void emitir(uint8_t id, const std::vector<uint8_t>& pdu) {
        std::vector<uint8_t> t{id};
        t.insert(t.end(), pdu.begin(), pdu.end());
        uint16_t c = modbus_crc16(t.data(), t.size());
        t.push_back(c & 0xFF);
        t.push_back(c >> 8);
        if (pin_tx_ >= 0) digitalWrite(pin_tx_, directo_ ? HIGH : LOW);
        vino::bus_direccion(true);
        puerto_->write(t.data(), t.size());
        puerto_->flush();            // espera al ultimo bit antes de soltar el par
        vino::bus_direccion(false);
        if (pin_tx_ >= 0) digitalWrite(pin_tx_, directo_ ? LOW : HIGH);
    }

    uint16_t pedir(uint8_t id, uint8_t fc, uint16_t o, uint16_t n, void* destino, cbTransaction cb) {
        return enviarPDU(id, {fc, (uint8_t)(o >> 8), (uint8_t)o, (uint8_t)(n >> 8), (uint8_t)n}, fc, n, destino, cb);
    }

    uint16_t enviarPDU(uint8_t id, const std::vector<uint8_t>& pdu, uint8_t fc, uint16_t n, void* destino,
                       cbTransaction cb) {
        if (!puerto_ || id_ != 0 || en_vuelo_) return 0;      // solo el maestro, y de una en una
        emitir(id, pdu);
        tid_++;
        if (tid_ == 0) tid_ = 1;
        if (id == 0) {                                        // difusion: nadie responde
            if (cb) cb(EX_SUCCESS, tid_, nullptr);
            return tid_;
        }
        en_vuelo_ = true;
        esclavo_ = id; fc_ = fc; num_ = n; destino_ = destino; cb_ = cb;
        t0_ = millis();
        return tid_;
    }

    void procesar(const std::vector<uint8_t>& t) {
        if (t.size() < 4) return;
        uint16_t c = modbus_crc16(t.data(), t.size() - 2);
        if (t[t.size() - 2] != (c & 0xFF) || t[t.size() - 1] != (c >> 8)) return;   // CRC malo: se ignora
        if (id_ == 0) {
            if (!en_vuelo_ || t[0] != esclavo_) return;
            std::vector<uint8_t> pdu(t.begin() + 1, t.end() - 2);
            ResultCode r = (pdu[0] & 0x80) ? (ResultCode)(pdu.size() > 1 ? pdu[1] : EX_GENERAL_FAILURE)
                                           : leerRespuesta(fc_, pdu, destino_, num_);
            en_vuelo_ = false;
            if (cb_) cb_(r, tid_, nullptr);
        } else if (t[0] == id_ || t[0] == 0) {
            std::vector<uint8_t> r = atenderPDU(&t[1], t.size() - 3);
            if (t[0] != 0 && !r.empty()) emitir(id_, r);
        }
    }
};
