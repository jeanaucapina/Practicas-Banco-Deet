// Nucleo Arduino virtual del tablero (ver LEEME.md en esta carpeta).
//
// El .ino del alumno se compila con g++ dentro del contenedor del equipo y
// corre como un proceso Linux: los pines viajan a las gafas por una tuberia
// con programa.py, Serial es el "monitor serie" y Ethernet/WiFi son sockets
// de verdad en las redes Docker del tablero. Solo la API de Arduino: nada de
// registros del micro (PORTB, TCCR1A...), que aqui no existen.
#pragma once

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdarg.h>
#include <math.h>
#include <string>
#include <functional>
#include <type_traits>

typedef uint8_t byte;
typedef bool boolean;
typedef uint16_t word;

#define HIGH 0x1
#define LOW 0x0
#define INPUT 0x0
#define OUTPUT 0x1
#define INPUT_PULLUP 0x2
#define CHANGE 1
#define FALLING 2
#define RISING 3
#define LSBFIRST 0
#define MSBFIRST 1
#define DEC 10
#define HEX 16
#define OCT 8
#define BIN 2
#define PI 3.1415926535897932384626433832795
#define HALF_PI 1.5707963267948966192313216916398
#define TWO_PI 6.283185307179586476925286766559
#define DEG_TO_RAD 0.017453292519943295769236907684886
#define RAD_TO_DEG 57.295779513082320876798154814105
#define LED_BUILTIN 13
// Codificacion de AVR (bits 1-2: datos-5, 4-5: paridad, 3: dos de parada)
#define SERIAL_7N1 0x04
#define SERIAL_8N1 0x06
#define SERIAL_7N2 0x0C
#define SERIAL_8N2 0x0E
#define SERIAL_7E1 0x24
#define SERIAL_8E1 0x26
#define SERIAL_7E2 0x2C
#define SERIAL_8E2 0x2E
#define SERIAL_7O1 0x34
#define SERIAL_8O1 0x36
#define SERIAL_7O2 0x3C
#define SERIAL_8O2 0x3E

#define F(s) (s)
#define PSTR(s) (s)
#define PROGMEM
#define pgm_read_byte(p) (*(const uint8_t*)(p))
#define pgm_read_word(p) (*(const uint16_t*)(p))
#define lowByte(w) ((uint8_t)((w) & 0xff))
#define highByte(w) ((uint8_t)((w) >> 8))
#define bitRead(v, b) (((v) >> (b)) & 0x01)
#define bitSet(v, b) ((v) |= (1UL << (b)))
#define bitClear(v, b) ((v) &= ~(1UL << (b)))
#define bitWrite(v, b, x) ((x) ? bitSet(v, b) : bitClear(v, b))
#define bit(b) (1UL << (b))
#define constrain(x, a, b) ((x) < (a) ? (a) : ((x) > (b) ? (b) : (x)))
#define sq(x) ((x) * (x))
#define radians(d) ((d) * DEG_TO_RAD)
#define degrees(r) ((r) * RAD_TO_DEG)
#define digitalPinToInterrupt(p) (p)

// min/max de Arduino aceptan tipos mezclados (min(x, 10) con x long).
template <class A, class B> inline auto min(A a, B b) -> decltype(a < b ? a : b) { return b < a ? b : a; }
template <class A, class B> inline auto max(A a, B b) -> decltype(a < b ? a : b) { return a < b ? b : a; }

void setup();
void loop();

void pinMode(uint8_t pin, uint8_t modo);
void digitalWrite(uint8_t pin, uint8_t valor);
int digitalRead(uint8_t pin);
int analogRead(uint8_t pin);
void analogWrite(uint8_t pin, int valor);
void analogReadResolution(int bits);
unsigned long millis();
unsigned long micros();
void delay(unsigned long ms);
void delayMicroseconds(unsigned int us);
void yield();
long random(long max);
long random(long min, long max);
void randomSeed(unsigned long semilla);
long map(long x, long in_min, long in_max, long out_min, long out_max);
void attachInterrupt(uint8_t pin, void (*isr)(), int modo);
void detachInterrupt(uint8_t pin);
// Las ISR (attachInterrupt, Timer1) corren en otro hilo del nucleo: noInterrupts()
// las retiene hasta interrupts(), como el bit I del AVR.
void interrupts();
void noInterrupts();
#define cli() noInterrupts()
#define sei() interrupts()

// ── Timer1 del ATmega2560 (Controllino): registros y vectores (guia L2) ──────
// Modo CTC (WGM12) con OCR1A y prescalador (CS12..CS10) llama a TIMER1_COMPA_vect;
// modo normal con TOIE1, a TIMER1_OVF_vect. Reloj de 16 MHz.
#define ISR(vector) extern "C" void vector()
extern "C" void TIMER1_COMPA_vect() __attribute__((weak));
extern "C" void TIMER1_COMPB_vect() __attribute__((weak));
extern "C" void TIMER1_OVF_vect() __attribute__((weak));
inline volatile uint8_t TCCR1A = 0, TCCR1B = 0, TCCR1C = 0, TIMSK1 = 0, TIFR1 = 0;
inline volatile uint16_t TCNT1 = 0, OCR1A = 0, OCR1B = 0, ICR1 = 0;
#define WGM10 0
#define WGM11 1
#define WGM12 3
#define WGM13 4
#define CS10 0
#define CS11 1
#define CS12 2
#define TOIE1 0
#define OCIE1A 1
#define OCIE1B 2
#define COM1A0 6
#define COM1A1 7
#define F_CPU 16000000UL
#define _BV(b) (1 << (b))

// Conversiones de numeros a texto de avr-libc
inline char* ltoa(long v, char* buf, int base) {
    char t[34]; int i = 0; bool neg = v < 0 && base == 10;
    unsigned long u = neg ? (unsigned long)(-v) : (unsigned long)v;
    do { int d = (int)(u % base); t[i++] = (char)(d < 10 ? '0' + d : 'a' + d - 10); u /= base; } while (u && i < 33);
    int k = 0;
    if (neg) buf[k++] = '-';
    while (i) buf[k++] = t[--i];
    buf[k] = 0;
    return buf;
}
inline char* itoa(int v, char* buf, int base) { return ltoa(v, buf, base); }
inline char* utoa(unsigned int v, char* buf, int base) { return ltoa((long)v, buf, base); }
inline char* ultoa(unsigned long v, char* buf, int base) { return ltoa((long)v, buf, base); }
inline char* dtostrf(double v, signed char ancho, unsigned char dec, char* buf) {
    snprintf(buf, 40, "%*.*f", (int)ancho, (int)dec, v);
    return buf;
}

class String;
class IPAddress;

class Print {
public:
    virtual ~Print() {}
    virtual size_t write(uint8_t c) = 0;
    virtual size_t write(const uint8_t* b, size_t n);
    size_t write(const char* s) { return s ? write((const uint8_t*)s, strlen(s)) : 0; }
    size_t write(const char* b, size_t n) { return write((const uint8_t*)b, n); }
    virtual void flush() {}

    size_t print(const char* s) { return write(s); }
    size_t print(char c) { return write((uint8_t)c); }
    size_t print(const String& s);
    size_t print(const IPAddress& ip);
    size_t print(unsigned char n, int base = DEC) { return print((unsigned long)n, base); }
    size_t print(int n, int base = DEC) { return print((long)n, base); }
    size_t print(unsigned int n, int base = DEC) { return print((unsigned long)n, base); }
    size_t print(long n, int base = DEC);
    size_t print(unsigned long n, int base = DEC);
    size_t print(long long n, int base = DEC) { return print((long)n, base); }
    size_t print(unsigned long long n, int base = DEC) { return print((unsigned long)n, base); }
    size_t print(double n, int decimales = 2);
    size_t println() { return write("\r\n"); }
    template <typename T> size_t println(const T& v) { size_t n = print(v); return n + println(); }
    template <typename T> size_t println(const T& v, int b) { size_t n = print(v, b); return n + println(); }
    size_t printf(const char* fmt, ...) __attribute__((format(printf, 2, 3)));
};

class String {
    std::string s;
public:
    String(const char* c = "") : s(c ? c : "") {}
    explicit String(const std::string& x) : s(x) {}
    String(const String& o) = default;
    String& operator=(const String& o) = default;
    String(char c) : s(1, c) {}
    String(unsigned char v, int base = DEC) : String((unsigned long)v, base) {}
    String(int v, int base = DEC) : String((long)v, base) {}
    String(unsigned int v, int base = DEC) : String((unsigned long)v, base) {}
    String(long v, int base = DEC);
    String(unsigned long v, int base = DEC);
    String(float v, int decimales = 2) : String((double)v, decimales) {}
    String(double v, int decimales = 2);

    unsigned int length() const { return s.size(); }
    bool isEmpty() const { return s.empty(); }
    const char* c_str() const { return s.c_str(); }
    const std::string& std() const { return s; }
    char operator[](unsigned int i) const { return i < s.size() ? s[i] : 0; }
    char& operator[](unsigned int i) { return s[i]; }
    char charAt(unsigned int i) const { return (*this)[i]; }
    void setCharAt(unsigned int i, char c) { if (i < s.size()) s[i] = c; }

    String& operator+=(const String& o) { s += o.s; return *this; }
    String& operator+=(const char* c) { if (c) s += c; return *this; }
    String& operator+=(char c) { s += c; return *this; }
    template <typename T, typename = typename std::enable_if<std::is_arithmetic<T>::value>::type>
    String& operator+=(T v) { s += String(v).s; return *this; }
    template <typename T> bool concat(T v) { *this += v; return true; }

    bool operator==(const String& o) const { return s == o.s; }
    bool operator==(const char* c) const { return s == (c ? c : ""); }
    bool operator!=(const String& o) const { return s != o.s; }
    bool operator!=(const char* c) const { return !(*this == c); }
    bool operator<(const String& o) const { return s < o.s; }
    bool equals(const String& o) const { return s == o.s; }
    bool equalsIgnoreCase(const String& o) const;
    int compareTo(const String& o) const { return s.compare(o.s); }

    int indexOf(char c, unsigned int desde = 0) const;
    int indexOf(const String& t, unsigned int desde = 0) const;
    int lastIndexOf(char c) const;
    int lastIndexOf(const String& t) const;
    String substring(unsigned int desde) const;
    String substring(unsigned int desde, unsigned int hasta) const;
    bool startsWith(const String& t) const { return s.compare(0, t.s.size(), t.s) == 0; }
    bool endsWith(const String& t) const;
    long toInt() const { return atol(s.c_str()); }
    float toFloat() const { return (float)atof(s.c_str()); }
    double toDouble() const { return atof(s.c_str()); }
    void trim();
    void toUpperCase();
    void toLowerCase();
    void replace(const String& a, const String& b);
    void replace(char a, char b);
    void remove(unsigned int i, unsigned int n = (unsigned int)-1);
    void reserve(unsigned int n) { s.reserve(n); }
    void getBytes(byte* b, unsigned int n) const;
    void toCharArray(char* b, unsigned int n) const { getBytes((byte*)b, n); }
};

String operator+(const String& a, const String& b);
String operator+(const String& a, const char* b);
String operator+(const char* a, const String& b);
String operator+(const String& a, char b);
template <typename T, typename = typename std::enable_if<std::is_arithmetic<T>::value>::type>
String operator+(const String& a, T b) { return a + String(b); }

class IPAddress {
    uint8_t b[4] = {0, 0, 0, 0};
public:
    IPAddress() {}
    IPAddress(uint8_t a, uint8_t c, uint8_t d, uint8_t e) : b{a, c, d, e} {}
    explicit IPAddress(uint32_t ip) { memcpy(b, &ip, 4); }
    uint8_t operator[](int i) const { return b[i]; }
    uint8_t& operator[](int i) { return b[i]; }
    bool operator==(const IPAddress& o) const { return memcmp(b, o.b, 4) == 0; }
    bool operator!=(const IPAddress& o) const { return !(*this == o); }
    bool fromString(const char* t);
    bool fromString(const String& t) { return fromString(t.c_str()); }
    String toString() const;
};
#define INADDR_NONE IPAddress(0, 0, 0, 0)

class Stream : public Print {
protected:
    unsigned long _timeout = 1000;
    int esperar_byte();
public:
    virtual int available() = 0;
    virtual int read() = 0;
    virtual int peek() = 0;
    void setTimeout(unsigned long ms) { _timeout = ms; }
    size_t readBytes(char* b, size_t n);
    size_t readBytes(uint8_t* b, size_t n) { return readBytes((char*)b, n); }
    size_t readBytesUntil(char fin, char* b, size_t n);
    String readString();
    String readStringUntil(char fin);
    long parseInt();
    float parseFloat();
    bool find(const char* t);
};

class HardwareSerial : public Stream {
    int id;
public:
    explicit HardwareSerial(int n) : id(n) {}
    void begin(unsigned long baudios, uint32_t config = SERIAL_8N1);
    void begin(unsigned long baudios, uint32_t config, int8_t rx, int8_t tx) { begin(baudios, config); (void)rx; (void)tx; }
    void end() {}
    int available() override;
    int read() override;
    int peek() override;
    size_t write(uint8_t c) override;
    using Print::write;
    void flush() override;
    operator bool() const { return true; }
};
extern HardwareSerial Serial, Serial1, Serial2, Serial3;

// Interno del nucleo (nucleo.cpp): el bus RS-485 del tablero.
namespace vino {
void bus_escribir(uint8_t c);
int bus_disponibles();
int bus_leer();
int bus_mirar();
void bus_cerrar_trama();
void bus_direccion(bool transmitir);   // semiduplex: false = recibir
void bus_auto(bool automatico);        // la direccion la lleva el driver
void bus_configurar(unsigned long baudios, uint32_t config);   // la UART del bus
void bus_vaciar();                     // flush(): espera a que salga el ultimo bit
unsigned long bus_baudios();           // los de la UART del bus (para el silencio t3,5)
unsigned long bus_t35_us();
void aviso(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
}
