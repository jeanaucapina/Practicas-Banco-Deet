// RTClib (Adafruit) con un DS3231 en el bus I2C del ESP32 PLC 14 (kit LoRa de la
// guia L10). El reloj del modulo es el del anfitrion en UTC, como un DS3231 puesto
// en hora UTC; adjust() lo desplaza y lostPower() dice false (pila del modulo bien).
//   RTC_DS3231 rtc;  rtc.begin();  uint32_t ts = rtc.now().unixtime();
#pragma once
#include <Arduino.h>
#include <Wire.h>
#include <ctime>

class TimeSpan {
public:
    TimeSpan(int32_t s = 0) : _s(s) {}
    TimeSpan(int16_t d, int8_t h, int8_t m, int8_t s) : _s((int32_t)d * 86400L + h * 3600L + m * 60L + s) {}
    int16_t days() const { return _s / 86400L; }
    int8_t hours() const { return _s / 3600 % 24; }
    int8_t minutes() const { return _s / 60 % 60; }
    int8_t seconds() const { return _s % 60; }
    int32_t totalseconds() const { return _s; }
private:
    int32_t _s;
};

class DateTime {
public:
    DateTime(uint32_t t = 946684800UL) : _t(t) { partir(); }
    DateTime(uint16_t y, uint8_t mo, uint8_t d, uint8_t h = 0, uint8_t mi = 0, uint8_t s = 0) {
        struct tm x = {};
        x.tm_year = y - 1900; x.tm_mon = mo - 1; x.tm_mday = d;
        x.tm_hour = h; x.tm_min = mi; x.tm_sec = s;
        _t = (uint32_t)timegm(&x);
        partir();
    }
    // DateTime(F(__DATE__), F(__TIME__)): "Oct 21 2026", "12:34:56"
    DateTime(const char* fecha, const char* hora) {
        static const char* meses = "JanFebMarAprMayJunJulAugSepOctNovDec";
        char m[4] = {fecha[0], fecha[1], fecha[2], 0};
        const char* p = strstr(meses, m);
        int mo = p ? (int)(p - meses) / 3 + 1 : 1;
        int d = atoi(fecha + 4), y = atoi(fecha + 7);
        int h = atoi(hora), mi = atoi(hora + 3), s = atoi(hora + 6);
        *this = DateTime(y, mo, d, h, mi, s);
    }
    uint16_t year() const { return _tm.tm_year + 1900; }
    uint8_t month() const { return _tm.tm_mon + 1; }
    uint8_t day() const { return _tm.tm_mday; }
    uint8_t hour() const { return _tm.tm_hour; }
    uint8_t minute() const { return _tm.tm_min; }
    uint8_t second() const { return _tm.tm_sec; }
    uint8_t dayOfTheWeek() const { return _tm.tm_wday; }
    uint32_t unixtime() const { return _t; }
    uint32_t secondstime() const { return _t - 946684800UL; }
    String timestamp() const {
        char b[24];
        snprintf(b, sizeof(b), "%04u-%02u-%02uT%02u:%02u:%02u", year(), month(), day(), hour(), minute(), second());
        return String(b);
    }
    DateTime operator+(const TimeSpan& s) const { return DateTime(_t + s.totalseconds()); }
    DateTime operator-(const TimeSpan& s) const { return DateTime(_t - s.totalseconds()); }
    TimeSpan operator-(const DateTime& o) const { return TimeSpan((int32_t)(_t - o._t)); }
    bool operator<(const DateTime& o) const { return _t < o._t; }
    bool operator==(const DateTime& o) const { return _t == o._t; }
private:
    uint32_t _t;
    struct tm _tm = {};
    void partir() { time_t t = _t; gmtime_r(&t, &_tm); }
};

class RTC_DS3231 {
public:
    bool begin(TwoWire* = &Wire) { return true; }
    DateTime now() { return DateTime((uint32_t)(::time(nullptr) + _desfase)); }
    void adjust(const DateTime& dt) { _desfase = (long)dt.unixtime() - (long)::time(nullptr); }
    bool lostPower() { return false; }
    float getTemperature() { return 24.75f; }
private:
    long _desfase = 0;
};
