// Nucleo Arduino virtual: main(), pines, tiempo, Serial y bus RS-485.
//
// Con programa.py habla por dos tuberias de texto (descriptores en
// VINO_FD_OUT / VINO_FD_IN), una linea por mensaje:
//   programa -> programa.py   "o <pin> <valor>"   una salida cambio
//                             "t <hex>"           trama al bus RS-485
//                             "a <texto>"         aviso para la consola de las gafas
//                             "h <hex>"           bytes de Serial2 hacia la HMI
//                             "l <hex>"           bytes de loraSerial hacia el RN2903 (ESP32)
//                             "n <iface> <ip|dhcp> <mac|-> <radio>"  el programa pide red
//   programa.py -> programa   "i <pin> <dig> <ana>"  una entrada cambio
//                             "r <hex>"              llego una trama del bus
//                             "H <hex>"              llegaron bytes de la HMI (Serial2)
//                             "L <hex>"              respuesta del RN2903 (loraSerial)
//                             "N <cable> <wifi> <ip|-> <rssi>"  estado de la red
// stdout es Serial (el monitor serie).
#include "Arduino.h"
#include "red.h"

#include <atomic>
#include <chrono>
#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <unistd.h>

static void llamar_isr(void (*f)());   // ISR con el bit I respetado (mas abajo)

namespace {

const int NPIN = 256;
std::atomic<int> g_dig[NPIN];       // entradas digitales (las pone programa.py)
std::atomic<int> g_ana[NPIN];       // entradas analogicas
std::atomic<int> g_sal[NPIN];       // salidas (lo que escribio el programa)
std::atomic<int> g_modo[NPIN];
void (*g_isr[NPIN])() = {};
int g_isr_modo[NPIN] = {};
int g_bits_adc = 0;                 // 0 = la resolucion nativa del equipo
std::atomic<int> g_carga{0};        // 0-100: saturacion del segmento (taller U6). Bajo carga,
                                    // la pila de red roba CPU al lazo y el loop() se ralentiza.

int g_fd_out = -1, g_fd_in = -1;
std::mutex g_m_out;
const auto g_t0 = std::chrono::steady_clock::now();

// Bus RS-485 con tiempos reales: cada byte ocupa el par lo que dura a los baudios de
// la UART (start + datos + paridad + parada). write() lo encola tras el anterior,
// flush() espera a que salga el ultimo bit y la trama se cierra tras 3,5 caracteres
// de silencio (o al flush / al volver a recepcion).
std::mutex g_m_bus;
std::deque<uint8_t> g_rx;
std::string g_tx;
long g_tx_ini = 0;                  // micros() en que empezo a salir la trama en curso
long g_tx_fin = 0;                  // micros() en que termina el ultimo byte encolado
unsigned long g_baud = 9600;
int g_bits_dato = 8, g_bits_car = 10;
std::string g_fmt = "8N1";
bool g_bus_tx = false;              // semiduplex: driver en transmision
bool g_bus_auto = true;             // la direccion la lleva el driver (ESP32)
bool g_aviso_dir = false;

double us_por_byte() { return g_bits_car * 1e6 / (double)g_baud; }
double us_t35() { return g_baud > 19200 ? 1750.0 : 3.5 * us_por_byte(); }

// Serial2 = la HMI (tipo Stone). Sin semiduplex ni direccion: bytes tal cual.
std::mutex g_m_h;
std::deque<uint8_t> g_h_rx;
std::string g_h_tx;
long g_h_t = 0;                     // micros() del ultimo byte escrito
// loraSerial (ESP32 PLC 14) = el RN2903 del slot LORA, tras el PIC puente. Bytes tal
// cual hacia programa.py, que emula el modulo (rn2903.py). Mismo cerrojo que la HMI.
std::deque<uint8_t> g_l_rx;
std::string g_l_tx;
long g_l_t = 0;

void enviar(const std::string& linea) {
    if (g_fd_out < 0) return;
    std::lock_guard<std::mutex> l(g_m_out);
    std::string t = linea + "\n";
    ssize_t r = ::write(g_fd_out, t.data(), t.size());
    (void)r;
}

std::string a_hex(const std::string& b) {
    static const char* d = "0123456789abcdef";
    std::string h;
    for (unsigned char c : b) { h += d[c >> 4]; h += d[c & 15]; }
    return h;
}

std::string de_hex(const std::string& h) {
    std::string b;
    for (size_t i = 0; i + 1 < h.size(); i += 2) b += (char)strtol(h.substr(i, 2).c_str(), nullptr, 16);
    return b;
}

// Con el bus bloqueado.
void cerrar_trama_ya() {
    if (g_tx.empty()) return;
    enviar("t " + a_hex(g_tx));
    g_tx.clear();
}

// Con g_m_h bloqueado.
void hmi_enviar_ya() {
    if (g_h_tx.empty()) return;
    enviar("h " + a_hex(g_h_tx));
    g_h_tx.clear();
}

// Con g_m_h bloqueado.
void lora_enviar_ya() {
    if (g_l_tx.empty()) return;
    enviar("l " + a_hex(g_l_tx));
    g_l_tx.clear();
}

void entrada(int pin, int dig, int ana) {
    if (pin < 0 || pin >= NPIN) return;
    int antes = g_dig[pin].exchange(dig);
    g_ana[pin] = ana;
    void (*f)() = g_isr[pin];
    if (f && antes != dig) {
        int m = g_isr_modo[pin];
        if (m == CHANGE || (m == RISING && dig) || (m == FALLING && !dig)) llamar_isr(f);
    }
}

// Generadores de pulsos: cuadrada de `hz` en la entrada `pin` (flancos de subida y de
// bajada, que disparan las ISR de attachInterrupt como un encoder de verdad).
std::atomic<double> g_pulsos_hz[NPIN];
std::atomic<bool> g_pulsos_hilo[NPIN];

void pulsos_fijar(int pin, double hz) {
    g_pulsos_hz[pin] = hz;
    bool falso = false;
    if (hz > 0 && g_pulsos_hilo[pin].compare_exchange_strong(falso, true)) {
        std::thread([pin]() {
            auto t = std::chrono::steady_clock::now();
            int nivel = 0;
            for (;;) {
                double f = g_pulsos_hz[pin];
                if (f <= 0) {
                    std::this_thread::sleep_for(std::chrono::milliseconds(5));
                    t = std::chrono::steady_clock::now();
                    continue;
                }
                t += std::chrono::nanoseconds((long long)(5e8 / f));       // medio periodo
                std::this_thread::sleep_until(t);
                nivel = 1 - nivel;
                entrada(pin, nivel, nivel ? 1023 : 0);
                if (std::chrono::steady_clock::now() - t > std::chrono::milliseconds(20))
                    t = std::chrono::steady_clock::now();
            }
        }).detach();
    }
}

void lector() {
    std::string buf;
    char tmp[4096];
    for (;;) {
        if (g_fd_in >= 0) {
            pollfd p{g_fd_in, POLLIN, 0};
            if (poll(&p, 1, 2) > 0) {
                ssize_t n = ::read(g_fd_in, tmp, sizeof tmp);
                if (n <= 0) _exit(0);              // programa.py se fue
                buf.append(tmp, n);
                size_t k;
                while ((k = buf.find('\n')) != std::string::npos) {
                    std::string l = buf.substr(0, k);
                    buf.erase(0, k + 1);
                    if (l.size() > 2 && l[0] == 'i') {
                        int pin = 0, dig = 0, ana = 0;
                        sscanf(l.c_str() + 2, "%d %d %d", &pin, &dig, &ana);
                        entrada(pin, dig, ana);
                    } else if (l.size() > 2 && l[0] == 'p') {
                        // Generador de pulsos (encoder del EPC): "p <pin> <hz>"; 0 lo para.
                        int pin = 0;
                        double hz = 0;
                        if (sscanf(l.c_str() + 2, "%d %lf", &pin, &hz) == 2 && pin >= 0 && pin < NPIN)
                            pulsos_fijar(pin, hz);
                    } else if (l.size() > 2 && l[0] == 'j') {
                        // Pulsador con rebote: "j <pin> <final> <ana> <t1> <t2> ... <tn>" en us
                        // desde ahora; el contacto alterna en cada t y acaba en <final>.
                        std::vector<long> t;
                        int pin = 0, fin = 0, ana = 0, n = 0;
                        const char* p = l.c_str() + 2;
                        if (sscanf(p, "%d %d %d%n", &pin, &fin, &ana, &n) >= 3) {
                            p += n;
                            long x;
                            while (sscanf(p, "%ld%n", &x, &n) == 1) { t.push_back(x); p += n; }
                            std::thread([pin, fin, ana, t]() {
                                auto t0 = std::chrono::steady_clock::now();
                                for (size_t k = 0; k < t.size(); k++) {
                                    std::this_thread::sleep_until(t0 + std::chrono::microseconds(t[k]));
                                    int nivel = (k == t.size() - 1) ? fin : ((k % 2 == 0) ? fin : 1 - fin);
                                    entrada(pin, nivel, ana);
                                }
                            }).detach();
                        }
                    } else if (l.size() > 2 && l[0] == 'N') {
                        int cable = 0, wifi = 0, rssi = 0;
                        char ip[32] = "";
                        sscanf(l.c_str() + 2, "%d %d %31s %d", &cable, &wifi, ip, &rssi);
                        vino::red_estado(cable, wifi, strcmp(ip, "-") ? ip : "", rssi);
                    } else if (l.size() >= 2 && l[0] == 'c') {
                        g_carga = atoi(l.c_str() + 2);      // saturacion del segmento (0-100)
                    } else if (l.size() > 2 && l[0] == 'H') {
                        std::string b = de_hex(l.substr(2));
                        std::lock_guard<std::mutex> g(g_m_h);
                        for (unsigned char c : b) g_h_rx.push_back(c);
                    } else if (l.size() > 2 && l[0] == 'L') {
                        std::string b = de_hex(l.substr(2));
                        std::lock_guard<std::mutex> g(g_m_h);
                        for (unsigned char c : b) g_l_rx.push_back(c);
                    } else if (l.size() > 2 && l[0] == 'r') {
                        std::string b = de_hex(l.substr(2));
                        std::lock_guard<std::mutex> g(g_m_bus);
                        // Un driver en transmision no escucha el bus.
                        if (g_bus_auto || !g_bus_tx)
                            for (unsigned char c : b) g_rx.push_back(c);
                    }
                }
            }
        } else {
            usleep(2000);
        }
        // Fin de trama: 3,5 caracteres de silencio tras el ultimo bit (a los baudios de la UART).
        std::lock_guard<std::mutex> g(g_m_bus);
        if (!g_tx.empty() && (long)micros() - g_tx_fin > (long)us_t35()) cerrar_trama_ya();
        std::lock_guard<std::mutex> gh(g_m_h);
        if (!g_h_tx.empty() && (long)micros() - g_h_t > 2000) hmi_enviar_ya();
        if (!g_l_tx.empty() && (long)micros() - g_l_t > 2000) lora_enviar_ya();
    }
}

}  // namespace

// ── Pines ───────────────────────────────────────────────────────────────────
void pinMode(uint8_t pin, uint8_t modo) { g_modo[pin] = modo; }

void digitalWrite(uint8_t pin, uint8_t valor) {
    int v = valor ? 1 : 0;
    if (g_sal[pin].exchange(v) != v) enviar("o " + std::to_string(pin) + " " + std::to_string(v));
}

void analogWrite(uint8_t pin, int valor) {
    valor = constrain(valor, 0, 255);
    if (g_sal[pin].exchange(valor) != valor)
        enviar("o " + std::to_string(pin) + " " + std::to_string(valor));
}

int digitalRead(uint8_t pin) {
    if (g_modo[pin] == OUTPUT) return g_sal[pin] ? HIGH : LOW;
    return g_dig[pin] ? HIGH : LOW;
}

void analogReadResolution(int bits) { g_bits_adc = constrain(bits, 8, 16); }

int analogRead(uint8_t pin) {
    // programa.py da la lectura a la resolucion del equipo real (10 bits en el
    // Controllino, 12 en el ESP32); analogReadResolution() la reescala.
    int v = g_ana[pin];
    int nativos = g_ana[255].load() > 0 ? g_ana[255].load() : 10;     // pin 255: bits del ADC
    // Sin analogReadResolution() cada placa lee a su resolucion de fabrica, como la
    // real: 10 bits el Controllino (AVR), 12 el ESP32.
    if (g_bits_adc == 0 || g_bits_adc == nativos) return v;
    return g_bits_adc > nativos ? v << (g_bits_adc - nativos) : v >> (nativos - g_bits_adc);
}

void attachInterrupt(uint8_t pin, void (*isr)(), int modo) { g_isr_modo[pin] = modo; g_isr[pin] = isr; }

// ── Interrupciones ──────────────────────────────────────────────────────────
// Un cerrojo global hace de bit I: una ISR espera mientras el programa lo tenga.
static std::recursive_mutex g_irq;
static thread_local bool g_irq_retenidas = false;
void noInterrupts() {
    if (!g_irq_retenidas) { g_irq.lock(); g_irq_retenidas = true; }
}
void interrupts() {
    if (g_irq_retenidas) { g_irq_retenidas = false; g_irq.unlock(); }
}
static void llamar_isr(void (*f)()) {
    if (!f) return;
    std::lock_guard<std::recursive_mutex> g(g_irq);
    f();
}

// Timer1: un hilo mira los registros y dispara la ISR al ritmo que dan (CTC u overflow).
static void hilo_timer1() {
    static const long PRESC[8] = {0, 1, 8, 64, 256, 1024, 0, 0};
    auto proximo = std::chrono::steady_clock::now();
    for (;;) {
        long p = PRESC[TCCR1B & 7];
        bool ctc = (TCCR1B & _BV(WGM12)) != 0;
        bool comp_a = (TIMSK1 & _BV(OCIE1A)) != 0 && TIMER1_COMPA_vect;
        bool ovf = (TIMSK1 & _BV(TOIE1)) != 0 && TIMER1_OVF_vect;
        if (p == 0 || (!comp_a && !ovf)) {
            std::this_thread::sleep_for(std::chrono::microseconds(500));
            proximo = std::chrono::steady_clock::now();
            continue;
        }
        long cuentas = ctc ? (long)OCR1A + 1 : 65536L;
        long periodo_us = std::max(20L, cuentas * p / 16);       // 16 MHz
        proximo += std::chrono::microseconds(periodo_us);
        std::this_thread::sleep_until(proximo);
        if (ctc && comp_a) llamar_isr(TIMER1_COMPA_vect);
        else if (!ctc && ovf) llamar_isr(TIMER1_OVF_vect);
        if (std::chrono::steady_clock::now() - proximo > std::chrono::milliseconds(50))
            proximo = std::chrono::steady_clock::now();          // no recuperar atrasos enormes
    }
}
void detachInterrupt(uint8_t pin) { g_isr[pin] = nullptr; }

// ── Tiempo y varios ─────────────────────────────────────────────────────────
unsigned long micros() {
    return (unsigned long)std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::steady_clock::now() - g_t0).count();
}
unsigned long millis() { return micros() / 1000; }
void delay(unsigned long ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
void delayMicroseconds(unsigned int us) { std::this_thread::sleep_for(std::chrono::microseconds(us)); }
void yield() { std::this_thread::yield(); }
long random(long hasta) { return hasta > 0 ? rand() % hasta : 0; }
long random(long desde, long hasta) { return hasta > desde ? desde + rand() % (hasta - desde) : desde; }
void randomSeed(unsigned long s) { srand(s); }
long map(long x, long a, long b, long c, long d) { return b == a ? c : (x - a) * (d - c) / (b - a) + c; }

// ── Print / Stream ──────────────────────────────────────────────────────────
size_t Print::write(const uint8_t* b, size_t n) {
    size_t k = 0;
    while (n--) k += write(*b++);
    return k;
}

size_t Print::print(const String& s) { return write(s.c_str()); }
size_t Print::print(const IPAddress& ip) { return print(ip.toString()); }

size_t Print::print(unsigned long n, int base) {
    if (base < 2 || base > 16) base = 10;
    char b[72];
    int i = sizeof b - 1;
    b[i] = 0;
    do { b[--i] = "0123456789ABCDEF"[n % base]; n /= base; } while (n && i > 0);
    return write(b + i);
}

size_t Print::print(long n, int base) {
    if (base == 10 && n < 0) return print('-') + print((unsigned long)(-n), 10);
    return print((unsigned long)n, base);
}

size_t Print::print(double n, int decimales) {
    char b[64];
    snprintf(b, sizeof b, "%.*f", decimales, n);
    return write(b);
}

size_t Print::printf(const char* fmt, ...) {
    char b[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(b, sizeof b, fmt, ap);
    va_end(ap);
    return write(b);
}

int Stream::esperar_byte() {
    unsigned long t = millis();
    do {
        if (available()) return read();
        delay(1);
    } while (millis() - t < _timeout);
    return -1;
}

size_t Stream::readBytes(char* b, size_t n) {
    size_t k = 0;
    while (k < n) {
        int c = esperar_byte();
        if (c < 0) break;
        b[k++] = (char)c;
    }
    return k;
}

size_t Stream::readBytesUntil(char fin, char* b, size_t n) {
    size_t k = 0;
    while (k < n) {
        int c = esperar_byte();
        if (c < 0 || c == fin) break;
        b[k++] = (char)c;
    }
    return k;
}

String Stream::readString() {
    std::string r;
    int c;
    while ((c = esperar_byte()) >= 0) r += (char)c;
    return String(r);
}

String Stream::readStringUntil(char fin) {
    std::string r;
    int c;
    while ((c = esperar_byte()) >= 0 && c != fin) r += (char)c;
    return String(r);
}

long Stream::parseInt() {
    int c;
    do { c = esperar_byte(); } while (c >= 0 && c != '-' && (c < '0' || c > '9'));
    if (c < 0) return 0;
    bool neg = c == '-';
    long v = neg ? 0 : c - '0';
    for (;;) {
        unsigned long t = millis();
        while (!available() && millis() - t < _timeout) delay(1);
        c = peek();
        if (c < '0' || c > '9') break;
        read();
        v = v * 10 + (c - '0');
    }
    return neg ? -v : v;
}

float Stream::parseFloat() { return (float)readStringUntil('\n').toFloat(); }

bool Stream::find(const char* t) {
    size_t k = 0, n = strlen(t);
    int c;
    while (k < n && (c = esperar_byte()) >= 0) k = (c == t[k]) ? k + 1 : (c == t[0] ? 1 : 0);
    return k == n;
}

// ── Serial ──────────────────────────────────────────────────────────────────
// Serial (0) = monitor serie (stdout). El RS-485 del tablero es Serial3 en el
// Controllino y Serial1 en el ESP32 PLC 14 (GPIO 16/17, con DE automatico; tambien
// RS485 de Industrial Shields). Serial2 es la HMI del tablero (tipo Stone, ver
// panel/hmi_stone.py). Lo demas no esta cableado a nada.
HardwareSerial Serial(0), Serial1(1), Serial2(2), Serial3(3), loraSerial(4);

#ifdef VINO_ESP32
static const int ID_BUS = 1;
#else
static const int ID_BUS = 3;
#endif

void HardwareSerial::begin(unsigned long baudios, uint32_t config) {
    if (id != ID_BUS) return;
    vino::bus_configurar(baudios, config);
#ifdef VINO_ESP32
    vino::bus_auto(true);
#endif
}

int HardwareSerial::available() {
    if (id == 2) { std::lock_guard<std::mutex> g(g_m_h); return (int)g_h_rx.size(); }
    if (id == 4) { std::lock_guard<std::mutex> g(g_m_h); return (int)g_l_rx.size(); }
    return id == ID_BUS ? vino::bus_disponibles() : 0;
}
int HardwareSerial::read() {
    if (id == 2) {
        std::lock_guard<std::mutex> g(g_m_h);
        if (g_h_rx.empty()) return -1;
        int c = g_h_rx.front();
        g_h_rx.pop_front();
        return c;
    }
    if (id == 4) {
        std::lock_guard<std::mutex> g(g_m_h);
        if (g_l_rx.empty()) return -1;
        int c = g_l_rx.front();
        g_l_rx.pop_front();
        return c;
    }
    return id == ID_BUS ? vino::bus_leer() : -1;
}
int HardwareSerial::peek() {
    if (id == 2) { std::lock_guard<std::mutex> g(g_m_h); return g_h_rx.empty() ? -1 : g_h_rx.front(); }
    if (id == 4) { std::lock_guard<std::mutex> g(g_m_h); return g_l_rx.empty() ? -1 : g_l_rx.front(); }
    return id == ID_BUS ? vino::bus_mirar() : -1;
}

size_t HardwareSerial::write(uint8_t c) {
    if (id == 0) { fputc(c, stdout); if (c == '\n') fflush(stdout); }
    else if (id == 2) { std::lock_guard<std::mutex> g(g_m_h); g_h_tx += (char)c; g_h_t = (long)micros(); }
    else if (id == 4) {
        // El RN2903 trabaja por lineas: cada fin de linea se entrega ya.
        std::lock_guard<std::mutex> g(g_m_h);
        g_l_tx += (char)c; g_l_t = (long)micros();
        if (c == '\n') lora_enviar_ya();
    }
    else if (id == ID_BUS) vino::bus_escribir(c);
    return 1;
}

void HardwareSerial::flush() {
    if (id == 0) fflush(stdout);
    else if (id == 2) { std::lock_guard<std::mutex> g(g_m_h); hmi_enviar_ya(); }
    else if (id == 4) { std::lock_guard<std::mutex> g(g_m_h); lora_enviar_ya(); }
    else if (id == ID_BUS) vino::bus_vaciar();
}

// ── Bus RS-485 ──────────────────────────────────────────────────────────────
namespace vino {

void bus_escribir(uint8_t c) {
    std::lock_guard<std::mutex> g(g_m_bus);
    if (!g_bus_auto && !g_bus_tx) {
        if (!g_aviso_dir) {
            g_aviso_dir = true;
            aviso("RS-485: escribes con el driver en RECEPCION; falta Controllino_RS485TxEnable()");
        }
        return;                       // como en el real: no sale nada
    }
    // El byte sale cuando termine el anterior (o ya, si la linea esta libre).
    long ahora = (long)micros();
    long ini = std::max(ahora, g_tx_fin);
    if (g_tx.empty()) g_tx_ini = ini;
    g_tx_fin = ini + (long)us_por_byte();
    g_tx += (char)c;
}

void bus_configurar(unsigned long baudios, uint32_t config) {
    std::lock_guard<std::mutex> g(g_m_bus);
    g_baud = baudios ? baudios : 9600;
    g_bits_dato = (int)((config >> 1) & 3) + 5;
    int par = (int)((config >> 4) & 3);       // 0 ninguna, 2 par, 3 impar
    int parada = (config & 0x08) ? 2 : 1;
    g_fmt = std::to_string(g_bits_dato) + (par == 2 ? "E" : par == 3 ? "O" : "N") + std::to_string(parada);
    g_bits_car = 1 + g_bits_dato + (par ? 1 : 0) + parada;
    enviar("u " + std::to_string(g_baud) + " " + g_fmt);
}

unsigned long bus_baudios() { std::lock_guard<std::mutex> g(g_m_bus); return g_baud; }
unsigned long bus_t35_us() { std::lock_guard<std::mutex> g(g_m_bus); return (unsigned long)us_t35(); }

void bus_vaciar() {
    // Serial.flush() de verdad: bloquea hasta que el ultimo bit ha salido del par.
    long falta;
    {
        std::lock_guard<std::mutex> g(g_m_bus);
        falta = g_tx_fin - (long)micros();
    }
    if (falta > 0) std::this_thread::sleep_for(std::chrono::microseconds(falta));
    std::lock_guard<std::mutex> g(g_m_bus);
    cerrar_trama_ya();
}

int bus_disponibles() { std::lock_guard<std::mutex> g(g_m_bus); return (int)g_rx.size(); }

int bus_leer() {
    std::lock_guard<std::mutex> g(g_m_bus);
    if (g_rx.empty()) return -1;
    int c = g_rx.front();
    g_rx.pop_front();
    return c;
}

int bus_mirar() { std::lock_guard<std::mutex> g(g_m_bus); return g_rx.empty() ? -1 : g_rx.front(); }

void bus_cerrar_trama() { std::lock_guard<std::mutex> g(g_m_bus); cerrar_trama_ya(); }

void bus_direccion(bool transmitir) {
    std::lock_guard<std::mutex> g(g_m_bus);
    if (!transmitir && !g_tx.empty()) {
        // Volver a recepcion con bytes aun saliendo (sin flush): el driver suelta el
        // par a mitad. Lo que no salio se pierde y el caracter cortado llega con sus
        // ultimos bits a 1 (la linea en reposo), como en el real.
        long ahora = (long)micros();
        if (ahora < g_tx_fin) {
            double byte_us = us_por_byte(), bit_us = byte_us / g_bits_car;
            long hecho = std::max(0L, ahora - g_tx_ini);
            size_t enteros = (size_t)(hecho / byte_us);
            int bits = (int)((hecho - enteros * byte_us) / bit_us);    // del caracter cortado
            std::string sale = g_tx.substr(0, std::min(enteros, g_tx.size()));
            if (enteros < g_tx.size() && bits >= 2) {
                int datos_ok = std::min(bits - 1, g_bits_dato);
                uint8_t c = (uint8_t)g_tx[enteros];
                sale += (char)(c | (uint8_t)(0xFF << datos_ok));
            }
            g_tx = sale;
            g_tx_fin = ahora;
            if (!g_aviso_dir) {
                g_aviso_dir = true;
                aviso("RS-485: RxEnable() antes de que salga el ultimo bit (falta Serial3.flush()): trama truncada");
            }
        }
        cerrar_trama_ya();
    }
    g_bus_tx = transmitir;
}

void bus_auto(bool automatico) { std::lock_guard<std::mutex> g(g_m_bus); g_bus_auto = automatico; }

void red_pedir(const std::string& linea) { enviar("n " + linea); }

void aviso(const char* fmt, ...) {
    char b[300];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(b, sizeof b, fmt, ap);
    va_end(ap);
    enviar(std::string("a ") + b);
}

}  // namespace vino

// ── Arranque ────────────────────────────────────────────────────────────────
int main() {
    signal(SIGPIPE, SIG_IGN);          // escribir a un socket cerrado no mata el programa
    setvbuf(stdout, nullptr, _IOLBF, 0);
    if (const char* e = getenv("VINO_FD_OUT")) g_fd_out = atoi(e);
    if (const char* e = getenv("VINO_FD_IN")) g_fd_in = atoi(e);
    if (g_fd_in >= 0) fcntl(g_fd_in, F_SETFL, fcntl(g_fd_in, F_GETFL) | O_NONBLOCK);
    std::thread(lector).detach();
    std::thread(hilo_timer1).detach();
    delay(50);                         // que lleguen las entradas iniciales
    setup();
    // Un loop() sin delay() no debe comerse un nucleo entero del PC, pero dormir en cada
    // vuelta daria un tiempo de ciclo de ~100 us que no es el de un PLC (guia L1: un lazo
    // vacio del ATmega2560 da unos pocos us). Se duerme 100 us cada 20 vueltas o cada
    // 2 ms: el lazo vacio promedia ~5 us y la CPU sigue casi libre.
    int vueltas = 0;
    auto t_dormir = std::chrono::steady_clock::now();
    for (;;) {
        loop();
        auto ahora = std::chrono::steady_clock::now();
        if (++vueltas >= 8 || ahora - t_dormir > std::chrono::milliseconds(1)) {
            // Dormir 300 us cada ~1 ms deja la CPU casi libre (antes 100 us cada 2 ms hacia
            // que un servidor Modbus TCP, cuyo loop() vuelve enseguida, girase al ~25 % de un
            // nucleo y robase cuadros al tablero 3D del navegador). El tiempo de respuesta
            // Modbus que mide U6 sube como mucho ~0.3 ms: Tc en reposo sigue por debajo de 1 ms.
            std::this_thread::sleep_for(std::chrono::microseconds(300));
            vueltas = 0;
            t_dormir = std::chrono::steady_clock::now();
        }
        // Saturacion del segmento (taller U6, Parte III): la pila de red del micro roba
        // CPU al lazo. El tiempo de ciclo crece con la carga hasta superar el plazo: a
        // nivel 100 el loop() tarda ~15 ms (el servidor Modbus TCP del alumno responde
        // tarde y el operador registra transacciones perdidas). El modelo de fabrica no
        // recibe "carga", asi que solo las practicas que corren un .ino lo notan.
        int carga = g_carga.load();
        if (carga > 0) {
            // Crece mas que lineal (la contencion se agrava cerca del 100 %): nivel 25 ->
            // ~3 ms, 50 -> ~7 ms, 100 -> ~120 ms. A plena carga el ciclo supera el periodo
            // de sondeo de 100 ms y el operador registra transacciones perdidas (su plazo).
            long us = (long)carga * 40L + (long)carga * carga * carga / 10L;
            std::this_thread::sleep_for(std::chrono::microseconds(us));
        }
    }
}
