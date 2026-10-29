// PubSubClient (cliente MQTT de knolleary) con la misma API, sobre el Client
// del nucleo: MQTT 3.1.1, QoS 0. Es la libreria MQTT habitual en Arduino y
// ESP32, asi que el .ino compila tambien para la placa real.
#pragma once
#include "red.h"

#define MQTT_VERSION_3_1_1 4
#define MQTT_MAX_PACKET_SIZE 256
#define MQTT_KEEPALIVE 15
#define MQTT_SOCKET_TIMEOUT 15

#define MQTT_CONNECTION_TIMEOUT -4
#define MQTT_CONNECTION_LOST -3
#define MQTT_CONNECT_FAILED -2
#define MQTT_DISCONNECTED -1
#define MQTT_CONNECTED 0
#define MQTT_CONNECT_BAD_PROTOCOL 1
#define MQTT_CONNECT_BAD_CLIENT_ID 2
#define MQTT_CONNECT_UNAVAILABLE 3
#define MQTT_CONNECT_BAD_CREDENTIALS 4
#define MQTT_CONNECT_UNAUTHORIZED 5

#define MQTT_CALLBACK_SIGNATURE std::function<void(char*, uint8_t*, unsigned int)> callback

class PubSubClient : public Print {
    Client* cliente = nullptr;
    std::string host;
    IPAddress ip;
    uint16_t puerto = 1883;
    MQTT_CALLBACK_SIGNATURE;
    int estado = MQTT_DISCONNECTED;
    uint16_t keepalive = MQTT_KEEPALIVE;
    unsigned long t_tx = 0, t_rx = 0;
    bool ping_pendiente = false;
    uint16_t id_msg = 0;
    size_t tam_buffer = MQTT_MAX_PACKET_SIZE;
    std::string publicando;        // beginPublish/endPublish

    bool enviar(uint8_t tipo, const std::string& cuerpo);
    bool leer_paquete(uint8_t& cab, std::string& cuerpo, unsigned long espera);
public:
    PubSubClient() {}
    explicit PubSubClient(Client& c) : cliente(&c) {}
    PubSubClient(IPAddress i, uint16_t p, Client& c) : cliente(&c) { setServer(i, p); }
    PubSubClient& setClient(Client& c) { cliente = &c; return *this; }
    PubSubClient& setServer(IPAddress i, uint16_t p) { ip = i; host.clear(); puerto = p; return *this; }
    PubSubClient& setServer(const char* h, uint16_t p) { host = h; puerto = p; return *this; }
    PubSubClient& setServer(uint8_t* i, uint16_t p) { return setServer(IPAddress(i[0], i[1], i[2], i[3]), p); }
    PubSubClient& setCallback(std::function<void(char*, uint8_t*, unsigned int)> f) { callback = f; return *this; }
    PubSubClient& setKeepAlive(uint16_t s) { keepalive = s; return *this; }
    PubSubClient& setSocketTimeout(uint16_t) { return *this; }
    bool setBufferSize(uint16_t n) { tam_buffer = n; return true; }
    uint16_t getBufferSize() { return (uint16_t)tam_buffer; }

    bool connect(const char* id) { return connect(id, nullptr, nullptr, nullptr, 0, false, nullptr, true); }
    bool connect(const char* id, const char* usuario, const char* clave) {
        return connect(id, usuario, clave, nullptr, 0, false, nullptr, true);
    }
    bool connect(const char* id, const char* tema_will, uint8_t qos, bool retenido, const char* msg_will) {
        return connect(id, nullptr, nullptr, tema_will, qos, retenido, msg_will, true);
    }
    bool connect(const char* id, const char* usuario, const char* clave, const char* tema_will,
                 uint8_t qos, bool retenido, const char* msg_will, bool sesion_limpia = true);
    void disconnect();
    bool publish(const char* tema, const char* carga) { return publish(tema, (const uint8_t*)carga, strlen(carga), false); }
    bool publish(const char* tema, const char* carga, bool retenido) {
        return publish(tema, (const uint8_t*)carga, strlen(carga), retenido);
    }
    bool publish(const char* tema, const uint8_t* carga, unsigned int n) { return publish(tema, carga, n, false); }
    bool publish(const char* tema, const uint8_t* carga, unsigned int n, bool retenido);
    bool publish_P(const char* tema, const char* carga, bool retenido) { return publish(tema, carga, retenido); }
    bool beginPublish(const char* tema, unsigned int n, bool retenido);
    size_t write(uint8_t c) override { publicando += (char)c; return 1; }
    size_t write(const uint8_t* b, size_t n) override { publicando.append((const char*)b, n); return n; }
    int endPublish();
    bool subscribe(const char* tema, uint8_t qos = 0);
    bool unsubscribe(const char* tema);
    bool loop();
    bool connected();
    int state() { return estado; }
private:
    std::string tema_publicando;
    bool retenido_publicando = false;
};
