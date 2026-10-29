// rn2xx3 (RN2483-Arduino-Library de jpmeijers) para el RN2903 del slot LORA del
// ESP32 PLC 14. Igual que la real: manda los comandos de texto del modulo
// ("sys get ver", "mac join otaa", "mac tx uncnf 1 <hex>"...) por el Stream que se
// le pasa y lee sus respuestas. El modulo lo emula dispositivos/rn2903.py, con la
// MAC LoRaWAN 1.0.x de verdad (AES-128, MIC, FCnt) y la radio US915.
//
//   rn2xx3 lora(loraSerial);
//   lora.autobaud();  lora.setFrequencyPlan(TTN_US);  lora.initOTAA(JOIN_EUI, APP_KEY);
//   lora.txBytes(trama, 9);   lora.setDR(3);   lora.sendRawCommand("mac pause");
//
// Una diferencia con la version publicada: initOTAA()/initABP() empiezan con
// "mac reset", que en el RN2903 vuelve a abrir los 72 canales; aqui la libreria
// recuerda el plan de setFrequencyPlan() y lo repone tras el reset, como en el
// banco del curso (guia L10, Listado L10.1: el plan se fija ANTES de initOTAA).
#pragma once
#include <Arduino.h>

enum RN2xx3_t { RN_NA = 0, RN2903 = 2903, RN2483 = 2483 };
enum FREQ_PLAN { SINGLE_CHANNEL_EU, TTN_EU, TTN_US, DEFAULT_EU };
enum TX_RETURN_TYPE { TX_FAIL = 0, TX_SUCCESS = 1, TX_WITH_RX = 2 };

class rn2xx3 {
public:
    explicit rn2xx3(Stream& serial) : _serial(serial) { _serial.setTimeout(2000); }

    // Rompe el silencio del modulo y le deja medir los baudios (0x00 + 0x55).
    void autobaud() {
        String respuesta = "";
        for (uint8_t i = 0; i < 10 && respuesta == ""; i++) {
            delay(1000);
            _serial.write((uint8_t)0x00);
            _serial.write((uint8_t)0x55);
            _serial.println();
            _serial.println("sys get ver");
            respuesta = _serial.readStringUntil('\n');
        }
    }

    String hweui() { return sendRawCommand("sys get hweui"); }
    String appeui() { return sendRawCommand("mac get appeui"); }
    String appkey() { return _appskey; }      // el modulo no deja leerla
    String deveui() { return sendRawCommand("mac get deveui"); }
    String sysver() {
        String ver = sendRawCommand("sys get ver");
        ver.trim();
        return ver;
    }
    RN2xx3_t moduleType() { return _moduleType; }

    bool setFrequencyPlan(FREQ_PLAN fp) {
        configureModuleType();
        _plan = fp;
        _plan_fijado = true;
        return aplicarPlan();
    }

    bool init() {
        if (_appskey == "0") return false;
        return _otaa ? initOTAA(_appeui, _appskey, _deveui) : initABP(_devAddr, _appskey, _nwkskey);
    }

    bool initOTAA(String AppEUI = "", String AppKey = "", String DevEUI = "") {
        _otaa = true;
        _nwkskey = "0";
        while (_serial.available()) _serial.read();
        configureModuleType();
        if (_moduleType == RN2903) sendRawCommand("mac reset");
        else if (_moduleType == RN2483) sendRawCommand("mac reset 868");
        else return false;
        if (_plan_fijado) aplicarPlan();
        if (DevEUI.length() == 16) _deveui = DevEUI;
        else {
            String addr = sendRawCommand("sys get hweui");
            if (addr.length() == 16) _deveui = addr;
        }
        sendRawCommand("mac set deveui " + _deveui);
        if (AppEUI.length() == 16) { _appeui = AppEUI; sendRawCommand("mac set appeui " + _appeui); }
        if (AppKey.length() == 32) { _appskey = AppKey; sendRawCommand("mac set appkey " + _appskey); }
        sendRawCommand(_moduleType == RN2903 ? "mac set pwridx 5" : "mac set pwridx 1");
        sendRawCommand("mac set adr off");
        sendRawCommand("mac set ar off");
        _serial.setTimeout(30000);
        sendRawCommand("mac save");
        bool unido = false;
        for (int i = 0; i < 2 && !unido; i++) {
            sendRawCommand("mac join otaa");
            String r = _serial.readStringUntil('\n');      // "accepted" o "denied"
            if (r.startsWith("accepted")) { unido = true; delay(1000); }
            else delay(1000);
        }
        _serial.setTimeout(2000);
        return unido;
    }

    bool initOTAA(const uint8_t* AppEUI, const uint8_t* AppKey, const uint8_t* DevEUI) {
        return initOTAA(aHex(AppEUI, 8), aHex(AppKey, 16), DevEUI ? aHex(DevEUI, 8) : String(""));
    }

    bool initABP(String addr, String AppSKey, String NwkSKey) {
        _otaa = false;
        _devAddr = addr;
        _appskey = AppSKey;
        _nwkskey = NwkSKey;
        while (_serial.available()) _serial.read();
        configureModuleType();
        if (_moduleType == RN2903) sendRawCommand("mac reset");
        else if (_moduleType == RN2483) sendRawCommand("mac reset 868");
        else return false;
        if (_plan_fijado) aplicarPlan();
        sendRawCommand("mac set nwkskey " + _nwkskey);
        sendRawCommand("mac set appskey " + _appskey);
        sendRawCommand("mac set devaddr " + _devAddr);
        sendRawCommand("mac set adr off");
        sendRawCommand("mac set ar off");
        if (_moduleType == RN2903) {
            sendRawCommand("mac set pwridx 5");
            sendRawCommand("mac set rx2 8 923300000");
        } else {
            sendRawCommand("mac set pwridx 1");
        }
        _serial.setTimeout(60000);
        sendRawCommand("mac save");
        sendRawCommand("mac join abp");
        String r = _serial.readStringUntil('\n');
        _serial.setTimeout(2000);
        delay(1000);
        return r.startsWith("accepted");
    }

    TX_RETURN_TYPE tx(String data) { return txUncnf(data); }
    TX_RETURN_TYPE txUncnf(String data) { return txCommand("mac tx uncnf 1 ", data, true); }
    TX_RETURN_TYPE txCnf(String data) { return txCommand("mac tx cnf 1 ", data, true); }
    TX_RETURN_TYPE txBytes(const uint8_t* data, uint8_t size) {
        return txCommand("mac tx uncnf 1 ", aHex(data, size), false);
    }
    TX_RETURN_TYPE txBytes(const char* data, uint8_t size) { return txBytes((const uint8_t*)data, size); }

    TX_RETURN_TYPE txCommand(String command, String data, bool shouldEncode) {
        uint8_t ocupado = 0, intentos = 0;
        while (_serial.available()) _serial.read();
        while (true) {
            if (++intentos > 10) return TX_FAIL;
            _serial.print(command);
            if (shouldEncode) sendEncoded(data);
            else _serial.print(data);
            _serial.println();
            String r = _serial.readStringUntil('\n');
            if (r.startsWith("ok")) {
                _serial.setTimeout(30000);
                r = _serial.readStringUntil('\n');
                _serial.setTimeout(2000);
                if (r.startsWith("mac_tx_ok")) return TX_SUCCESS;
                if (r.startsWith("mac_rx")) {        // mac_rx <puerto> <hex>
                    _rxMessenge = r.substring(r.indexOf(' ', 7) + 1);
                    _rxMessenge.trim();
                    return TX_WITH_RX;
                }
                if (r.startsWith("invalid_data_len")) return TX_FAIL;
                if (r.startsWith("radio_tx_ok")) return TX_SUCCESS;
                init();                              // mac_err, radio_err...: se vuelve a unir
            }
            else if (r.startsWith("invalid_param")) return TX_FAIL;
            else if (r.startsWith("invalid_data_len")) return TX_FAIL;
            else if (r.startsWith("no_free_ch")) delay(1000);
            else if (r.startsWith("busy")) { if (++ocupado >= 10) init(); else delay(1000); }
            else init();                             // not_joined, silent, mac_paused...
        }
    }

    void sendEncoded(String input) {
        char tmp[3];
        for (unsigned i = 0; i < input.length(); i++) {
            snprintf(tmp, sizeof(tmp), "%02X", (unsigned char)input.charAt(i));
            _serial.print(tmp);
        }
    }
    String base16encode(String input) {
        String out = "";
        char tmp[3];
        for (unsigned i = 0; i < input.length(); i++) {
            snprintf(tmp, sizeof(tmp), "%02X", (unsigned char)input.charAt(i));
            out += tmp;
        }
        return out;
    }
    String base16decode(String input) {
        String out = "";
        for (unsigned i = 0; i + 1 < input.length(); i += 2)
            out += (char)strtol(input.substring(i, i + 2).c_str(), nullptr, 16);
        return out;
    }
    String getRx() { return _rxMessenge; }
    int getSNR() { return sendRawCommand("radio get snr").toInt(); }
    int getRSSI() { return sendRawCommand("radio get rssi").toInt(); }
    bool setDR(int dr) {
        if (dr < 0 || dr > 15) return false;
        return sendRawCommand("mac set dr " + String(dr)) == "ok";
    }
    void sleep(long msec) { _serial.print("sys sleep "); _serial.println(msec); }

    String sendRawCommand(String command) {
        delay(20);
        while (_serial.available()) _serial.read();
        _serial.println(command);
        String ret = _serial.readStringUntil('\n');
        ret.trim();
        return ret;
    }

private:
    Stream& _serial;
    RN2xx3_t _moduleType = RN_NA;
    bool _otaa = true;
    FREQ_PLAN _plan = DEFAULT_EU;
    bool _plan_fijado = false;
    String _deveui = "0011223344556677";
    String _appeui = "0";
    String _nwkskey = "0";
    String _appskey = "0";
    String _devAddr = "03FFBEEF";
    String _rxMessenge = "";

    void configureModuleType() {
        if (_moduleType != RN_NA) return;
        String ver = sysver();
        String modelo = ver.substring(0, 6);
        if (modelo == "RN2903") _moduleType = RN2903;
        else if (modelo == "RN2483") _moduleType = RN2483;
    }

    bool aplicarPlan() {
        if (_plan == TTN_US) {
            if (_moduleType != RN2903) return false;
            // Sub-banda 2 (canales 8-15 de 125 kHz); los de 500 kHz (64-71) se dejan.
            for (int ch = 0; ch < 64; ch++)
                sendRawCommand("mac set ch status " + String(ch) + ((ch >= 8 && ch < 16) ? " on" : " off"));
            return true;
        }
        return _moduleType == RN2483;      // los planes EU son del RN2483
    }

    static String aHex(const uint8_t* d, size_t n) {
        String out = "";
        char tmp[3];
        for (size_t i = 0; i < n; i++) { snprintf(tmp, sizeof(tmp), "%02X", d[i]); out += tmp; }
        return out;
    }
};
