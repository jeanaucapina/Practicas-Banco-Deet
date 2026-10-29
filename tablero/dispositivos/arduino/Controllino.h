// CONTROLLINO MEGA en el tablero virtual: los mismos nombres que la libreria
// oficial (CONTROLLINO_D0, CONTROLLINO_R0, CONTROLLINO_A0, ...), asi el .ino
// compila igual en el Arduino IDE con la placa "CONTROLLINO MEGA". Los numeros
// son los de este nucleo, no los del ATmega2560: usa siempre los nombres.
#pragma once
#include <Arduino.h>

#define CONTROLLINO_D0 100
#define CONTROLLINO_D1 101
#define CONTROLLINO_D2 102
#define CONTROLLINO_D3 103
#define CONTROLLINO_D4 104
#define CONTROLLINO_D5 105
#define CONTROLLINO_D6 106
#define CONTROLLINO_D7 107
#define CONTROLLINO_D8 108
#define CONTROLLINO_D9 109
#define CONTROLLINO_D10 110
#define CONTROLLINO_D11 111
#define CONTROLLINO_D12 112
#define CONTROLLINO_D13 113
#define CONTROLLINO_D14 114
#define CONTROLLINO_D15 115
#define CONTROLLINO_D16 116
#define CONTROLLINO_D17 117
#define CONTROLLINO_D18 118
#define CONTROLLINO_D19 119
#define CONTROLLINO_D20 120
#define CONTROLLINO_D21 121
#define CONTROLLINO_D22 122
#define CONTROLLINO_D23 123

#define CONTROLLINO_R0 130
#define CONTROLLINO_R1 131
#define CONTROLLINO_R2 132
#define CONTROLLINO_R3 133
#define CONTROLLINO_R4 134
#define CONTROLLINO_R5 135
#define CONTROLLINO_R6 136
#define CONTROLLINO_R7 137
#define CONTROLLINO_R8 138
#define CONTROLLINO_R9 139
#define CONTROLLINO_R10 140
#define CONTROLLINO_R11 141
#define CONTROLLINO_R12 142
#define CONTROLLINO_R13 143
#define CONTROLLINO_R14 144
#define CONTROLLINO_R15 145

#define CONTROLLINO_A0 160
#define CONTROLLINO_A1 161
#define CONTROLLINO_A2 162
#define CONTROLLINO_A3 163
#define CONTROLLINO_A4 164
#define CONTROLLINO_A5 165
#define CONTROLLINO_A6 166
#define CONTROLLINO_A7 167
#define CONTROLLINO_A8 168
#define CONTROLLINO_A9 169
#define CONTROLLINO_A10 170
#define CONTROLLINO_A11 171
#define CONTROLLINO_A12 172
#define CONTROLLINO_A13 173
#define CONTROLLINO_A14 174
#define CONTROLLINO_A15 175

// Pulsadores del panel e interrupciones
#define CONTROLLINO_I16 180
#define CONTROLLINO_I17 181
#define CONTROLLINO_I18 182
#define CONTROLLINO_IN0 183
#define CONTROLLINO_IN1 184

// Pines DE (habilita el emisor) y /RE (habilita el receptor) del transceptor,
// para ArduinoRS485: RS485Class RS485bus(Serial3, 14, CONTROLLINO_RS485_DE, CONTROLLINO_RS485_RE);
#define CONTROLLINO_RS485_TX 14
#define CONTROLLINO_RS485_DE 250
#define CONTROLLINO_RS485_RE 251

// RS-485 (Serial3, semiduplex): como en el real, hay que poner el driver en
// transmision antes de escribir y volver a recepcion para oir la respuesta.
//   Controllino_RS485TxEnable(); Serial3.write(...); Serial3.flush(); Controllino_RS485RxEnable();
inline char Controllino_RS485Init(long baudios = 9600) {
    Serial3.begin(baudios);
    vino::bus_auto(false);
    vino::bus_direccion(false);
    return 0;
}
inline void Controllino_RS485TxEnable() { vino::bus_direccion(true); }
// Sin Serial3.flush() antes, lo que aun no habia salido se trunca (guia L3, paso 8b).
inline void Controllino_RS485RxEnable() { vino::bus_direccion(false); }
