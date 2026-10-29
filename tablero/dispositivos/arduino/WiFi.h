// WiFi del ESP32 en el tablero virtual: el punto de acceso del laboratorio esta
// en el segmento del banco (192.168.1.0/24). WiFi.begin() se asocia (el SSID y la
// clave no se comprueban) y pide DHCP, o la IP de WiFi.config(). El RSSI depende
// de la posicion del banco que se elija en el portal (A: linea de vista, B: tras
// una pared).
#pragma once
#include "red.h"

#define WL_IDLE_STATUS 0
#define WL_NO_SSID_AVAIL 1
#define WL_CONNECTED 3
#define WL_CONNECT_FAILED 4
#define WL_CONNECTION_LOST 5
#define WL_DISCONNECTED 6
#define WIFI_OFF 0
#define WIFI_STA 1
#define WIFI_AP 2
#define WIFI_AP_STA 3

class WiFiClass {
    bool pedida = false;
    std::string ssid_;
    IPAddress fija;
public:
    int begin(const char* ssid, const char* clave = nullptr);
    int begin(const String& ssid, const String& clave) { return begin(ssid.c_str(), clave.c_str()); }
    int status();
    bool isConnected() { return status() == WL_CONNECTED; }
    bool config(IPAddress ip, IPAddress gw = IPAddress(), IPAddress mascara = IPAddress(),
                IPAddress dns1 = IPAddress(), IPAddress dns2 = IPAddress());
    IPAddress localIP();
    bool mode(int m) { (void)m; return true; }
    bool disconnect(bool apagar = false);
    bool reconnect() { return begin(ssid_.c_str()) == WL_CONNECTED; }
    void setAutoReconnect(bool) {}
    void setSleep(bool) {}
    String SSID() { return String(ssid_); }
    int8_t RSSI();
    String macAddress() { return String("24:6F:28:00:00:01"); }
    String BSSIDstr() { return String("B8:69:F4:3C:10:01"); }   // AP del laboratorio
    int32_t channel() { return 6; }
    IPAddress gatewayIP() { return IPAddress(192, 168, 1, 1); }
    IPAddress subnetMask() { return IPAddress(255, 255, 255, 0); }
    IPAddress dnsIP(uint8_t = 0) { return gatewayIP(); }
    String getHostname() { return String("esp32plc"); }
    bool setHostname(const char*) { return true; }
};
extern WiFiClass WiFi;

class WiFiClient : public ClienteTCP {
public:
    using ClienteTCP::ClienteTCP;
    WiFiClient() {}
    WiFiClient(const ClienteTCP& c) : ClienteTCP(c) {}
};

class WiFiServer : public ServidorTCP {
public:
    using ServidorTCP::ServidorTCP;
    WiFiClient available() { return WiFiClient(ServidorTCP::available()); }
    WiFiClient accept() { return WiFiClient(ServidorTCP::accept()); }
};
