// MQTT 3.1.1 minimo (QoS 0) para PubSubClient.h.
#include "PubSubClient.h"

static std::string cadena(const char* t) {
    size_t n = t ? strlen(t) : 0;
    std::string r;
    r += (char)(n >> 8);
    r += (char)(n & 0xff);
    if (n) r.append(t, n);
    return r;
}

bool PubSubClient::enviar(uint8_t cab, const std::string& cuerpo) {
    if (!cliente) return false;
    std::string p(1, (char)cab);
    size_t n = cuerpo.size();
    do {
        uint8_t b = n % 128;
        n /= 128;
        if (n) b |= 0x80;
        p += (char)b;
    } while (n);
    p += cuerpo;
    bool ok = cliente->write((const uint8_t*)p.data(), p.size()) == p.size();
    if (ok) t_tx = millis();
    return ok;
}

bool PubSubClient::leer_paquete(uint8_t& cab, std::string& cuerpo, unsigned long espera) {
    auto byte_ = [&](int& c) {
        unsigned long t = millis();
        while (!cliente->available()) {
            if (!cliente->connected() || millis() - t > espera) return false;
            delay(1);
        }
        c = cliente->read();
        return c >= 0;
    };
    int c;
    if (!byte_(c)) return false;
    cab = (uint8_t)c;
    size_t n = 0, mult = 1;
    do {
        if (!byte_(c)) return false;
        n += (c & 0x7f) * mult;
        mult *= 128;
    } while (c & 0x80);
    cuerpo.clear();
    while (cuerpo.size() < n) {
        if (!byte_(c)) return false;
        cuerpo += (char)c;
    }
    t_rx = millis();
    return true;
}

bool PubSubClient::connect(const char* id, const char* usuario, const char* clave, const char* tema_will,
                           uint8_t qos, bool retenido, const char* msg_will, bool limpia) {
    if (!cliente) return false;
    if (connected()) return true;
    bool ok = host.empty() ? cliente->connect(ip, puerto) : cliente->connect(host.c_str(), puerto);
    if (!ok) { estado = MQTT_CONNECT_FAILED; return false; }
    uint8_t banderas = limpia ? 0x02 : 0;
    if (tema_will) banderas |= 0x04 | (qos << 3) | (retenido ? 0x20 : 0);
    if (usuario) banderas |= 0x80;
    if (usuario && clave) banderas |= 0x40;
    std::string c = cadena("MQTT");
    c += (char)MQTT_VERSION_3_1_1;
    c += (char)banderas;
    c += (char)(keepalive >> 8);
    c += (char)(keepalive & 0xff);
    c += cadena(id);
    if (tema_will) { c += cadena(tema_will); c += cadena(msg_will ? msg_will : ""); }
    if (usuario) c += cadena(usuario);
    if (usuario && clave) c += cadena(clave);
    if (!enviar(0x10, c)) { estado = MQTT_CONNECT_FAILED; cliente->stop(); return false; }
    uint8_t cab;
    std::string r;
    if (!leer_paquete(cab, r, MQTT_SOCKET_TIMEOUT * 1000UL) || (cab & 0xf0) != 0x20 || r.size() < 2) {
        estado = MQTT_CONNECTION_TIMEOUT;
        cliente->stop();
        return false;
    }
    estado = (uint8_t)r[1];
    if (estado != MQTT_CONNECTED) { cliente->stop(); return false; }
    ping_pendiente = false;
    t_rx = millis();
    return true;
}

void PubSubClient::disconnect() {
    if (cliente && cliente->connected()) enviar(0xE0, "");
    if (cliente) cliente->stop();
    estado = MQTT_DISCONNECTED;
}

bool PubSubClient::publish(const char* tema, const uint8_t* carga, unsigned int n, bool retenido) {
    if (!connected()) return false;
    std::string c = cadena(tema);
    c.append((const char*)carga, n);
    return enviar(0x30 | (retenido ? 1 : 0), c);
}

bool PubSubClient::beginPublish(const char* tema, unsigned int n, bool retenido) {
    (void)n;
    tema_publicando = tema;
    retenido_publicando = retenido;
    publicando.clear();
    return connected();
}

int PubSubClient::endPublish() {
    return publish(tema_publicando.c_str(), (const uint8_t*)publicando.data(),
                   (unsigned int)publicando.size(), retenido_publicando) ? 1 : 0;
}

bool PubSubClient::subscribe(const char* tema, uint8_t qos) {
    if (!connected()) return false;
    id_msg = id_msg == 0xffff ? 1 : id_msg + 1;
    std::string c;
    c += (char)(id_msg >> 8);
    c += (char)(id_msg & 0xff);
    c += cadena(tema);
    c += (char)(qos > 1 ? 1 : qos);
    return enviar(0x82, c);
}

bool PubSubClient::unsubscribe(const char* tema) {
    if (!connected()) return false;
    id_msg = id_msg == 0xffff ? 1 : id_msg + 1;
    std::string c;
    c += (char)(id_msg >> 8);
    c += (char)(id_msg & 0xff);
    c += cadena(tema);
    return enviar(0xA2, c);
}

bool PubSubClient::loop() {
    if (!connected()) return false;
    unsigned long ahora = millis();
    if (keepalive && (ahora - t_tx > keepalive * 1000UL || ahora - t_rx > keepalive * 1000UL)) {
        if (ping_pendiente) {                     // el broker no contesto al ping
            estado = MQTT_CONNECTION_TIMEOUT;
            cliente->stop();
            return false;
        }
        enviar(0xC0, "");
        ping_pendiente = true;
    }
    while (cliente->available()) {
        uint8_t cab;
        std::string r;
        if (!leer_paquete(cab, r, 1000)) break;
        uint8_t tipo = cab & 0xf0;
        if (tipo == 0x30 && r.size() >= 2) {      // PUBLISH
            size_t nt = ((uint8_t)r[0] << 8) | (uint8_t)r[1];
            size_t ini = 2 + nt + (((cab >> 1) & 3) ? 2 : 0);
            if (ini > r.size()) continue;
            std::string tema = r.substr(2, nt);
            std::string carga = r.substr(ini);
            if (callback) callback((char*)tema.c_str(), (uint8_t*)carga.data(), (unsigned int)carga.size());
        } else if (tipo == 0xD0) {                // PINGRESP
            ping_pendiente = false;
        } else if (tipo == 0xC0) {                // PINGREQ del broker
            enviar(0xD0, "");
        }
    }
    return connected();
}

bool PubSubClient::connected() {
    if (!cliente) return false;
    bool c = cliente->connected();
    if (!c && estado == MQTT_CONNECTED) estado = MQTT_CONNECTION_LOST;
    return c && estado == MQTT_CONNECTED;
}
