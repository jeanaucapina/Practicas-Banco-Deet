#!/bin/sh
# PC del alumno: escritorio virtual visto por el navegador (noVNC, 6080), terminal
# web (ttyd, 7681), convertidor USB-RS485 en /dev/ttyUSB0 y OpenPLC Editor.
export DISPLAY=:1
# Tras un `docker restart` el bloqueo del arranque anterior sigue en el disco del
# contenedor y Xvfb se niega a empezar ("Server is already active for display 1").
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
Xvfb :1 -screen 0 1600x900x24 -nolisten tcp &
# Esperar a que la pantalla exista antes de lanzar lo que la usa.
for i in $(seq 1 50); do
    xdpyinfo -display :1 >/dev/null 2>&1 && break
    sleep 0.2
done
xsetroot -solid "#2b3a4a"
openbox &
tint2 -c /etc/pc_escritorio/tint2rc &
x11vnc -display :1 -forever -shared -nopw -quiet -rfbport 5900 &
websockify --web /usr/share/novnc 6080 localhost:5900 &
# Terminal en el navegador, para quien prefiera no usar el escritorio.
ttyd -p 7681 -W -t titleFixed="Terminal del PC (192.168.1.100)" bash -l &
# Convertidor USB-RS485: /dev/ttyUSB0 unido al bus RS-485 del banco a traves de la
# pasarela (puerto 4860 de la red de gestion), con los baudios y el formato que la
# aplicacion ponga en el tty (openplc/usb485.py). Se reintenta si la pasarela reinicia.
(
    while true; do
        python3 /opt/banco/usb485.py
        sleep 2
    done
) &
# Los ejemplos se copian (sin pisar) a la carpeta de proyectos del alumno,
# que es tablero/openplc/proyectos en el PC.
# La ventana "Save to file" del editor arranca en /OpenPLC_Editor: un marcador
# "Proyectos" en su barra lateral lleva a la carpeta compartida con el PC.
mkdir -p /root/.config/gtk-3.0
grep -q "/proyectos" /root/.config/gtk-3.0/bookmarks 2>/dev/null || echo "file:///proyectos Proyectos" >> /root/.config/gtk-3.0/bookmarks
mkdir -p /proyectos/ejemplos
cp -rn /ejemplos/* /proyectos/ejemplos/ 2>/dev/null
# Prompt de la terminal con la IP del banco, como en el PC del laboratorio.
grep -q "PS1=.*alumno" /root/.bashrc 2>/dev/null || cat >> /root/.bashrc <<'EOF'
export PS1='alumno@pc-banco:\w\$ '
echo "PC del banco. Red: $(ip -4 -o addr show | awk '/192\.168\.1\./{print $2" "$4}' | head -1 || true)"
echo "Si no hay 192.168.1.x: enchufa en el 3D el cable del PC al switch del tablero."
EOF
cd /OpenPLC_Editor
# El editor se abre una vez al arrancar, con el ejemplo; despues se lanza desde la barra.
./.venv/bin/python3 ./editor/Beremiz.py /proyectos/ejemplos/boton_matriz &
wait
