// Libreria del banco para la HMI STONE (guia L2): recepcion y envio.
//   Stone_HMI_Init();                         // en setup(), tras Serial2.begin(115200)
//   Uart_HMI_Data_Receive();                  // en loop(): vuelca la trama en hmi_msg
//   int v = HMI_get_value("spin_box", "spin_box1");   // -1 si no hay dato nuevo de ese widget
//   Stone_HMI_Set_Text("label2", "42");       // texto de un label
//   Stone_HMI_Set_Value("slider", "slider1", 50);
//   STONE_push_series("chart_view1", "line_series1", 37);   // un punto mas en la grafica
#pragma once
#include "Stone_HMI_Define.h"

namespace stone_priv {
inline uint8_t buf[160];
inline size_t n = 0;

inline void enviar(const String& json) {
    Serial2.print("ST<");
    Serial2.print(json);
    Serial2.print(">ET");
    Serial2.flush();
}
}  // namespace stone_priv

// Lee lo que haya en Serial2 y, si completa una trama valida (cabecera, cola y CRC),
// la deja en hmi_msg con nuevo = true. Las tramas con CRC malo se cuentan y se tiran.
inline void Uart_HMI_Data_Receive() {
    using namespace stone_priv;
    while (Serial2.available() > 0) {
        int c = Serial2.read();
        if (c < 0) break;
        if (n == 0 && c != 'S') continue;                    // resincroniza en la cabecera
        if (n == 1 && c != 'T') { n = 0; continue; }
        if (n == 2 && c != '<') { n = 0; continue; }
        if (n < sizeof buf) buf[n++] = (uint8_t)c;
        else { n = 0; continue; }
        if (n < 7) continue;
        size_t len = ((size_t)buf[5] << 8) | buf[6];
        if (len > sizeof buf - 12) { n = 0; continue; }
        if (n < 7 + len + 3 + 2) continue;
        size_t fin = 7 + len;
        if (buf[fin] != '>' || buf[fin + 1] != 'E' || buf[fin + 2] != 'T') { n = 0; continue; }
        uint16_t crc = Stone_HMI_CRC16(buf, fin + 3);
        if (buf[fin + 3] != (crc & 0xFF) || buf[fin + 4] != (crc >> 8)) {
            hmi_msg.tramas_crc_mal++;
            n = 0;
            continue;
        }
        hmi_msg.cmd = ((uint16_t)buf[3] << 8) | buf[4];
        size_t k = 0;
        while (k < len && buf[7 + k] != ':' && k < STONE_MAX_NOMBRE) { hmi_msg.widget[k] = buf[7 + k]; k++; }
        hmi_msg.widget[k] = 0;
        size_t d = 7 + k + 1, nd = len > k + 1 ? len - k - 1 : 0;
        if (hmi_msg.cmd == STONE_CMD_EDIT || (hmi_msg.cmd == STONE_CMD_GET_VALUE && nd != 4)) {
            size_t m = nd < STONE_MAX_TEXTO ? nd : STONE_MAX_TEXTO;
            memcpy(hmi_msg.text, buf + d, m);
            hmi_msg.text[m] = 0;
            hmi_msg.value = atol(hmi_msg.text);
        } else if (nd >= 4) {
            hmi_msg.value = (long)(((uint32_t)buf[d] << 24) | ((uint32_t)buf[d + 1] << 16) |
                                   ((uint32_t)buf[d + 2] << 8) | buf[d + 3]);
            hmi_msg.text[0] = 0;
        }
        hmi_msg.nuevo = true;
        hmi_msg.tramas_ok++;
        n = 0;
    }
}

// Valor del ultimo evento de ese widget, una sola vez; -1 si no hay dato nuevo suyo.
inline long HMI_get_value(const char* tipo, const char* widget) {
    if (!hmi_msg.nuevo || strcmp(hmi_msg.widget, widget) != 0) return -1;
    if (strcmp(Stone_HMI_Tipo(hmi_msg.cmd), tipo) != 0 && hmi_msg.cmd != STONE_CMD_GET_VALUE) return -1;
    hmi_msg.nuevo = false;
    return hmi_msg.value;
}

// Texto del ultimo evento de un edit (o NULL si no hay dato nuevo suyo).
inline const char* HMI_get_text(const char* widget) {
    if (!hmi_msg.nuevo || strcmp(hmi_msg.widget, widget) != 0) return NULL;
    hmi_msg.nuevo = false;
    return hmi_msg.text;
}

inline void Stone_HMI_Set_Text(const char* widget, const char* texto, const char* tipo = "label") {
    stone_priv::enviar(String("{\"cmd_code\":\"set_text\",\"type\":\"") + tipo + "\",\"widget\":\"" + widget +
                       "\",\"text\":\"" + texto + "\"}");
}

inline void Stone_HMI_Set_Value(const char* tipo, const char* widget, long valor) {
    stone_priv::enviar(String("{\"cmd_code\":\"set_value\",\"type\":\"") + tipo + "\",\"widget\":\"" + widget +
                       "\",\"value\":" + String(valor) + "}");
}

inline void Stone_HMI_Set_Float(const char* widget, float valor, const char* formato = "%.2f") {
    stone_priv::enviar(String("{\"cmd_code\":\"set_value\",\"type\":\"label\",\"widget\":\"") + widget +
                       "\",\"value\":" + String(valor, 3) + ",\"format\":\"" + formato + "\"}");
}

// En STONE la serie se direcciona por su nombre; el del chart se pasa por claridad.
inline void STONE_push_series(const char* chart, const char* serie, long valor) {
    (void)chart;
    stone_priv::enviar(String("{\"cmd_code\":\"set_value\",\"type\":\"line_series\",\"widget\":\"") + serie +
                       "\",\"mode\":\"push\",\"value\":" + String(valor) + "}");
}

inline void Stone_HMI_Open_Win(const char* pagina) {
    stone_priv::enviar(String("{\"cmd_code\":\"open_win\",\"widget\":\"") + pagina + "\"}");
}

inline void Stone_HMI_Get_Value(const char* tipo, const char* widget) {
    stone_priv::enviar(String("{\"cmd_code\":\"get_value\",\"type\":\"") + tipo + "\",\"widget\":\"" + widget + "\"}");
}
