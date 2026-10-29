// Client/Server TCP de Arduino sobre sockets de verdad. El contenedor del
// equipo esta (o no) en el segmento del banco, tab_lan (192.168.1.0/24): por
// cable si su RJ45 llega a un switch, por WiFi si el programa la pidio. La IP
// la pide el programa (Ethernet.begin, WiFi.config) y la aplica la pasarela.
#pragma once
#include <Arduino.h>

#include <memory>
#include <string>
#include <vector>

struct Socket;   // red.cpp

class Client : public Stream {
public:
    virtual int connect(IPAddress ip, uint16_t puerto) = 0;
    virtual int connect(const char* host, uint16_t puerto) = 0;
    virtual uint8_t connected() = 0;
    virtual void stop() = 0;
    virtual operator bool() = 0;
};

class ClienteTCP : public Client {
protected:
    std::shared_ptr<Socket> s;
public:
    ClienteTCP() {}
    explicit ClienteTCP(std::shared_ptr<Socket> x) : s(std::move(x)) {}
    int connect(IPAddress ip, uint16_t puerto) override;
    int connect(const char* host, uint16_t puerto) override;
    int connect(const String& host, uint16_t puerto) { return connect(host.c_str(), puerto); }
    size_t write(uint8_t c) override { return write(&c, 1); }
    size_t write(const uint8_t* b, size_t n) override;
    using Print::write;
    int available() override;
    int read() override;
    int read(uint8_t* b, size_t n);
    int peek() override;
    void flush() override {}
    void stop() override;
    uint8_t connected() override;
    operator bool() override;
    bool operator==(const ClienteTCP& o) const { return s == o.s; }
    bool operator!=(const ClienteTCP& o) const { return s != o.s; }
    IPAddress remoteIP();
    uint16_t remotePort();
    void setTimeout(unsigned long ms) { _timeout = ms; }
};

class ServidorTCP : public Print {
    uint16_t puerto;
    int fd = -1;
    std::vector<std::shared_ptr<Socket>> clientes;
    void aceptar();
public:
    explicit ServidorTCP(uint16_t p) : puerto(p) {}
    void begin(uint16_t p = 0);
    ClienteTCP available();           // un cliente con datos (como Arduino)
    ClienteTCP accept();              // el siguiente cliente nuevo
    size_t write(uint8_t c) override { return write(&c, 1); }
    size_t write(const uint8_t* b, size_t n) override;   // a todos
    using Print::write;
    operator bool() const { return fd >= 0; }
};

namespace vino {
bool ip_en_red(const char* prefijo, IPAddress* ip);   // "192.168.1."
void red_pedir(const std::string& linea);            // nucleo.cpp: "n <linea>"
void red_estado(bool cable, bool wifi, const char* ip, int rssi);
}
