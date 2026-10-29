#!/usr/bin/env python3
"""Convertidor USB-RS485 del PC del banco: /dev/ttyUSB0 unido al bus del tablero.

Crea un pseudo-terminal y lo enlaza como /dev/ttyUSB0. Lo que escriba la aplicacion
(mbpoll, QModMaster, picocom, un script con pyserial...) sale al par a los baudios y
con el formato que ESA aplicacion configuro en el tty (stty / termios): cada byte
tarda lo que tarda, y la trama acaba tras 3,5 caracteres de silencio. Lo que llega
del bus se lee con la UART del convertidor (bus485.py): baudios o formato distintos
dan basura, A/B cruzados no sincronizan y dos emisores a la vez colisionan.

Habla con la pasarela por TCP (172.30.99.1:4860); protocolo en pasarela.py
(_usb_atender). Lo arranca editor_arranque.sh y se reintenta solo.
"""
import asyncio
import os
import pty
import sys
import termios
import time
import tty

sys.path.insert(0, "/opt/banco")
import bus485  # noqa: E402

ENLACE = "/dev/ttyUSB0"
PASARELA = ("172.30.99.1", 4860)
GUARDA = 0.001
BAUDIOS = {getattr(termios, "B%d" % b): b for b in (300, 600, 1200, 2400, 4800, 9600, 19200, 38400,
                                                     57600, 115200, 230400) if hasattr(termios, "B%d" % b)}


class Convertidor:
    def __init__(self):
        self.maestro, self.esclavo = pty.openpty()
        tty.setraw(self.esclavo)
        a = termios.tcgetattr(self.esclavo)
        a[3] &= ~termios.ECHO
        a[4] = a[5] = termios.B19200            # como sale de fabrica
        termios.tcsetattr(self.esclavo, termios.TCSANOW, a)
        os.set_blocking(self.maestro, False)
        nombre = os.ttyname(self.esclavo)
        os.chmod(nombre, 0o666)
        try:
            os.remove(ENLACE)
        except OSError:
            pass
        os.symlink(nombre, ENLACE)
        self.escritor = None
        self.linea_enviada = None
        self.cruzado = False
        self.ruido = 0.0
        self.tx = b""
        self.tx_ini = self.tx_fin = 0.0
        self.temporizador = None
        self.en_par = []

    def linea(self):
        """Baudios y formato que la aplicacion puso en el tty."""
        try:
            iflag, oflag, cflag, lflag, ispeed, ospeed, cc = termios.tcgetattr(self.esclavo)
        except termios.error:
            return [19200, "8N1"]
        datos = {termios.CS5: 5, termios.CS6: 6, termios.CS7: 7, termios.CS8: 8}.get(cflag & termios.CSIZE, 8)
        paridad = "N" if not cflag & termios.PARENB else ("O" if cflag & termios.PARODD else "E")
        return [BAUDIOS.get(ospeed, 19200), "%d%s%d" % (datos, paridad, 2 if cflag & termios.CSTOPB else 1)]

    def _mandar(self, txt):
        if self.escritor is not None and not self.escritor.is_closing():
            self.escritor.write((txt + "\n").encode())

    def _avisar_linea(self):
        ln = self.linea()
        if ln != self.linea_enviada:
            self.linea_enviada = ln
            self._mandar("L %d %s" % (ln[0], ln[1]))
        return ln

    # ── Hacia el bus ─────────────────────────────────────────────────────────
    def legible(self):
        try:
            datos = os.read(self.maestro, 4096)
        except (BlockingIOError, OSError):
            return
        if not datos:
            return
        baud, fmt = self._avisar_linea()
        ahora = time.time()
        if not self.tx:
            self.tx_ini = max(ahora, self.tx_fin)
            self.tx_fin = self.tx_ini
        self.tx += datos
        self.tx_fin = max(self.tx_fin, ahora) + bus485.duracion(len(datos), baud, fmt)
        if self.temporizador:
            self.temporizador.cancel()
        espera = self.tx_fin - ahora + bus485.t35(baud, fmt)
        self.temporizador = asyncio.get_running_loop().call_later(max(0.0, espera), self._cerrar)

    def _cerrar(self):
        t, self.tx = self.tx, b""
        if not t:
            return
        baud, fmt = self.linea()
        self.en_par.append(bus485.Segmento(self.tx_ini, t, baud, fmt, self.cruzado))
        self._mandar("T " + t.hex())

    # ── Desde el bus ─────────────────────────────────────────────────────────
    def trama(self, baud, fmt, cruzado, datos):
        fin = time.time()
        seg = bus485.Segmento(fin - bus485.duracion(len(datos), baud, fmt), datos, baud, fmt, cruzado)
        self.en_par = [x for x in self.en_par if fin - x.t1 < 1.0] + [seg]
        asyncio.get_running_loop().call_later(GUARDA, self._oir, seg)

    def abierto(self) -> bool:
        """¿Alguna aplicacion tiene abierto /dev/ttyUSB0? Con el puerto cerrado el
        convertidor real tira lo que oye; el pty, en cambio, lo guardaria y la
        siguiente aplicacion leeria tramas viejas."""
        ahora = time.time()
        if ahora - getattr(self, "_t_abierto", 0) < 0.2:
            return self._abierto
        self._t_abierto, self._abierto = ahora, False
        nombre, yo = os.ttyname(self.esclavo), str(os.getpid())
        for pid in os.listdir("/proc"):
            if not pid.isdigit() or pid == yo:
                continue
            try:
                for fd in os.listdir("/proc/%s/fd" % pid):
                    if os.readlink("/proc/%s/fd/%s" % (pid, fd)) == nombre:
                        self._abierto = True
                        return True
            except OSError:
                continue
        return False

    def _oir(self, seg):
        if not self.abierto():
            return
        otras = [x for x in self.en_par if x is not seg and x.t0 < seg.t1 and seg.t0 < x.t1]
        baud, fmt = self.linea()
        # El ruido que reparte la pasarela es el de 38 400 baudios (como en base.py):
        # a 19 200 o menos el bus mal terminado aun no da errores.
        p = min(0.9, self.ruido * max(0.0, (baud - 19200) / 19200.0))
        datos = bus485.ruido(bus485.leer([seg] + otras, baud, fmt, self.cruzado), p)
        if datos:
            try:
                os.write(self.maestro, datos)
            except OSError:
                pass

    async def correr(self):
        loop = asyncio.get_running_loop()
        loop.add_reader(self.maestro, self.legible)
        while True:
            try:
                lector, self.escritor = await asyncio.open_connection(*PASARELA)
            except OSError:
                await asyncio.sleep(2)
                continue
            self.linea_enviada = None
            self._avisar_linea()
            try:
                while True:
                    l = await lector.readline()
                    if not l:
                        break
                    p = l.decode(errors="replace").split()
                    if len(p) == 5 and p[0] == "R":
                        self.trama(int(p[1]), p[2], p[3] == "1", bytes.fromhex(p[4]))
                    elif len(p) == 3 and p[0] == "P":
                        self.cruzado, self.ruido = p[1] == "1", float(p[2])
                    self._avisar_linea()
            except (ConnectionError, OSError, ValueError):
                pass
            self.escritor = None
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(Convertidor().correr())
