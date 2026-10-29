// WebServer del core ESP32 de Arduino (guia L9: servidor HTTP en el puerto 80 del PLC).
//   #include <WebServer.h>
//   WebServer server(80);
//   server.on("/", raiz); server.on("/estado", HTTP_GET, estado); server.onNotFound(nada);
//   server.begin();            ...     loop() { server.handleClient(); }
//   server.send(200, "application/json", "{...}"); server.arg("v"); server.hasArg("v");
// Atiende una peticion por llamada a handleClient(), como el original: si el loop()
// tarda (delay), el navegador espera. HTTP/1.0 y conexion cerrada tras cada respuesta.
#pragma once
#include <functional>
#include <utility>
#include <vector>

#include "WiFi.h"

enum HTTPMethod { HTTP_ANY, HTTP_GET, HTTP_HEAD, HTTP_POST, HTTP_PUT, HTTP_PATCH, HTTP_DELETE, HTTP_OPTIONS };

class WebServer {
public:
    typedef std::function<void(void)> THandlerFunction;

    explicit WebServer(int puerto = 80) : srv_((uint16_t)puerto) {}
    void begin() { srv_.begin(); }
    void begin(uint16_t p) { srv_.begin(p); }
    void close() {}
    void stop() {}

    void on(const String& ruta, THandlerFunction f) { on(ruta, HTTP_ANY, f); }
    void on(const String& ruta, HTTPMethod m, THandlerFunction f) { rutas_.push_back({ruta, m, f}); }
    void onNotFound(THandlerFunction f) { no_encontrada_ = f; }

    void handleClient() {
        ClienteTCP c = srv_.accept();
        if (!c) return;
        if (!leer(c)) { c.stop(); return; }
        cliente_ = c;
        respondido_ = false;
        cabeceras_extra_.clear();
        bool hecho = false;
        for (auto& r : rutas_) {
            if (r.ruta == uri_ && (r.metodo == HTTP_ANY || r.metodo == metodo_)) {
                r.f();
                hecho = true;
                break;
            }
        }
        if (!hecho) {
            if (no_encontrada_) no_encontrada_();
            else send(404, "text/plain", String("Not found: ") + uri_);
        }
        if (!respondido_) send(500, "text/plain", "sin respuesta");
        cliente_.flush();
        cliente_.stop();
    }

    void send(int codigo, const char* tipo = "text/plain", const String& contenido = String("")) {
        String r = String("HTTP/1.1 ") + String(codigo) + " " + texto_estado(codigo) + "\r\n";
        r += String("Content-Type: ") + tipo + "\r\n";
        r += String("Content-Length: ") + String((unsigned long)contenido.length()) + "\r\n";
        for (auto& h : cabeceras_extra_) r += h.first + ": " + h.second + "\r\n";
        r += "Connection: close\r\n\r\n";
        r += contenido;
        cliente_.write((const uint8_t*)r.c_str(), r.length());
        respondido_ = true;
    }
    void send(int codigo, const String& tipo, const String& contenido) { send(codigo, tipo.c_str(), contenido); }
    void send(int codigo, const char* tipo, const char* contenido) { send(codigo, tipo, String(contenido)); }
    void sendHeader(const String& nombre, const String& valor, bool = false) { cabeceras_extra_.push_back({nombre, valor}); }

    String uri() { return uri_; }
    HTTPMethod method() { return metodo_; }
    int args() { return (int)args_.size(); }
    String arg(int i) { return i >= 0 && i < (int)args_.size() ? args_[i].second : String(""); }
    String argName(int i) { return i >= 0 && i < (int)args_.size() ? args_[i].first : String(""); }
    String arg(const String& nombre) {
        if (nombre == "plain") return cuerpo_;
        for (auto& a : args_) if (a.first == nombre) return a.second;
        return String("");
    }
    bool hasArg(const String& nombre) {
        if (nombre == "plain") return cuerpo_.length() > 0;
        for (auto& a : args_) if (a.first == nombre) return true;
        return false;
    }
    WiFiClient client() { return WiFiClient(cliente_); }

private:
    struct Ruta { String ruta; HTTPMethod metodo; THandlerFunction f; };
    WiFiServer srv_;
    std::vector<Ruta> rutas_;
    THandlerFunction no_encontrada_;
    ClienteTCP cliente_;
    bool respondido_ = false;
    String uri_, cuerpo_;
    HTTPMethod metodo_ = HTTP_GET;
    std::vector<std::pair<String, String>> args_, cabeceras_extra_;

    static const char* texto_estado(int c) {
        switch (c) {
            case 200: return "OK";
            case 201: return "Created";
            case 204: return "No Content";
            case 301: return "Moved Permanently";
            case 302: return "Found";
            case 400: return "Bad Request";
            case 401: return "Unauthorized";
            case 403: return "Forbidden";
            case 404: return "Not Found";
            case 405: return "Method Not Allowed";
            default: return c < 400 ? "OK" : "Error";
        }
    }

    static String decodificar(const String& t) {
        String r;
        for (unsigned int i = 0; i < t.length(); i++) {
            char c = t[i];
            if (c == '+') r += ' ';
            else if (c == '%' && i + 2 < t.length()) {
                char h[3] = {t[i + 1], t[i + 2], 0};
                r += (char)strtol(h, nullptr, 16);
                i += 2;
            } else r += c;
        }
        return r;
    }

    void parsear_args(const String& q) {
        unsigned int i = 0;
        while (i < q.length()) {
            int fin = q.indexOf('&', i);
            String par = fin < 0 ? q.substring(i) : q.substring(i, fin);
            int eq = par.indexOf('=');
            if (par.length()) {
                if (eq < 0) args_.push_back({decodificar(par), String("")});
                else args_.push_back({decodificar(par.substring(0, eq)), decodificar(par.substring(eq + 1))});
            }
            if (fin < 0) break;
            i = fin + 1;
        }
    }

    // Lee la peticion completa (cabeceras y cuerpo) con un plazo de 1 s.
    bool leer(ClienteTCP& c) {
        String txt;
        unsigned long t0 = millis();
        int fin_cab = -1;
        long largo = 0;
        while (millis() - t0 < 1000) {
            while (c.available() > 0) {
                int b = c.read();
                if (b < 0) break;
                txt += (char)b;
            }
            if (fin_cab < 0) {
                fin_cab = txt.indexOf("\r\n\r\n");
                if (fin_cab >= 0) {
                    String cab = txt.substring(0, fin_cab);
                    String baja = cab;
                    baja.toLowerCase();
                    int k = baja.indexOf("content-length:");
                    if (k >= 0) largo = baja.substring(k + 15).toInt();
                }
            }
            if (fin_cab >= 0 && (long)txt.length() >= fin_cab + 4 + largo) break;
            if (!c.connected() && c.available() == 0) break;
            delay(1);
        }
        if (fin_cab < 0) return false;
        int sp1 = txt.indexOf(' '), sp2 = txt.indexOf(' ', sp1 + 1);
        if (sp1 < 0 || sp2 < 0) return false;
        String m = txt.substring(0, sp1), ruta = txt.substring(sp1 + 1, sp2);
        metodo_ = m == "POST" ? HTTP_POST : m == "PUT" ? HTTP_PUT : m == "DELETE" ? HTTP_DELETE
                : m == "PATCH" ? HTTP_PATCH : m == "HEAD" ? HTTP_HEAD : m == "OPTIONS" ? HTTP_OPTIONS : HTTP_GET;
        args_.clear();
        int q = ruta.indexOf('?');
        uri_ = q < 0 ? ruta : ruta.substring(0, q);
        if (q >= 0) parsear_args(ruta.substring(q + 1));
        cuerpo_ = txt.substring(fin_cab + 4);
        String baja = txt.substring(0, fin_cab);
        baja.toLowerCase();
        if (baja.indexOf("application/x-www-form-urlencoded") >= 0) parsear_args(cuerpo_);
        return true;
    }
};
