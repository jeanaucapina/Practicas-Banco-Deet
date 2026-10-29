// Libreria del banco para la HMI STONE STWC050WT-01 (guia L2): definiciones.
// La HMI esta en Serial2 del Controllino (conversor TTL <-> RS-232 ya montado),
// a 115 200 8N1. Formato de las tramas en panel/hmi_stone.py:
//   MCU -> HMI   ST<{"cmd_code":"set_text","type":"label","widget":"label2","text":"42"}>ET
//   HMI -> MCU   'S' 'T' '<'  CMD(2)  LEN(2)  nombre ':' valor(int32 BE)  '>' 'E' 'T'  CRC16(2)
#pragma once
#include <Arduino.h>

// Codigos de comando de las tramas que sube la HMI (HMI -> MCU)
#define STONE_CMD_BUTTON    0x1001
#define STONE_CMD_SWITCH    0x1010
#define STONE_CMD_SLIDER    0x1040
#define STONE_CMD_SPIN_BOX  0x1062
#define STONE_CMD_EDIT      0x1070
#define STONE_CMD_GET_VALUE 0x1080

#define STONE_HMI_BAUDIOS 115200
#define STONE_MAX_NOMBRE 24
#define STONE_MAX_TEXTO 64

// La ultima trama recibida de la HMI, ya interpretada.
struct Stone_HMI_Msg {
    uint16_t cmd;                       // STONE_CMD_...
    char widget[STONE_MAX_NOMBRE + 1];  // nombre del widget ("spin_box1")
    long value;                         // valor numerico (int32)
    char text[STONE_MAX_TEXTO + 1];     // texto (edit)
    bool nuevo;                         // true hasta que alguien lo lee
    unsigned long tramas_ok, tramas_crc_mal;
};

inline Stone_HMI_Msg hmi_msg;

inline void Stone_HMI_Init() {
    memset(&hmi_msg, 0, sizeof hmi_msg);
}

inline uint16_t Stone_HMI_CRC16(const uint8_t* b, size_t n) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < n; i++) {
        crc ^= b[i];
        for (uint8_t k = 0; k < 8; k++) crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : (crc >> 1);
    }
    return crc;
}

// Tipo de widget de cada comando ("spin_box", "slider"...), para HMI_get_value().
inline const char* Stone_HMI_Tipo(uint16_t cmd) {
    switch (cmd) {
        case STONE_CMD_BUTTON: return "button";
        case STONE_CMD_SWITCH: return "switch";
        case STONE_CMD_SLIDER: return "slider";
        case STONE_CMD_SPIN_BOX: return "spin_box";
        case STONE_CMD_EDIT: return "edit";
        case STONE_CMD_GET_VALUE: return "get_value";
        default: return "";
    }
}
