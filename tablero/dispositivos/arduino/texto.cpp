// String e IPAddress de Arduino sobre std::string.
#include "Arduino.h"

#include <algorithm>
#include <cctype>

static std::string en_base(unsigned long n, int base) {
    if (base < 2 || base > 16) base = 10;
    std::string r;
    do { r.insert(r.begin(), "0123456789abcdef"[n % base]); n /= base; } while (n);
    return r;
}

String::String(long v, int base) {
    if (base == 10 && v < 0) s = "-" + en_base((unsigned long)(-v), 10);
    else s = en_base((unsigned long)v, base);
}

String::String(unsigned long v, int base) : s(en_base(v, base)) {}

String::String(double v, int decimales) {
    char b[64];
    snprintf(b, sizeof b, "%.*f", decimales, v);
    s = b;
}

bool String::equalsIgnoreCase(const String& o) const {
    if (s.size() != o.s.size()) return false;
    for (size_t i = 0; i < s.size(); i++)
        if (tolower((unsigned char)s[i]) != tolower((unsigned char)o.s[i])) return false;
    return true;
}

int String::indexOf(char c, unsigned int desde) const {
    size_t k = s.find(c, desde);
    return k == std::string::npos ? -1 : (int)k;
}

int String::indexOf(const String& t, unsigned int desde) const {
    size_t k = s.find(t.s, desde);
    return k == std::string::npos ? -1 : (int)k;
}

int String::lastIndexOf(char c) const {
    size_t k = s.rfind(c);
    return k == std::string::npos ? -1 : (int)k;
}

int String::lastIndexOf(const String& t) const {
    size_t k = s.rfind(t.s);
    return k == std::string::npos ? -1 : (int)k;
}

String String::substring(unsigned int desde) const {
    return desde >= s.size() ? String("") : String(s.substr(desde));
}

String String::substring(unsigned int desde, unsigned int hasta) const {
    if (desde > hasta) std::swap(desde, hasta);
    if (desde >= s.size()) return String("");
    return String(s.substr(desde, hasta - desde));
}

bool String::endsWith(const String& t) const {
    return s.size() >= t.s.size() && s.compare(s.size() - t.s.size(), t.s.size(), t.s) == 0;
}

void String::trim() {
    size_t a = s.find_first_not_of(" \t\r\n");
    size_t b = s.find_last_not_of(" \t\r\n");
    s = a == std::string::npos ? "" : s.substr(a, b - a + 1);
}

void String::toUpperCase() { for (auto& c : s) c = (char)toupper((unsigned char)c); }
void String::toLowerCase() { for (auto& c : s) c = (char)tolower((unsigned char)c); }

void String::replace(const String& a, const String& b) {
    if (a.s.empty()) return;
    for (size_t k = 0; (k = s.find(a.s, k)) != std::string::npos; k += b.s.size()) s.replace(k, a.s.size(), b.s);
}

void String::replace(char a, char b) { std::replace(s.begin(), s.end(), a, b); }

void String::remove(unsigned int i, unsigned int n) { if (i < s.size()) s.erase(i, n); }

void String::getBytes(byte* b, unsigned int n) const {
    if (!n) return;
    size_t k = std::min<size_t>(n - 1, s.size());
    memcpy(b, s.data(), k);
    b[k] = 0;
}

String operator+(const String& a, const String& b) { String r(a); r += b; return r; }
String operator+(const String& a, const char* b) { String r(a); r += b; return r; }
String operator+(const char* a, const String& b) { String r(a); r += b; return r; }
String operator+(const String& a, char b) { String r(a); r += b; return r; }

bool IPAddress::fromString(const char* t) {
    unsigned v[4];
    if (!t || sscanf(t, "%u.%u.%u.%u", &v[0], &v[1], &v[2], &v[3]) != 4) return false;
    for (int i = 0; i < 4; i++) {
        if (v[i] > 255) return false;
        b[i] = (uint8_t)v[i];
    }
    return true;
}

String IPAddress::toString() const {
    char t[16];
    snprintf(t, sizeof t, "%u.%u.%u.%u", b[0], b[1], b[2], b[3]);
    return String(t);
}
