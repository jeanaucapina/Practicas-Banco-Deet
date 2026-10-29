// I2C sin dispositivos: el tablero virtual no tiene nada en el bus I2C, asi
// que toda transmision acaba en NACK (endTransmission() = 2), como un bus vacio.
#pragma once
#include <Arduino.h>

class TwoWire : public Stream {
public:
    void begin() {}
    void begin(int sda, int scl) { (void)sda; (void)scl; }
    void setClock(uint32_t) {}
    void beginTransmission(uint8_t) {}
    uint8_t endTransmission(bool = true) { return 2; }
    uint8_t requestFrom(uint8_t, uint8_t, bool = true) { return 0; }
    size_t write(uint8_t) override { return 1; }
    using Print::write;
    int available() override { return 0; }
    int read() override { return -1; }
    int peek() override { return -1; }
};

inline TwoWire Wire;
