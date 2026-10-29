// RS485 de Industrial Shields (ESP32 PLC): el driver cambia de direccion
// solo, asi que basta con RS485.begin(), write() y read().
//   RS485.begin(9600, HALFDUPLEX, SERIAL_8N1);   o   RS485.begin(19200, SERIAL_8N1);
// (el paquete de placas lo da sin #include: compilar.py lo incluye en el ESP32)
// beginTransmission()/endTransmission() (estilo ArduinoRS485) cierran trama.
#pragma once
#include <Arduino.h>

#define HALFDUPLEX 0
#define FULLDUPLEX 1

class RS485Class : public Stream {
public:
    void begin(unsigned long baudios, uint32_t duplex = HALFDUPLEX, uint32_t config = SERIAL_8N1) {
        if (duplex > FULLDUPLEX) config = duplex;      // RS485.begin(19200, SERIAL_8N1)
        vino::bus_configurar(baudios, config);
        vino::bus_auto(true);
    }
    void end() {}
    int available() override { return vino::bus_disponibles(); }
    int read() override { return vino::bus_leer(); }
    int peek() override { return vino::bus_mirar(); }
    size_t write(uint8_t c) override { vino::bus_escribir(c); return 1; }
    using Print::write;
    void flush() override { vino::bus_vaciar(); }
    void beginTransmission() {}
    void endTransmission() { flush(); }
    void receive() {}
    void noReceive() {}
};

inline RS485Class RS485;
