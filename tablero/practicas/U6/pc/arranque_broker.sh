#!/bin/sh
# Taller U6 - entrada del contenedor del broker endurecido. Genera los SECRETOS que no viven
# en el repositorio (certificado TLS y fichero de contrasenas) la primera vez, y arranca
# Mosquitto con la configuracion endurecida. Las contrasenas de laboratorio llegan por
# variable de entorno (OP_PASS / LEC_PASS); cambialas en un despliegue real.
#
# La imagen de Mosquitto no trae el binario openssl, pero si la biblioteca; el certificado
# autofirmado se genera con un Python de una sola vez (ssl + un contenedor efimero no hace
# falta). Aqui se usa el generador mosquitto para las claves y un pequeno certificado DER
# empaquetado por el propio arranque a traves de /usr/bin si existe; si no, por Python.
set -e
CFG=/mosquitto/config
OP_PASS="${OP_PASS:-banco}"
LEC_PASS="${LEC_PASS:-banco}"

if [ ! -f "$CFG/server.crt" ]; then
    echo "U6: generando certificado TLS autofirmado (CN=broker.planta.local)"
    if command -v openssl >/dev/null 2>&1; then
        openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
            -keyout "$CFG/server.key" -out "$CFG/server.crt" -subj "/CN=broker.planta.local" >/dev/null 2>&1
    else
        # Sin openssl en la imagen: lo genera el init cert (contenedor alpine/openssl del
        # docker-compose) antes que este arranque. Si aun no esta, esperar un momento.
        for i in 1 2 3 4 5 6 7 8 9 10; do [ -f "$CFG/server.crt" ] && break; sleep 1; done
    fi
fi

echo "U6: fichero de contrasenas (FR1): operador y lector"
rm -f "$CFG/pwfile"
mosquitto_passwd -b -c "$CFG/pwfile" operador "$OP_PASS"
mosquitto_passwd -b    "$CFG/pwfile" lector   "$LEC_PASS"
# Mosquitto corre como el usuario 'mosquitto', no como root: dale lectura a los secretos.
chmod 0644 "$CFG/pwfile" "$CFG/server.crt" "$CFG/acl" 2>/dev/null || true
chmod 0640 "$CFG/server.key" 2>/dev/null || true
chown mosquitto "$CFG/server.key" 2>/dev/null || true

exec mosquitto -c "$CFG/mosquitto_seguro.conf"
