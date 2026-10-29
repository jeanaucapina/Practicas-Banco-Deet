"""Equipo que ejecuta el programa .ino del alumno (nucleo Arduino virtual).

Sustituye a la imitacion de fabrica (controllino.py / esp32plc.py) cuando se
sube un programa con `.\\lab.ps1 subir <equipo> <archivo.ino>`. Aqui no hay
logica del PLC: solo se traducen pines y bus entre el programa y las gafas.

  gafas (pasarela) --orden entrada/analogica--> pin de entrada del programa
  programa --digitalWrite--> "do"/"rele" del estado -> LED en las gafas
  bus RS-485 <--tramas crudas--> Serial3 (Controllino) / RS485 (ESP32)
  Serial2 <--UDP--> HMI virtual del panel (panel/hmi_stone.py), solo Controllino
  loraSerial <--> RN2903 emulado (rn2903.py), solo ESP32; su radio va al aire de tab-lora
  Serial.print -> registro (consola de las gafas y `.\\lab.ps1 serie <equipo>`)

La red (Modbus TCP, MQTT...) no pasa por aqui: el programa abre sockets en las
redes del contenedor, igual que el firmware en el equipo real.
Protocolo con el programa: ver la cabecera de arduino/nucleo.cpp.
"""

import asyncio
import fcntl
import os
import random
import socket
import subprocess
import time

from base import ID, Equipo
from modbus_mini import abrir_rtu
from rn2903 import RN2903

PROGRAMA = "/programas/%s/programa" % ID
TIPO = ID.split(".")[-1]

# HMI virtual: la hace el panel (172.30.99.6), un puerto UDP por tablero (5301, 5302).
# Los bytes de Serial2 viajan tal cual en datagramas UDP, en los dos sentidos.
_N = ID[1:2] if ID[:1] == "t" and ID[1:2].isdigit() else "1"
HMI_DESTINO = (os.environ.get("TAB_HMI_IP", "172.30.99.6"), 5300 + int(_N))
HMI_PUERTO_PROPIO = 5300

# Numeros de pin del nucleo (arduino/Controllino.h y placa_esp32plc.h).
PERFILES = {
    "controllino": {
        "do": list(range(100, 124)), "rele": list(range(130, 146)),
        # discretas como las de controllino.py: A0..A15, I16..I18, IN0, IN1
        "di": [160 + i for i in range(16)] + [180, 181, 182, 183, 184],
        "ai": [160 + i for i in range(16)], "bits_adc": 10,
        "rebote": (180, 181, 182),                  # pulsadores I16-I18 del panel
    },
    "esp32plc": {
        "do": [200, 201, 202, 203], "rele": [204, 205],
        "di": [211 + i for i in range(8)],          # I0.1..I0.8
        "ai": [215, 216, 217, 218], "bits_adc": 12,  # I0.5..I0.8
    },
}
P = PERFILES[TIPO]
AI_MAX = (1 << P["bits_adc"]) - 1


class Programa(Equipo):
    nombre = TIPO

    def __init__(self):
        super().__init__()
        self.salidas = {}                       # pin -> valor escrito
        self.dig = {p: 0 for p in P["di"]}
        self.ana = {p: 0 for p in P["ai"]}
        self.proc = None
        self._w = None                          # tuberia hacia el programa
        self.arranques = 0
        self.nombre_ino = ""
        try:
            self.nombre_ino = open("/programas/%s/nombre" % ID).read().strip()
        except OSError:
            pass
        self._lineas_serie = []                 # para limitar el ritmo del registro
        self._udp_hmi = None
        # Red: lo que pide el programa (Ethernet.begin / WiFi.begin / WiFi.config)
        # y lo que dice la pasarela que tiene (enlace por cable, por WiFi, IP).
        self.red_pedida = None                  # {"ip": "x.x.x.x"|"dhcp", "mac", "wifi"}
        self.red = {"cable": False, "wifi": False, "ip": ""}
        self.rssi = -55
        self.epc = {"conectado": False, "rpm": 0.0, "hz": 0.0}
        # Slot LORA del ESP32 PLC 14: el modulo sigue encendido aunque el programa se
        # reinicie (su sesion LoRaWAN no se pierde; solo un "sys reset" o apagar el equipo).
        self.lora = RN2903(ID, lambda b: self._mandar("L " + b.hex()), self.anotar) \
            if TIPO == "esp32plc" else None

    # ── Hacia el programa ─────────────────────────────────────────────────────
    def _mandar(self, linea: str):
        if self._w is None:
            return
        try:
            os.write(self._w, (linea + "\n").encode())
        except (BlockingIOError, BrokenPipeError, OSError):
            pass

    def _entrada(self, pin):
        self._mandar("i %d %d %d" % (pin, self.dig.get(pin, 0), self.ana.get(pin, 0)))

    def _rebotar(self, pin, v):
        """Pulsador mecanico sin antirrebote (I16-I18 del panel, guia L1): antes de
        quedarse en `v`, el contacto rebota unos milisegundos. Al pulsar rebota mas
        (2-8 flancos espurios en 1-5 ms) que al soltar (0-4 en menos de 2 ms)."""
        # El nucleo aplica los flancos a su tiempo (un hilo con microsegundos): desde
        # aqui saldrian juntos en la misma vuelta del bucle de asyncio.
        n = random.choice((2, 4, 6, 8)) if v else random.choice((0, 2, 4))
        dur = random.uniform(1000, 5000) if v else random.uniform(300, 1800)
        tiempos = sorted(int(random.uniform(50, dur)) for _ in range(n + 1))
        self._mandar("j %d %d %d %s" % (pin, v, self.ana.get(pin, 0), " ".join(str(t) for t in tiempos)))

    def orden(self, d):
        super().orden(d)
        c = d.get("cmd")
        if c == "entrada":
            i = int(d["i"])
            if 0 <= i < len(P["di"]):
                pin = P["di"][i]
                v = 1 if d.get("v") else 0
                cambia = v != self.dig.get(pin, 0)
                self.dig[pin] = v
                if pin in self.ana:
                    self.ana[pin] = AI_MAX if self.dig[pin] else 0
                if cambia and pin in P.get("rebote", ()):
                    self._rebotar(pin, v)
                else:
                    self._entrada(pin)
        elif c == "red":
            self.red = {"cable": bool(d.get("cable")), "wifi": bool(d.get("wifi")), "ip": str(d.get("ip", ""))}
            self._avisar_red_al_programa()
            self._poner_mac()
        elif c == "epc":
            # Entrenador de Planta de Control: el 3D dice si esta cableado a X1 (D0 -> IN
            # MOTOR, GND -> GND MOTOR, IN1 <- ENCODER). Guia L2.
            self.epc["conectado"] = bool(d.get("conectado"))
            self.anotar("EPC %s" % ("cableado a X1" if self.epc["conectado"] else "desconectado"))
        elif c == "rssi":
            self.rssi = int(d.get("v", -55))
            self._avisar_red_al_programa()
        elif c == "carga":
            # Saturacion del segmento (taller U6, Parte III): el micro reparte su CPU
            # entre la pila de red y el lazo, asi que su tiempo de ciclo se degrada. Se lo
            # pasamos al nucleo, que mete retardo en loop() proporcional al nivel (0-100).
            self._mandar("c %d" % int(d.get("nivel", 0)))
        elif c == "analogica":
            i = int(d["i"])
            if 0 <= i < len(P["ai"]):
                pin = P["ai"][i]
                # Las gafas mandan cuentas del equipo real (0-1023 / 0-4095).
                self.ana[pin] = max(0, min(AI_MAX, int(d["v"])))
                if pin in self.dig:
                    self.dig[pin] = 1 if self.ana[pin] > AI_MAX // 2 else 0
                self._entrada(pin)
        elif c in ("modo", "salida", "maestro"):
            self.anotar("el HMI/consola no manda: el equipo corre %s" % (self.nombre_ino or "tu programa"))

    # ── Bus RS-485: crudo, el programa hace su propio Modbus ─────────────────
    def crudo_485(self, data: bytes) -> bool:
        if abrir_rtu(data) is None:
            self.tramas_485["crc_mal"] += 1
        else:
            self.tramas_485["rx"] += 1
        self._mandar("r " + data.hex())
        return True

    # ── Desde el programa ─────────────────────────────────────────────────────
    def _del_programa(self, linea: str):
        if linea.startswith("o "):
            _, pin, v = linea.split()
            self.salidas[int(pin)] = int(v)
        elif linea.startswith("t "):
            # El nucleo ya la emitio byte a byte a sus baudios: acaba de terminar.
            self.enviar_485_crudo(bytes.fromhex(linea[2:].strip()), ya_emitida=True)
        elif linea.startswith("u "):
            # Serial3.begin / Serial1.begin / RS485.begin: baudios y formato de la UART
            _, baud, fmt = linea.split()
            self.linea = [int(baud), fmt]
            self.anotar("RS-485 a %s baudios %s" % (baud, fmt))
        elif linea.startswith("a "):
            self.anotar(linea[2:])
        elif linea.startswith("h "):
            self._a_hmi(bytes.fromhex(linea[2:].strip()))
        elif linea.startswith("l "):
            if self.lora is not None:
                self.lora.recibir(bytes.fromhex(linea[2:].strip()))
        elif linea.startswith("n "):
            self._pide_red(linea[2:].split())

    # ── Red: el programa pide IP; la pasarela la aplica con docker network ───
    def _pide_red(self, p):
        # p = [iface, ip|dhcp|-, mac|-, radio(0/1)]
        if len(p) < 4:
            return
        iface, ip, mac, radio = p[0], p[1], p[2], p[3] == "1"
        antes = dict(self.red_pedida or {})
        nuevo = dict(antes)
        if iface == "WiFi" and ip == "-":                  # WiFi.disconnect()
            nuevo["wifi"] = False
        else:
            nuevo["ip"] = ip
            if mac != "-":
                nuevo["mac"] = mac
            if iface == "WiFi":
                nuevo["wifi"] = radio
        self.red_pedida = nuevo
        self._poner_mac()
        if nuevo != antes:
            if iface == "WiFi" and ip == "-":
                self.anotar("WiFi desconectada por el programa")
            else:
                self.anotar("%s pide %s%s" % (iface, "DHCP" if ip == "dhcp" else "IP " + ip,
                                              (" con MAC " + mac) if mac != "-" else ""))

    def _poner_mac(self):
        """La MAC de Ethernet.begin(mac, ...) se pone en la interfaz del
        segmento del banco (arp -a desde el PC la muestra). Se comprueba en cada
        vuelta del estado: Docker reconecta las redes al reiniciar y la cambia."""
        mac = (self.red_pedida or {}).get("mac", "")
        ip = self.red.get("ip", "")
        if not mac or not ip or time.time() - getattr(self, "_t_mac", 0) < 2.0:
            return
        self._t_mac = time.time()
        try:
            out = subprocess.run(["ip", "-o", "-4", "addr"], capture_output=True, text=True, timeout=3).stdout
            iface = next((l.split()[1] for l in out.splitlines() if (" " + ip + "/") in l), None)
            if not iface:
                return
            actual = subprocess.run(["cat", "/sys/class/net/%s/address" % iface], capture_output=True,
                                    text=True, timeout=3).stdout.strip().lower()
            if actual == mac.lower():
                return
            for orden in (["ip", "link", "set", "dev", iface, "down"],
                          ["ip", "link", "set", "dev", iface, "address", mac],
                          ["ip", "link", "set", "dev", iface, "up"]):
                subprocess.run(orden, capture_output=True, timeout=3)
            self.anotar("MAC %s en la interfaz del banco (%s)" % (mac, ip))
        except (OSError, subprocess.SubprocessError):
            pass

    def _avisar_red_al_programa(self):
        r = self.red
        self._mandar("N %d %d %s %d" % (1 if r.get("cable") else 0, 1 if r.get("wifi") else 0,
                                        r.get("ip") or "-", self.rssi))

    # ── HMI (Serial2): UDP con el panel, que hace de pantalla tipo Stone ─────
    def _a_hmi(self, datos: bytes):
        if self._udp_hmi is None:
            return
        try:
            self._udp_hmi.sendto(datos, HMI_DESTINO)
        except OSError:
            pass

    def _de_hmi(self):
        try:
            while True:
                datos, _ = self._udp_hmi.recvfrom(4096)
                self._mandar("H " + datos.hex())
        except (BlockingIOError, OSError):
            pass

    def _serie(self, linea: str):
        # El registro va a las gafas: como mucho 5 lineas por segundo (un
        # Serial.println() en cada loop() lo inundaria). Docker las ve todas.
        print("Serial: " + linea, flush=True)
        ahora = time.time()
        self._lineas_serie = [t for t in self._lineas_serie if ahora - t < 1.0]
        if len(self._lineas_serie) < 5:
            self._lineas_serie.append(ahora)
            self.log.append(time.strftime("%H:%M:%S ") + "Serial: " + linea)
            del self.log[:-12]

    async def _leer(self, lector, que):
        while True:
            linea = await lector.readline()
            if not linea:
                return
            txt = linea.decode("utf-8", "replace").rstrip("\r\n")
            (self._del_programa if que == "pines" else self._serie)(txt)

    async def _correr(self):
        loop = asyncio.get_running_loop()
        while True:
            r_out, w_out = os.pipe()            # programa -> aqui
            r_in, w_in = os.pipe()              # aqui -> programa
            fcntl.fcntl(w_in, fcntl.F_SETFL, fcntl.fcntl(w_in, fcntl.F_GETFL) | os.O_NONBLOCK)
            env = dict(os.environ, VINO_FD_OUT=str(w_out), VINO_FD_IN=str(r_in))
            self.proc = await asyncio.create_subprocess_exec(
                PROGRAMA, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                pass_fds=(w_out, r_in), env=env)
            os.close(w_out)
            os.close(r_in)
            self._w = w_in
            self.arranques += 1
            # Resolucion del ADC (pin 255), red y estado inicial de las entradas.
            self._mandar("i 255 0 %d" % P["bits_adc"])
            self.red_pedida = None              # un programa nuevo pide su red de cero
            self._avisar_red_al_programa()
            for pin in set(self.dig) | set(self.ana):
                self._entrada(pin)
            lector = asyncio.StreamReader()
            await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(lector), os.fdopen(r_out, "rb"))
            tareas = [asyncio.ensure_future(self._leer(lector, "pines")),
                      asyncio.ensure_future(self._leer(self.proc.stdout, "serie"))]
            self.anotar("corriendo %s" % (self.nombre_ino or "el programa"))
            rc = await self.proc.wait()
            for t in tareas:
                t.cancel()
            os.close(w_in)
            self._w = None
            self.salidas.clear()                # un PLC parado deja las salidas a 0
            self.anotar("el programa se detuvo (codigo %d): se reinicia en 2 s" % rc)
            await asyncio.sleep(2.0)

    async def iniciar(self):
        if TIPO == "controllino":
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setblocking(False)
            s.bind(("0.0.0.0", HMI_PUERTO_PROPIO))
            self._udp_hmi = s
            asyncio.get_running_loop().add_reader(s.fileno(), self._de_hmi)
            asyncio.ensure_future(self._bucle_epc())
        if self.lora is not None:
            await self.lora.iniciar()
        asyncio.ensure_future(self._correr())

    # ── EPC: motor DC con encoder de 36 pulsos/rev en el puerto X1 (guia L2) ───
    EPC_D0, EPC_IN1 = 100, 184          # D0 de X1 (PWM de mando) e IN1 de X1 (pulsos)
    EPC_RPM_MAX, EPC_ZONA_MUERTA, EPC_TAU = 3800.0, 0.12, 0.35

    async def _bucle_epc(self):
        """Velocidad del motor a partir del PWM de D0: zona muerta del puente, primer
        orden con constante de tiempo de 0,35 s y un poco de rizado. Los pulsos del
        encoder los genera el nucleo en IN1 (36 por vuelta)."""
        dt = 0.02
        while True:
            await asyncio.sleep(dt)
            v = int(self.salidas.get(self.EPC_D0, 0))
            duty = 1.0 if v == 1 else max(0, min(v, 255)) / 255.0     # digitalWrite HIGH = 100 %
            obj = 0.0
            if self.epc["conectado"] and duty > self.EPC_ZONA_MUERTA:
                obj = self.EPC_RPM_MAX * (duty - self.EPC_ZONA_MUERTA) / (1 - self.EPC_ZONA_MUERTA)
            rpm = self.epc["rpm"] + (obj - self.epc["rpm"]) * dt / self.EPC_TAU
            if rpm < 1:
                rpm = 0.0
            self.epc["rpm"] = rpm
            hz = rpm * 36 / 60 * (1 + random.uniform(-0.004, 0.004)) if rpm > 0 else 0.0
            if abs(hz - self.epc["hz"]) > max(0.5, 0.005 * hz) or (hz == 0) != (self.epc["hz"] == 0):
                self.epc["hz"] = hz
                self._mandar("p %d %.2f" % (self.EPC_IN1, hz))

    def estado(self):
        self._poner_mac()
        sal = lambda pins: [1 if self.salidas.get(p, 0) else 0 for p in pins]
        d = {
            "do": sal(P["do"]), "rele": sal(P["rele"]),
            "di": [self.dig[p] for p in P["di"]],
            "ai": [self.ana[p] for p in P["ai"]],
            "hr": [], "peticiones": {}, "programa": self.nombre_ino,
            "red_pedida": self.red_pedida, "red": self.red,
            "modo": 9,                              # 9 = programa del alumno (no el de fabrica)
        }
        if TIPO == "controllino":
            d["epc"] = {"conectado": self.epc["conectado"], "rpm": int(self.epc["rpm"])}
            d.update({"unidad": 0, "remoto": 0,
                      "maestro": {"ok": 0, "sin_respuesta": 0, "ultimo": ""}})
        else:
            # S0_24v..S3_24v: modo de Q0.0..Q0.3 (LOW 5 V, HIGH 24 V), para el multimetro
            d.update({"maestro": 0, "broker": "", "s24": sal([220, 221, 222, 223])})
            d["lora"] = self.lora.resumen()
        return d


if __name__ == "__main__":
    asyncio.run(Programa().correr())
