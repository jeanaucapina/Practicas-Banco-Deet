// ESP32 PLC 14 (Industrial Shields) en el tablero virtual. En el real los
// nombres los define el paquete de placas de Industrial Shields al elegir la
// placa en el IDE (no hay #include); aqui se incluyen solos al compilar.
// Son los de las etiquetas del tablero: I0_1..I0_8 entradas, Q0_0..Q0_3
// salidas, R0_1 el rele. I0_5..I0_8 aceptan tambien analogRead (0-4095).
#pragma once
#include <Arduino.h>

// Slot LORA (modulo RN2903 de Microchip): no cuelga de un UART del ESP32 sino de un
// PIC puente por I2C, que el paquete de placas expone como el Stream loraSerial.
// Con «LoRa (America)» el modulo es un RN2903 (US915). Ver rn2xx3.h.
extern HardwareSerial loraSerial;

#define Q0_0 200
#define Q0_1 201
#define Q0_2 202
#define Q0_3 203
#define R0_1 204

#define I0_1 211
#define I0_2 212
#define I0_3 213
#define I0_4 214
#define I0_5 215
#define I0_6 216
#define I0_7 217
#define I0_8 218

// Nombres de las guias del curso (L0, L7, L9): los dos reles y los selectores de
// tension de las salidas (SX_24v: LOW = 5 V, HIGH = 24 V). Los selectores son
// salidas que solo cambian el nivel de la bornera; en el banco virtual se guardan.
#define REL_A R0_1
#define REL_B 205
#define S0_24v 220
#define S1_24v 221
#define S2_24v 222
#define S3_24v 223
