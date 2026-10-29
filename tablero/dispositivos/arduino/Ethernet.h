// Ethernet (W5100 del Controllino, W5500 del ESP32 PLC) en el tablero virtual.
// Solo hay "enlace" si en las gafas el cable del equipo esta en el switch.
#pragma once
#include "red.h"

enum EthernetLinkStatus { Unknown, LinkON, LinkOFF };
enum EthernetHardwareStatus { EthernetNoHardware, EthernetW5100, EthernetW5200, EthernetW5500 };

class EthernetClass {
public:
    int begin(uint8_t* mac, unsigned long timeout = 60000, unsigned long respuesta = 4000);
    void begin(uint8_t* mac, IPAddress ip);
    void begin(uint8_t* mac, IPAddress ip, IPAddress dns) { begin(mac, ip); (void)dns; }
    void begin(uint8_t* mac, IPAddress ip, IPAddress dns, IPAddress gw) { begin(mac, ip); (void)dns; (void)gw; }
    void begin(uint8_t* mac, IPAddress ip, IPAddress dns, IPAddress gw, IPAddress mascara) {
        begin(mac, ip); (void)dns; (void)gw; (void)mascara;
    }
    void init(uint8_t pin_cs) { (void)pin_cs; }
    IPAddress localIP();
    IPAddress gatewayIP();
    IPAddress subnetMask();
    IPAddress dnsServerIP() { return gatewayIP(); }
    int linkStatus();
    int hardwareStatus() { return EthernetW5500; }
    int maintain() { return 0; }
};
extern EthernetClass Ethernet;

class EthernetClient : public ClienteTCP {
public:
    using ClienteTCP::ClienteTCP;
    EthernetClient() {}
    EthernetClient(const ClienteTCP& c) : ClienteTCP(c) {}
};

class EthernetServer : public ServidorTCP {
public:
    using ServidorTCP::ServidorTCP;
    EthernetClient available() { return EthernetClient(ServidorTCP::available()); }
    EthernetClient accept() { return EthernetClient(ServidorTCP::accept()); }
};
