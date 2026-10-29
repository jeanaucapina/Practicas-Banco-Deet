// Transporte Modbus TCP (MBAP) sobre los sockets del nucleo.
#include <algorithm>
#include "ModbusTCP.h"

void ModbusTCP::server(uint16_t puerto) {
    if (srv_) return;
    srv_ = new ServidorTCP(puerto);
    srv_->begin();
}

void ModbusTCP::task() {
    if (srv_) {
        // Conexiones nuevas: hasta MODBUSIP_MAX_CLIENTS; la de mas se cierra.
        for (;;) {
            ClienteTCP c = srv_->accept();
            if (!c) break;
            entrantes_.erase(std::remove_if(entrantes_.begin(), entrantes_.end(),
                                            [](Conexion& x) { return !x.c.connected(); }),
                             entrantes_.end());
            if (entrantes_.size() >= MODBUSIP_MAX_CLIENTS) {
                c.stop();
                continue;
            }
            entrantes_.push_back(Conexion{c, {}, c.remoteIP()});
        }
        for (auto& x : entrantes_) atender(x);
        entrantes_.erase(std::remove_if(entrantes_.begin(), entrantes_.end(),
                                        [](Conexion& x) { return !x.c.connected() && x.c.available() == 0; }),
                         entrantes_.end());
    }
    for (auto& x : salientes_) respuestas(x);
    // Timeouts del lado cliente.
    unsigned long ahora = millis();
    for (size_t i = 0; i < pendientes_.size();) {
        if (ahora - pendientes_[i].t0 >= MODBUSIP_TIMEOUT) {
            ModbusTransaccion t = pendientes_[i];
            pendientes_.erase(pendientes_.begin() + i);
            if (t.cb) t.cb(EX_TIMEOUT, t.tid, nullptr);
        } else {
            i++;
        }
    }
}

void ModbusTCP::atender(Conexion& x) {
    while (x.c.available() > 0) {
        int b = x.c.read();
        if (b < 0) break;
        x.buf.push_back((uint8_t)b);
    }
    while (x.buf.size() >= 7) {
        uint16_t len = (x.buf[4] << 8) | x.buf[5];
        if (len < 2 || len > 254) { x.buf.clear(); x.c.stop(); return; }
        if (x.buf.size() < (size_t)(6 + len)) return;
        std::vector<uint8_t> resp = atenderPDU(&x.buf[7], len - 1);
        std::vector<uint8_t> adu(x.buf.begin(), x.buf.begin() + 7);   // TID, PID, LEN, UNIT
        adu[4] = (uint8_t)((resp.size() + 1) >> 8);
        adu[5] = (uint8_t)(resp.size() + 1);
        adu.insert(adu.end(), resp.begin(), resp.end());
        x.c.write(adu.data(), adu.size());
        x.buf.erase(x.buf.begin(), x.buf.begin() + 6 + len);
    }
}

void ModbusTCP::respuestas(Conexion& x) {
    while (x.c.available() > 0) {
        int b = x.c.read();
        if (b < 0) break;
        x.buf.push_back((uint8_t)b);
    }
    while (x.buf.size() >= 7) {
        uint16_t len = (x.buf[4] << 8) | x.buf[5];
        if (x.buf.size() < (size_t)(6 + len)) return;
        uint16_t tid = (x.buf[0] << 8) | x.buf[1];
        std::vector<uint8_t> pdu(x.buf.begin() + 7, x.buf.begin() + 6 + len);
        x.buf.erase(x.buf.begin(), x.buf.begin() + 6 + len);
        for (size_t i = 0; i < pendientes_.size(); i++) {
            if (pendientes_[i].tid != tid) continue;
            ModbusTransaccion t = pendientes_[i];
            pendientes_.erase(pendientes_.begin() + i);
            ResultCode r = leerRespuesta(t.fc, pdu, t.destino, t.num);
            if (t.cb) t.cb(r, t.tid, nullptr);
            break;
        }
    }
}

ModbusTCP::Conexion* ModbusTCP::conexion(IPAddress ip) {
    for (auto& x : salientes_)
        if (x.ip == ip) return &x;
    return nullptr;
}

bool ModbusTCP::connect(IPAddress ip, uint16_t puerto) {
    Conexion* x = conexion(ip);
    if (x && x->c.connected()) return true;
    ClienteTCP c;
    if (!c.connect(ip, puerto)) return false;
    if (x) {
        x->c = c;
        x->buf.clear();
    } else {
        salientes_.push_back(Conexion{c, {}, ip});
    }
    return true;
}

bool ModbusTCP::isConnected(IPAddress ip) {
    Conexion* x = conexion(ip);
    return x && x->c.connected();
}

bool ModbusTCP::disconnect(IPAddress ip) {
    Conexion* x = conexion(ip);
    if (!x) return false;
    x->c.stop();
    return true;
}

void ModbusTCP::dropTransactions() {
    for (auto& t : pendientes_)
        if (t.cb) t.cb(EX_CANCEL, t.tid, nullptr);
    pendientes_.clear();
}

bool ModbusTCP::isTransaction(uint16_t tid) {
    for (auto& t : pendientes_)
        if (t.tid == tid) return true;
    return false;
}

uint16_t ModbusTCP::pedir(IPAddress ip, uint8_t unit, uint8_t fc, uint16_t o, uint16_t n,
                          const uint8_t* datos, void* destino, cbTransaction cb, size_t nb) {
    Conexion* x = conexion(ip);
    if (!x || !x->c.connected()) return 0;
    std::vector<uint8_t> pdu{fc, (uint8_t)(o >> 8), (uint8_t)o};
    if (fc == FC_WRITE_REG || fc == FC_WRITE_COIL) {
        pdu.push_back(datos[0]);
        pdu.push_back(datos[1]);
    } else {
        pdu.push_back((uint8_t)(n >> 8));
        pdu.push_back((uint8_t)n);
        if (fc == FC_WRITE_REGS || fc == FC_WRITE_COILS) {
            pdu.push_back((uint8_t)nb);
            pdu.insert(pdu.end(), datos, datos + nb);
        }
    }
    tid_++;
    if (tid_ == 0) tid_ = 1;
    std::vector<uint8_t> adu{(uint8_t)(tid_ >> 8), (uint8_t)tid_, 0, 0,
                             (uint8_t)((pdu.size() + 1) >> 8), (uint8_t)(pdu.size() + 1), unit};
    adu.insert(adu.end(), pdu.begin(), pdu.end());
    x->c.write(adu.data(), adu.size());
    ModbusTransaccion t;
    t.tid = tid_;
    t.unidad = unit;
    t.fc = fc;
    t.num = n;
    t.destino = destino;
    t.cb = cb;
    t.t0 = millis();
    pendientes_.push_back(t);
    return tid_;
}

uint16_t ModbusTCP::writeHreg(IPAddress ip, uint16_t o, uint16_t* v, uint16_t n, cbTransaction cb, uint8_t unit) {
    std::vector<uint8_t> d;
    for (uint16_t i = 0; i < n; i++) {
        d.push_back(v[i] >> 8);
        d.push_back(v[i] & 0xFF);
    }
    return pedir(ip, unit, FC_WRITE_REGS, o, n, d.data(), nullptr, cb, d.size());
}

uint16_t ModbusTCP::writeCoil(IPAddress ip, uint16_t o, bool* v, uint16_t n, cbTransaction cb, uint8_t unit) {
    std::vector<uint8_t> d((n + 7) / 8, 0);
    for (uint16_t i = 0; i < n; i++)
        if (v[i]) d[i / 8] |= 1 << (i % 8);
    return pedir(ip, unit, FC_WRITE_COILS, o, n, d.data(), nullptr, cb, d.size());
}
