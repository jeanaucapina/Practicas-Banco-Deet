// EEPROM en memoria (4 KiB). Se pierde al reiniciar el programa, no al
// apagar el tablero: en el virtual no hay "apagado" que la conserve.
#pragma once
#include <Arduino.h>

class EEPROMClass {
    uint8_t m[4096];
public:
    EEPROMClass() { memset(m, 0xff, sizeof m); }
    bool begin(size_t) { return true; }
    bool commit() { return true; }
    void end() {}
    uint8_t read(int i) { return m[i & 4095]; }
    void write(int i, uint8_t v) { m[i & 4095] = v; }
    void update(int i, uint8_t v) { m[i & 4095] = v; }
    uint8_t& operator[](int i) { return m[i & 4095]; }
    uint16_t length() { return sizeof m; }
    template <typename T> T& get(int i, T& t) { memcpy(&t, m + (i & 4095), sizeof(T)); return t; }
    template <typename T> const T& put(int i, const T& t) { memcpy(m + (i & 4095), &t, sizeof(T)); return t; }
};

inline EEPROMClass EEPROM;
