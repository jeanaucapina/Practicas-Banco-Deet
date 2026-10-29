// Sockets TCP para Client/Server, Ethernet y WiFi del nucleo virtual.
#include "red.h"
#include "Ethernet.h"
#include "WiFi.h"

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <mutex>
#include <string>

struct Socket {
    int fd = -1;
    ~Socket() { if (fd >= 0) ::close(fd); }
};

static void sin_bloqueo(int fd) { fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK); }

namespace vino {
bool ip_en_red(const char* prefijo, IPAddress* ip) {
    ifaddrs* l = nullptr;
    if (getifaddrs(&l) != 0) return false;
    bool hay = false;
    for (ifaddrs* a = l; a && !hay; a = a->ifa_next) {
        if (!a->ifa_addr || a->ifa_addr->sa_family != AF_INET) continue;
        char t[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &((sockaddr_in*)a->ifa_addr)->sin_addr, t, sizeof t);
        if (strncmp(t, prefijo, strlen(prefijo)) == 0) {
            hay = true;
            if (ip) ip->fromString(t);
        }
    }
    freeifaddrs(l);
    return hay;
}
}  // namespace vino

// ── Cliente ─────────────────────────────────────────────────────────────────
int ClienteTCP::connect(IPAddress ip, uint16_t puerto) {
    return connect(ip.toString().c_str(), puerto);
}

int ClienteTCP::connect(const char* host, uint16_t puerto) {
    stop();
    addrinfo pista{}, *r = nullptr;
    pista.ai_family = AF_INET;
    pista.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host, std::to_string(puerto).c_str(), &pista, &r) != 0 || !r) return 0;
    auto x = std::make_shared<Socket>();
    x->fd = socket(AF_INET, SOCK_STREAM, 0);
    sin_bloqueo(x->fd);
    int u = 1;
    setsockopt(x->fd, IPPROTO_TCP, TCP_NODELAY, &u, sizeof u);
    int rc = ::connect(x->fd, r->ai_addr, r->ai_addrlen);
    freeaddrinfo(r);
    if (rc != 0 && errno != EINPROGRESS) return 0;
    pollfd p{x->fd, POLLOUT, 0};
    if (poll(&p, 1, (int)(_timeout ? _timeout : 1000)) <= 0) return 0;   // sin red: como el real, tarda y falla
    int err = 0;
    socklen_t n = sizeof err;
    getsockopt(x->fd, SOL_SOCKET, SO_ERROR, &err, &n);
    if (err) return 0;
    s = x;
    return 1;
}

size_t ClienteTCP::write(const uint8_t* b, size_t n) {
    if (!s || s->fd < 0) return 0;
    size_t k = 0;
    unsigned long t = millis();
    while (k < n && millis() - t < 2000) {
        ssize_t r = ::send(s->fd, b + k, n - k, MSG_NOSIGNAL);
        if (r > 0) k += r;
        else if (r < 0 && errno != EAGAIN) { stop(); break; }
        else delay(1);
    }
    return k;
}

int ClienteTCP::available() {
    if (!s || s->fd < 0) return 0;
    uint8_t b[2048];
    ssize_t r = ::recv(s->fd, b, sizeof b, MSG_PEEK | MSG_DONTWAIT);
    return r > 0 ? (int)r : 0;
}

int ClienteTCP::read() {
    uint8_t c;
    return read(&c, 1) == 1 ? c : -1;
}

int ClienteTCP::read(uint8_t* b, size_t n) {
    if (!s || s->fd < 0) return -1;
    ssize_t r = ::recv(s->fd, b, n, MSG_DONTWAIT);
    return r > 0 ? (int)r : -1;
}

int ClienteTCP::peek() {
    if (!s || s->fd < 0) return -1;
    uint8_t c;
    return ::recv(s->fd, &c, 1, MSG_PEEK | MSG_DONTWAIT) == 1 ? c : -1;
}

void ClienteTCP::stop() {
    if (s && s->fd >= 0) { ::close(s->fd); s->fd = -1; }
    s.reset();
}

uint8_t ClienteTCP::connected() {
    if (!s || s->fd < 0) return 0;
    uint8_t c;
    ssize_t r = ::recv(s->fd, &c, 1, MSG_PEEK | MSG_DONTWAIT);
    if (r == 0) return 0;                                   // el otro cerro
    if (r < 0 && errno != EAGAIN && errno != EWOULDBLOCK) return 0;
    return 1;
}

ClienteTCP::operator bool() { return s && s->fd >= 0; }

IPAddress ClienteTCP::remoteIP() {
    IPAddress ip;
    sockaddr_in a{};
    socklen_t n = sizeof a;
    if (s && getpeername(s->fd, (sockaddr*)&a, &n) == 0) {
        char t[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &a.sin_addr, t, sizeof t);
        ip.fromString(t);
    }
    return ip;
}

uint16_t ClienteTCP::remotePort() {
    sockaddr_in a{};
    socklen_t n = sizeof a;
    return s && getpeername(s->fd, (sockaddr*)&a, &n) == 0 ? ntohs(a.sin_port) : 0;
}

// ── Servidor ────────────────────────────────────────────────────────────────
void ServidorTCP::begin(uint16_t p) {
    if (p) puerto = p;
    fd = socket(AF_INET, SOCK_STREAM, 0);
    int u = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &u, sizeof u);
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons(puerto);
    a.sin_addr.s_addr = INADDR_ANY;
    if (bind(fd, (sockaddr*)&a, sizeof a) != 0 || listen(fd, 8) != 0) {
        vino::aviso("servidor TCP: el puerto %u no esta libre", puerto);
        ::close(fd);
        fd = -1;
        return;
    }
    sin_bloqueo(fd);
}

void ServidorTCP::aceptar() {
    if (fd < 0) return;
    for (;;) {
        int c = ::accept(fd, nullptr, nullptr);
        if (c < 0) break;
        sin_bloqueo(c);
        auto x = std::make_shared<Socket>();
        x->fd = c;
        clientes.push_back(x);
    }
}

ClienteTCP ServidorTCP::available() {
    aceptar();
    for (size_t i = 0; i < clientes.size();) {
        ClienteTCP c(clientes[i]);
        if (!c.connected()) { clientes.erase(clientes.begin() + i); continue; }
        if (c.available()) return c;
        i++;
    }
    return ClienteTCP();
}

ClienteTCP ServidorTCP::accept() {
    if (fd < 0) return ClienteTCP();
    int c = ::accept(fd, nullptr, nullptr);
    if (c < 0) return ClienteTCP();
    sin_bloqueo(c);
    auto x = std::make_shared<Socket>();
    x->fd = c;
    return ClienteTCP(x);
}

size_t ServidorTCP::write(const uint8_t* b, size_t n) {
    aceptar();
    for (auto& x : clientes) ClienteTCP(x).write(b, n);
    return n;
}

// ── Ethernet / WiFi ─────────────────────────────────────────────────────────
// El segmento del banco es 192.168.1.0/24 (switch del tablero y punto de acceso
// WiFi del laboratorio, puenteados). La IP la pide el programa, como en el real:
// Ethernet.begin(mac, ip) o WiFi.config(ip, ...) fijan una; Ethernet.begin(mac) o
// WiFi.begin() sin config piden DHCP. La pasarela conecta el contenedor con esa IP
// y avisa al programa ("N cable wifi ip") de si hay enlace y con que direccion.
EthernetClass Ethernet;
WiFiClass WiFi;

namespace {
std::mutex g_m_red;
bool g_cable = false, g_wifi = false;
std::string g_ip;
int g_rssi = -55;

void pedir(const char* iface, IPAddress ip, const uint8_t* mac, bool radio) {
    char m[18] = "-";
    if (mac) snprintf(m, sizeof m, "%02x:%02x:%02x:%02x:%02x:%02x", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    std::string que = ip == IPAddress() ? std::string("dhcp") : std::string(ip.toString().c_str());
    if (que != "dhcp" && !(ip[0] == 192 && ip[1] == 168 && ip[2] == 1)) {
        vino::aviso("%s: %s no es del segmento del banco (192.168.1.0/24): no habra enlace", iface,
                    que.c_str());
    }
    vino::red_pedir(std::string(iface) + " " + que + " " + m + (radio ? " 1" : " 0"));
}

// Espera (como el real) a que la red quede lista: la pasarela tarda ~1 s.
bool esperar(bool (*ok)(), unsigned long ms) {
    unsigned long t = millis();
    while (!ok() && millis() - t < ms) delay(50);
    return ok();
}
bool con_cable() { std::lock_guard<std::mutex> g(g_m_red); return g_cable && !g_ip.empty(); }
bool con_wifi() { std::lock_guard<std::mutex> g(g_m_red); return g_wifi && !g_ip.empty(); }
IPAddress ip_actual() {
    std::lock_guard<std::mutex> g(g_m_red);
    IPAddress ip;
    ip.fromString(g_ip.c_str());
    return ip;
}
}  // namespace

namespace vino {
void red_estado(bool cable, bool wifi, const char* ip, int rssi) {
    std::lock_guard<std::mutex> g(g_m_red);
    g_cable = cable;
    g_wifi = wifi;
    g_ip = ip ? ip : "";
    if (rssi < 0) g_rssi = rssi;
}
}  // namespace vino

int EthernetClass::begin(uint8_t* mac, unsigned long timeout, unsigned long) {
    pedir("Ethernet", IPAddress(), mac, false);                   // DHCP
    return esperar(con_cable, timeout < 8000 ? timeout : 8000) ? 1 : 0;
}

void EthernetClass::begin(uint8_t* mac, IPAddress ip) {
    pedir("Ethernet", ip, mac, false);
    esperar(con_cable, 2500);
}

IPAddress EthernetClass::localIP() { return con_cable() ? ip_actual() : IPAddress(); }
IPAddress EthernetClass::gatewayIP() { return IPAddress(192, 168, 1, 1); }
IPAddress EthernetClass::subnetMask() { return IPAddress(255, 255, 255, 0); }
int EthernetClass::linkStatus() { std::lock_guard<std::mutex> g(g_m_red); return g_cable ? LinkON : LinkOFF; }

int WiFiClass::begin(const char* ssid, const char* clave) {
    (void)clave;
    pedida = true;
    ssid_ = ssid ? ssid : "";
    pedir("WiFi", fija, nullptr, true);
    return status();
}

int WiFiClass::status() {
    if (!pedida) return WL_IDLE_STATUS;
    return con_wifi() ? WL_CONNECTED : WL_DISCONNECTED;
}

IPAddress WiFiClass::localIP() { return con_wifi() ? ip_actual() : IPAddress(); }

bool WiFiClass::config(IPAddress ip, IPAddress, IPAddress, IPAddress, IPAddress) {
    fija = ip;
    if (pedida) pedir("WiFi", fija, nullptr, true);
    return true;
}

bool WiFiClass::disconnect(bool) {
    pedida = false;
    vino::red_pedir("WiFi - - 0");
    return true;
}

int8_t WiFiClass::RSSI() {
    std::lock_guard<std::mutex> g(g_m_red);
    // El RSSI real nunca esta quieto (multitrayecto, gente que pasa): ±3 dB
    // alrededor del valor de la posicion del banco. Por eso la guia pide la mediana.
    return g_wifi ? (int8_t)(g_rssi + (rand() % 7) - 3) : 0;
}
