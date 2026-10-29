// SPI vacio: lo incluyen los ejemplos de Ethernet; aqui no hace falta.
#pragma once
#include <Arduino.h>

class SPIClass {
public:
    void begin() {}
    void end() {}
    uint8_t transfer(uint8_t) { return 0; }
};

inline SPIClass SPI;
