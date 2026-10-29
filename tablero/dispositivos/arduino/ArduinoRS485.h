// ArduinoRS485 (libreria oficial de Arduino, 1.0.x) sobre el RS-485 del tablero
// (guia L6, esclavo en el Controllino):
//   #include <Controllino.h>          // primero: declara los pines DE y RE
//   #include <ArduinoRS485.h>
//   RS485Class RS485bus(Serial3, 14, CONTROLLINO_RS485_DE, CONTROLLINO_RS485_RE);
// beginTransmission() pone el driver en transmision; endTransmission() espera a que
// salga el ultimo bit (flush) y lo devuelve a recepcion, como la libreria real.
// No se mezcla con <RS485.h> de Industrial Shields (ESP32): las dos definen RS485Class.
#pragma once
#include <Arduino.h>

class RS485Class : public Stream {
public:
    RS485Class(HardwareSerial& serie, int pin_tx, int pin_de, int pin_re)
        : serie_(serie), tx_(pin_tx), de_(pin_de), re_(pin_re) {}
    void begin(unsigned long baudios) { begin(baudios, SERIAL_8N1); }
    void begin(unsigned long baudios, uint16_t config) {
        serie_.begin(baudios, config);
        vino::bus_auto(false);
        vino::bus_direccion(false);
        (void)tx_; (void)de_; (void)re_;
    }
    void end() {}
    int available() override { return serie_.available(); }
    int read() override { return serie_.read(); }
    int peek() override { return serie_.peek(); }
    size_t write(uint8_t c) override { return serie_.write(c); }
    using Print::write;
    void flush() override { serie_.flush(); }
    void beginTransmission() { vino::bus_direccion(true); }
    void endTransmission() { serie_.flush(); vino::bus_direccion(false); }
    void receive() {}
    void noReceive() {}
    void sendBreak(unsigned int) {}
    void sendBreakMicroseconds(unsigned int) {}
    void setPins(int pin_tx, int pin_de, int pin_re) { tx_ = pin_tx; de_ = pin_de; re_ = pin_re; }
    void setDelays(int, int) {}
    HardwareSerial& serie() { return serie_; }

private:
    HardwareSerial& serie_;
    int tx_, de_, re_;
};

// La instancia por defecto de la libreria, sobre la UART del bus del tablero.
#ifdef VINO_ESP32
inline RS485Class RS485(Serial1, 17, -1, -1);
#else
inline RS485Class RS485(Serial3, 14, 250, 251);
#endif
