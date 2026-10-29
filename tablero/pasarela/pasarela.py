#!/usr/bin/env python3
"""Pasarela entre las gafas y el tablero simulado en Docker.

Corre en el PC del laboratorio (el que tiene Docker y Wireshark), sin
dependencias: solo Python 3 y el comando `docker`.

  gafas  --TCP 7070, JSON por lineas-->  pasarela  --docker network connect-->  contenedores
         <--estado 10 Hz--------------            <--UDP 9001 (tab-gestion)--

Lo que hace:
  - Guarda el cableado del tablero (quien esta enchufado a que). Es la unica
    fuente de verdad: si hay dos visores, los dos ven los mismos cables.
  - Latiguillo Ethernet entre un equipo y el switch -> `docker network
    connect tab_lan <contenedor> --ip ...`. Quitarlo -> `disconnect`. El enlace
    se cae de verdad: el ping deja de responder y las conexiones TCP se rompen.
  - Cables en los bornes A/B de RS-485 -> calcula que equipos comparten bus,
    con que polaridad y por que puerto UDP va cada bus, y se lo dice a cada uno.
  - Interruptores de energia de cada tablero -> `docker pause/unpause`.
  - Hace de adaptador USB-RS485 del PC: crea un pseudo-terminal
    (run/ttyTAB485) para QModMaster o mbpoll, unido al bus simulado.
  - Lee los contadores de paquetes de cada puerto del switch (las veth del
    puente) para que los LED de actividad parpadeen con el trafico real.
  - Anuncia su IP por difusion UDP en el 7071 para que las gafas la encuentren
    solas.
  - Captura tab-lan (con herramientas/sniffer.py en un contenedor con NET_RAW)
    y los buses RS-485, y manda a las gafas las ultimas tramas decodificadas
    (tramas.py) para la pantalla del PC.

Uso:  python3 pasarela/pasarela.py            (con `docker compose up -d` antes)
"""

import asyncio
import json
import os
import pty
import socket
import subprocess
import sys
import termios
import time
import tty
from collections import deque

import tramas

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
RUN = os.path.join(RAIZ, "run")
FICHERO_CABLES = os.path.join(RUN, "cableado.json")
TTY_ENLACE = os.path.join(RUN, "ttyTAB485")

# En Docker Desktop el 7070 publicado para las gafas lo ocupa el propio Docker
# dentro de la VM: ahi la pasarela escucha en otro (TAB_PUERTO_GAFAS=7170) y el
# contenedor tab-puerta traduce 7070 -> 7170.
PANEL_IP = "172.30.99.6"          # panel web del PC (docker-compose: panel)
PUERTO_GAFAS = int(os.environ.get("TAB_PUERTO_GAFAS", "7070"))
PUERTO_BALIZA = 7071
PUERTO_ESTADO = 9001
PUERTO_ORDEN = 9000
PUERTO_485 = 4850
BUS_485 = "172.30.85.255"
IP_485_PC = "172.30.85.1"

# ── Los tableros ──────────────────────────────────────────────────────────────
# El segmento del banco es 192.168.1.0/24, como en las guias del curso: ESP32 PLC
# del tablero 1 en .10 (la IP de las guias L4, L7 y L9), PC del alumno en .100,
# atacante (U6) en .101 y la "pasarela" .1 (el anfitrion de Docker). El punto de
# acceso WiFi esta puenteado al mismo segmento: WiFi y cable dan IP de la misma red.
# Cada equipo tiene una IP de fabrica; el programa del alumno la cambia con
# Ethernet.begin(mac, ip) / WiFi.config(ip, ...) o pide DHCP (pool .150-.199).
N_TABLEROS = int(os.environ.get("TAB_N", "2"))
RED_LAN = "tab_lan"
PREFIJO_LAN = "192.168.1."
EQUIPOS = {}
PUERTOS = {"usb485.A": "borne", "usb485.B": "borne",   # adaptador USB-RS485 del PC
           "pc.eth": "eth",                             # tarjeta de red del PC del alumno
           "lora.eth": "eth",                           # RJ45 de la pasarela LoRaWAN
           # USB del PC: para programar un PLC hay que cablearlo (USB-B del Controllino,
           # micro USB del ESP32), como en el banco real. Sin cable no se puede subir.
           "pc.usb1": "usb", "pc.usb2": "usb", "pc.usb3": "usb", "pc.usb4": "usb"}
# Estaciones que no son PLC: solo tienen cable de red (el PC del alumno).
ESTACIONES = {"pc": {"contenedor": "tab-editor", "lan": PREFIJO_LAN + "100"},
              # pasarela LoRaWAN del laboratorio (guia L10): su RJ45 al switch = backhaul
              "lora": {"contenedor": "tab-lora", "lan": PREFIJO_LAN + "70"}}
for _n in range(1, N_TABLEROS + 1):
    EQUIPOS["t%d.controllino" % _n] = {"contenedor": "tab%d-controllino" % _n,
                                       "gestion": "172.30.99.1%d" % _n, "ip485": "172.30.85.1%d" % _n,
                                       "lan": PREFIJO_LAN + "1%d" % _n, "wifi": False}
    EQUIPOS["t%d.esp32plc" % _n] = {"contenedor": "tab%d-esp32plc" % _n,
                                    "gestion": "172.30.99.2%d" % _n, "ip485": "172.30.85.2%d" % _n,
                                    "lan": PREFIJO_LAN + "%d" % (10 * _n), "wifi": True}
    for _e in ("controllino", "esp32plc"):
        PUERTOS["t%d.%s.eth" % (_n, _e)] = "eth"
        PUERTOS["t%d.%s.usb" % (_n, _e)] = "usb"
        PUERTOS["t%d.%s.485A" % (_n, _e)] = "borne"
        PUERTOS["t%d.%s.485B" % (_n, _e)] = "borne"
    for _k in range(1, 5):
        PUERTOS["t%d.switch.p%d" % (_n, _k)] = "eth"
# Cada switch es su propia red: los equipos de dos tableros solo se ven si un
# latiguillo une sus switches (p. ej. t1.switch.p4 <-> t2.switch.p4). Ver
# segmentos(). Los servidores del laboratorio (broker, Node-RED, FUXA...) y la WiFi
# no pasan por ningun switch del tablero: los alcanzan todos.

# Interruptores de energia de cada tablero (etiqueta superior izquierda).
ENERGIA = ["switch", "hmi", "esp32plc", "controllino", "fuente"]


def ahora():
    return time.strftime("%H:%M:%S")


def docker(*args) -> tuple:
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=15)
    return r.returncode, (r.stdout + r.stderr).strip()


class Pasarela:
    def __init__(self):
        os.makedirs(RUN, exist_ok=True)
        self.cables = {}            # id -> {"a": puerto, "b": puerto}
        self.equipos = {}           # nombre -> ultimo estado recibido
        self.visto = {}             # nombre -> hora del ultimo estado
        self.lan = {}               # nombre -> True si esta en tab_lan (por cable o por WiFi)
        self.cable = {}             # nombre -> True si su RJ45 llega a un switch con corriente
        self.wifi = {}              # nombre -> True si su radio WiFi esta encendida
        self.ip = {}                # nombre -> IP que tiene ahora en tab_lan
        self.red_avisada = {}       # nombre -> ultimo {"cable","wifi","ip"} mandado al equipo
        self.bus = {}               # nombre -> {"en_bus", "invertido", "puerto"}
        self.linea_pc = [19200, "8N1"]   # la del convertidor USB-RS485 del PC (la de su tty)
        self.electrico = {}         # nombre -> {"rab", "vab"} medidos en el 3D (capa electrica)
        self.energia = {}           # "tN.equipo" -> False si su interruptor esta apagado
        self.pausado = {}           # nombre -> True si el contenedor esta en pausa
        self.puertos_sw = {}        # "switch.pN" -> {"link", "tx", "rx"}
        self.epc_estado = {}        # nom -> EPC cableado a X1 (guia L2), para reenviarlo tras un reinicio
        # HMI STONE de cada tablero tal como la diseño y programa el alumno (guia L2). La
        # pantalla vive en el panel; aqui solo se reenvia: panel -> 3D (lo que se ve) y
        # 3D -> panel (los toques, numerados para que el panel no los repita).
        self.hmi = {}               # "1"/"2" -> {"pagina", "widgets", "valores", "textos", "series"}
        self.hmi_toques = deque(maxlen=30)
        self._hmi_seq = 0
        self.clientes = set()
        self.eventos = []
        self._veth = {}             # nombre equipo -> interfaz veth en el anfitrion
        self._tty_fd = None
        self._usb_clientes = set()   # /dev/ttyUSB0 del PC del alumno, por TCP
        self._sock_orden = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socks485 = {}         # puerto UDP del segmento -> socket
        self.tramas = deque(maxlen=60)
        self._n_trama = 0
        self._cargar()

    def evento(self, txt):
        print(ahora(), txt, flush=True)
        self.eventos.append(ahora() + " " + txt)
        del self.eventos[:-10]

    # ── Persistencia del cableado ─────────────────────────────────────────────
    def _cargar(self):
        try:
            with open(FICHERO_CABLES) as f:
                self.cables = json.load(f)
        except (OSError, ValueError):
            self.cables = {}

    def _guardar(self):
        with open(FICHERO_CABLES, "w") as f:
            json.dump(self.cables, f, indent=1)

    # ── Topologia ─────────────────────────────────────────────────────────────
    def _otro_extremo(self, puerto):
        for c in self.cables.values():
            if c["a"] == puerto:
                return c["b"]
            if c["b"] == puerto:
                return c["a"]
        return None

    def validar(self, a, b):
        if a not in PUERTOS or b not in PUERTOS:
            return "puerto desconocido"
        if a == b:
            return "un cable necesita dos extremos"
        if PUERTOS[a] != PUERTOS[b]:
            return "ese cable no encaja: RJ45 con RJ45, bornes con bornes"
        if PUERTOS[a] == "eth":
            ocupado = [p for p in (a, b) if self._otro_extremo(p) is not None]
            if ocupado:
                return "%s ya tiene un cable" % ocupado[0]
            if ".switch." not in a and ".switch." not in b:
                return "el latiguillo va de un equipo a un switch"
        if PUERTOS[a] == "usb":
            ocupado = [p for p in (a, b) if self._otro_extremo(p) is not None]
            if ocupado:
                return "%s ya tiene un cable" % ocupado[0]
            if not (a.startswith("pc.") ^ b.startswith("pc.")):
                return "el cable USB va del PC a un PLC"
        return None

    def encendido(self, clave):
        """Un equipo tiene corriente si su interruptor y el de la fuente de su
        tablero estan encendidos."""
        t = clave.split(".")[0]
        return self.energia.get(clave, True) and self.energia.get(t + ".fuente", True)

    async def aplicar(self):
        """Lleva Docker y los equipos al estado que dice el cableado."""
        # Energia: sin corriente, el contenedor se congela (docker pause). Deja
        # de responder de verdad, como un PLC apagado.
        for nom, eq in EQUIPOS.items():
            quiere = not self.encendido(nom)
            if self.pausado.get(nom) is not None and quiere != self.pausado[nom]:
                rc, out = await asyncio.to_thread(docker, "unpause" if not quiere else "pause",
                                                  eq["contenedor"])
                if rc == 0 or "not paused" in out or "already paused" in out:
                    self.pausado[nom] = quiere
                    self.evento("%s %s" % (nom, "APAGADO" if quiere else "encendido"))
        # Red: un equipo esta en la LAN si su RJ45 acaba en un switch con
        # corriente o si tiene la WiFi encendida (el punto de acceso esta en el
        # mismo segmento). Con la IP que pida su programa, o la de fabrica.
        for nom in list(EQUIPOS) + list(ESTACIONES):
            otro = self._otro_extremo(nom + ".eth")
            self.cable[nom] = bool(otro is not None and ".switch." in otro
                                   and self.encendido(otro.split(".")[0] + ".switch"))
            quiere = self.cable[nom] or self._wifi_on(nom)
            if self.lan.get(nom) is None:
                continue                          # contenedor parado
            ip = self.ip_deseada(nom)
            if quiere != self.lan.get(nom):
                await self._red(nom, quiere, ip)
            elif quiere and ip != self.ip.get(nom):
                await self._red(nom, False, self.ip.get(nom, ""))
                await self._red(nom, True, ip)
            self._avisar_red(nom)
        # RS-485: nodos = bornes, aristas = cables. Cada red electrica es una
        # clase de equivalencia; un equipo esta en el bus si sus A y B caen en
        # dos redes distintas que comparte con alguien mas.
        padre = {p: p for p in PUERTOS if PUERTOS[p] == "borne"}

        def raiz(x):
            while padre[x] != x:
                padre[x] = padre[padre[x]]
                x = padre[x]
            return x

        for c in self.cables.values():
            if PUERTOS.get(c["a"]) == "borne":
                padre[raiz(c["a"])] = raiz(c["b"])
        nodos = {n: (raiz(n + ".485A"), raiz(n + ".485B")) for n in EQUIPOS}
        nodos["usb485"] = (raiz("usb485.A"), raiz("usb485.B"))
        # Polaridad de referencia: la del primer par cableado que aparezca. Cada
        # bus (par de redes A/B con dos o mas equipos) va por su propio puerto
        # UDP, asi dos tableros sin cablear entre si no se oyen.
        ref = {}
        for n, (a, b) in nodos.items():
            if a == b:
                continue
            clave = frozenset((a, b))
            companeros = [m for m, ab in nodos.items() if m != n and frozenset(ab) == clave]
            if not companeros:
                continue
            ref.setdefault(clave, a)
        segmento = {c: PUERTO_485 + i for i, c in enumerate(sorted(ref, key=lambda c: sorted(c)))}
        nuevo = {}
        for n, (a, b) in nodos.items():
            clave = frozenset((a, b))
            if a != b and clave in ref:
                nuevo[n] = {"en_bus": True, "invertido": a != ref[clave], "puerto": segmento[clave]}
            else:
                nuevo[n] = {"en_bus": False, "invertido": False, "puerto": PUERTO_485}
            if a == b and self._otro_extremo(n + (".A" if n == "usb485" else ".485A")):
                nuevo[n]["corto"] = True     # A y B puenteados: el bus no funciona
        for n, st in nuevo.items():
            if st != self.bus.get(n):
                self.bus[n] = st
                if n in EQUIPOS:
                    self._orden_bus(n)
        self._repartir_lineas()
        self._guardar()

    # ── Capa fisica del RS-485: la linea serie de cada nodo ───────────────────
    def lineas(self) -> dict:
        """IP en tab_485 -> [baudios, formato, A/B cruzado] de cada nodo en un bus.
        Con esto cada receptor lee la onda con su propia UART (dispositivos/bus485.py)."""
        out = {}
        for n, eq in EQUIPOS.items():
            st = self.bus.get(n) or {}
            if st.get("en_bus"):
                linea = (self.equipos.get(n) or {}).get("linea485") or [19200, "8N1"]
                out[eq["ip485"]] = [int(linea[0]), str(linea[1]), bool(st.get("invertido"))]
        st = self._st_usb()
        if st.get("en_bus"):
            out[IP_485_PC] = [self.linea_pc[0], self.linea_pc[1], bool(st.get("invertido"))]
        return out

    def _orden_bus(self, n):
        st = self.bus.get(n) or {}
        self.orden(n, {"cmd": "bus", **{k: st[k] for k in ("en_bus", "invertido", "puerto")},
                       "ruido": self.ruido(st.get("puerto")), "lineas": self.lineas()})

    def ruido(self, puerto) -> float:
        """Probabilidad de trama danada en ese bus a 38 400 baudios por la terminacion
        (el receptor la escala con sus baudios: a 19 200 o menos, nada). La mide el 3D
        con el ohmetro de cada equipo (mensaje bus_electrico): ~60 ohm entre A y B es
        el bus bien terminado; sin terminar, un solo terminador o tres, hay errores."""
        peor = 0.0
        for n, st in self.bus.items():
            if not st.get("en_bus") or st.get("puerto") != puerto:
                continue
            rab = float((self.electrico.get(n) or {}).get("rab", 60.0))
            if rab > 1000:
                p = 0.15          # sin terminar
            elif rab > 80:
                p = 0.06          # falta un terminador
            elif rab < 45:
                p = 0.05          # sobra uno
            else:
                p = 0.0
            peor = max(peor, p)
        return peor

    def _repartir_lineas(self):
        ls = self.lineas()
        if ls != getattr(self, "_lineas_enviadas", None):
            self._lineas_enviadas = ls
            for n in EQUIPOS:
                if (self.bus.get(n) or {}).get("en_bus"):
                    self._orden_bus(n)
            self._usb_aviso_linea()

    def ip_deseada(self, nom):
        """IP que debe tener `nom` en la LAN: la que pidio su programa
        (Ethernet.begin / WiFi.config), una del pool DHCP si pidio DHCP, o la de
        fabrica."""
        if nom in ESTACIONES:
            return ESTACIONES[nom]["lan"]
        pedida = (self.equipos.get(nom) or {}).get("red_pedida") or {}
        ip = str(pedida.get("ip", ""))
        if ip == "dhcp":
            return PREFIJO_LAN + str(150 + sorted(EQUIPOS).index(nom))
        if ip.startswith(PREFIJO_LAN) and ip.count(".") == 3:
            return ip
        return EQUIPOS[nom]["lan"]

    def _wifi_on(self, nom):
        """WiFi asociada: la pidio el programa (WiFi.begin) o se encendio a mano
        (consola de las gafas o portal, para el programa de fabrica)."""
        if nom not in EQUIPOS or not EQUIPOS[nom]["wifi"]:
            return False
        pedida = ((self.equipos.get(nom) or {}).get("red_pedida") or {}).get("wifi")
        return bool(self.wifi.get(nom)) or bool(pedida)

    def _avisar_red(self, nom):
        """Le dice al equipo si tiene enlace por cable, por WiFi y con que IP
        (lo leen Ethernet.linkStatus(), WiFi.status() y localIP())."""
        if nom not in EQUIPOS:
            return
        st = {"cable": bool(self.cable.get(nom)) and bool(self.lan.get(nom)),
              "wifi": self._wifi_on(nom) and bool(self.lan.get(nom)),
              "ip": self.ip.get(nom, "") if self.lan.get(nom) else ""}
        if st != self.red_avisada.get(nom):
            self.orden(nom, {"cmd": "red", **st})
            self.red_avisada[nom] = st

    async def _red(self, nom, conectar, ip):
        c = (EQUIPOS.get(nom) or ESTACIONES[nom])["contenedor"]
        if conectar:
            # Una IP ya usada por otro equipo es un conflicto de verdad: no se
            # enchufa y se avisa (en planta, dos equipos con la misma IP se pisan).
            duenio = [n for n, i in self.ip.items() if i == ip and n != nom and self.lan.get(n)]
            if duenio:
                self.evento("CONFLICTO DE IP: %s pide %s, que ya usa %s" % (nom, ip, duenio[0]))
                return
            rc, out = await asyncio.to_thread(docker, "network", "connect", "--ip", ip, RED_LAN, c)
            ok = rc == 0 or "already exists" in out
        else:
            rc, out = await asyncio.to_thread(docker, "network", "disconnect", "-f", RED_LAN, c)
            ok = rc == 0 or "is not connected" in out
        if ok:
            self.lan[nom] = conectar
            if conectar:
                self.ip[nom] = ip
            else:
                self.ip.pop(nom, None)
            self.evento("%s %s la LAN (%s)" % (nom, "en" if conectar else "fuera de", ip))
            self._veth.pop(nom, None)
        else:
            self.evento("docker fallo con %s: %s" % (nom, out[-160:]))

    # ── Contadores de los puertos del switch ─────────────────────────────────
    async def _veth_de(self, nom):
        if nom in self._veth:
            return self._veth[nom]
        # El iflink de cada interfaz del contenedor es el ifindex de su veth en
        # el anfitrion; de esas veth, la que cuelga del puente tab-lan es el
        # puerto del switch.
        guion = "for i in /sys/class/net/*; do echo $(basename $i) $(cat $i/iflink); done"
        rc, out = await asyncio.to_thread(docker, "exec", (EQUIPOS.get(nom) or ESTACIONES[nom])["contenedor"],
                                          "sh", "-c", guion)
        if rc != 0:
            return None
        iflinks = {l.split()[1] for l in out.splitlines()
                   if len(l.split()) == 2 and l.split()[0] != "lo"}
        for dev in os.listdir("/sys/class/net"):
            try:
                with open("/sys/class/net/%s/ifindex" % dev) as f:
                    idx = f.read().strip()
                with open("/sys/class/net/%s/master/uevent" % dev) as f:
                    master = f.read()
            except OSError:
                continue
            if idx in iflinks and "INTERFACE=tab-lan" in master:
                self._veth[nom] = dev
                return dev
        return None

    async def _bucle_contadores(self):
        while True:
            puertos = {}
            for nom in EQUIPOS:
                if not self.lan.get(nom):
                    continue
                p = self._otro_extremo(nom + ".eth")
                if self.pausado.get(nom):
                    continue
                dev = await self._veth_de(nom)
                if p is None or dev is None:
                    continue
                try:
                    with open("/sys/class/net/%s/statistics/tx_packets" % dev) as f:
                        tx = int(f.read())
                    with open("/sys/class/net/%s/statistics/rx_packets" % dev) as f:
                        rx = int(f.read())
                except OSError:
                    self._veth.pop(nom, None)
                    continue
                puertos[p] = {"link": True, "tx": tx, "rx": rx}
            self.puertos_sw = puertos
            await asyncio.sleep(0.1)

    # ── Segmentos: cada switch es su propia red ──────────────────────────────
    # En Docker todos los equipos cableados comparten tab_lan (una sola subred, el plan
    # de IP del curso). Pero dos tableros sin un latiguillo entre sus switches NO deben
    # verse: el Controllino T2 no se alcanza desde el tablero 1. Se hace en el puente:
    # en la veth de cada equipo cableado se descartan (tc flower, salida hacia el
    # contenedor) las tramas cuyo MAC de origen es de un equipo de OTRO segmento. Las MAC
    # salen de la tabla FDB del puente, asi que valen aunque el programa cambie la MAC.
    # (El kernel de Docker Desktop no tiene nftables para puentes; tc si.)
    def segmentos(self):
        """nombre -> segmento (el switch raiz) de cada equipo cableado a un switch con
        corriente. Dos switches unidos por un latiguillo switch-switch son un mismo
        segmento. Lo que va por WiFi o no pasa por un switch del tablero (broker, Node-RED,
        FUXA, servidores del alumno) no tiene segmento: lo ven todos, como el punto de
        acceso y la red del laboratorio."""
        padre = {"t%d.switch" % n: "t%d.switch" % n for n in range(1, N_TABLEROS + 1)}

        def raiz(x):
            while padre[x] != x:
                x = padre[x]
            return x
        for c in self.cables.values():
            if ".switch." in c["a"] and ".switch." in c["b"]:
                a, b = c["a"].rsplit(".", 1)[0], c["b"].rsplit(".", 1)[0]
                if a in padre and b in padre and self.encendido(a) and self.encendido(b):
                    padre[raiz(b)] = raiz(a)
        seg = {}
        for nom in list(EQUIPOS) + list(ESTACIONES):
            otro = self._otro_extremo(nom + ".eth")
            if self.cable.get(nom) and self.lan.get(nom) and otro:
                seg[nom] = raiz(otro.rsplit(".", 1)[0])
        return seg

    async def _bucle_segmentos(self):
        self._filtros = {}          # veth -> frozenset de MAC ajenas que se descartan
        while True:
            try:
                await self._aplicar_segmentos()
            except Exception as e:  # nunca tumbar la pasarela por esto
                self.evento("segmentos: %s" % e)
            await asyncio.sleep(1.0)

    async def _aplicar_segmentos(self):
        seg = self.segmentos()
        veth = {}
        for nom in seg:
            d = self._veth.get(nom) if self.pausado.get(nom) else await self._veth_de(nom)
            if d:
                veth[nom] = d
        r = await asyncio.to_thread(subprocess.run, ["bridge", "fdb", "show", "br", "tab-lan"],
                                    capture_output=True, text=True, timeout=10)
        mac_de = {}
        for l in r.stdout.splitlines():
            p = l.split()
            if len(p) >= 3 and p[1] == "dev" and "permanent" not in l and "self" not in p:
                mac_de.setdefault(p[2], set()).add(p[0].lower())
        quiere = {}
        for nom, d in veth.items():
            ajenas = set()
            for otro, d2 in veth.items():
                if seg[otro] != seg[nom]:
                    ajenas |= mac_de.get(d2, set())
            quiere[d] = frozenset(ajenas)

        def tc(*a):
            return subprocess.run(["tc", *a], capture_output=True, text=True, timeout=10)
        cambios = False
        for d in list(self._filtros):
            if not quiere.get(d):
                await asyncio.to_thread(tc, "qdisc", "del", "dev", d, "clsact")
                del self._filtros[d]
                cambios = True
        for d, macs in quiere.items():
            if not macs or self._filtros.get(d) == macs:
                continue
            await asyncio.to_thread(tc, "qdisc", "add", "dev", d, "clsact")      # si ya esta, falla y da igual
            await asyncio.to_thread(tc, "filter", "del", "dev", d, "egress")
            for m in sorted(macs):
                await asyncio.to_thread(tc, "filter", "add", "dev", d, "egress", "protocol", "all",
                                        "pref", "10", "flower", "src_mac", m, "action", "drop")
            self._filtros[d] = macs
            cambios = True
        if cambios:
            grupos = {}
            for nom, s in seg.items():
                grupos.setdefault(s, []).append(nom)
            self.evento("segmentos de red: " + " | ".join(
                "%s: %s" % (s.split(".")[0], ", ".join(sorted(v))) for s, v in sorted(grupos.items())))

    # ── Convivencia con ot-lab ────────────────────────────────────────────────
    # ot-lab (github.com/Pbarbecho/ot-lab) es el entorno de los talleres del mismo curso.
    # Si corre a la vez que el banco, sus contenedores reciben aqui, solos, una pata en el
    # segmento del banco (como servidores del laboratorio: ven los dos tableros), da igual
    # cual se levante primero. `lab.ps1 otlab quitar` lo desactiva (run/otlab_no).
    OTLAB = {"openplc": 200, "ignition": 201, "fuxa": 202, "node-red": 203, "mosquitto": 204,
             "modbus-sim": 205, "opcua-py": 206, "opc-plc": 207, "conpot": 208}

    async def _bucle_otlab(self):
        enchufados = set()
        while True:
            await asyncio.sleep(10)
            if os.path.exists(os.path.join(RUN, "otlab_no")):
                enchufados.clear()
                continue
            rc, out = await asyncio.to_thread(docker, "ps", "--filter", "label=com.docker.compose.project=ot-lab",
                                              "--format", "{{.Names}} {{.Networks}}")
            if rc != 0:
                continue
            for linea in out.splitlines():
                nombre, _, redes = linea.partition(" ")
                if nombre not in self.OTLAB or RED_LAN in redes.split(","):
                    continue
                ip = PREFIJO_LAN + str(self.OTLAB[nombre])
                rc2, _ = await asyncio.to_thread(docker, "network", "connect", "--ip", ip, RED_LAN, nombre)
                if rc2 == 0 and nombre not in enchufados:
                    enchufados.add(nombre)
                    self.evento("ot-lab: %s enchufado al banco (%s)" % (nombre, ip))

    # ── Canal con los equipos ─────────────────────────────────────────────────
    def _aplicar_carga(self, nivel: int):
        """Reparte el nivel de saturacion (0-100) a los equipos enchufados al switch."""
        self._carga_nivel = nivel
        for nom in EQUIPOS:
            if self.cable.get(nom):
                self.orden(nom, {"cmd": "carga", "nivel": nivel})

    def orden(self, nom, d):
        eq = EQUIPOS.get(nom)
        if eq:
            self._sock_orden.sendto(json.dumps(d).encode(), (eq["gestion"], PUERTO_ORDEN))

    class _ProtoEstado(asyncio.DatagramProtocol):
        def __init__(self, pas):
            self.pas = pas

        def datagram_received(self, data, addr):
            try:
                d = json.loads(data)
            except ValueError:
                return
            nom = d.get("equipo")
            if nom in EQUIPOS:
                antes = (self.pas.equipos.get(nom) or {}).get("red_pedida")
                self.pas.equipos[nom] = d
                self.pas.visto[nom] = time.time()
                # El programa pidio otra IP (o DHCP): se le reconecta con ella.
                if d.get("red_pedida") != antes:
                    asyncio.ensure_future(self.pas.aplicar())
                # Se reinicio y no sabe que red tiene: se le recuerda.
                if "red" in d and d.get("red") != self.pas.red_avisada.get(nom):
                    self.pas.red_avisada.pop(nom, None)
                    self.pas._avisar_red(nom)
                # Si el contenedor se reinicio, vuelve sin bus: se le recuerda.
                st = self.pas.bus.get(nom)
                claves = ("en_bus", "invertido", "puerto")
                if st is not None and {k: (d.get("bus") or {}).get(k) for k in claves} != {k: st[k] for k in claves}:
                    self.pas._orden_bus(nom)
                # EPC: si el equipo se reinicio (al subir un .ino) y vuelve sin saber que
                # esta cableado a X1, se le recuerda (guia L2).
                epc = self.pas.epc_estado.get(nom)
                if epc and not (d.get("epc") or {}).get("conectado"):
                    self.pas.orden(nom, {"cmd": "epc", "conectado": True})
                # Cambio de baudios o formato (Serial3.begin...): todos lo saben.
                self.pas._repartir_lineas()

    # ── Adaptador USB-RS485 del PC ────────────────────────────────────────────
    def _abrir_tty(self):
        maestro, esclavo = pty.openpty()
        tty.setraw(esclavo)
        attrs = termios.tcgetattr(esclavo)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(esclavo, termios.TCSANOW, attrs)
        os.set_blocking(maestro, False)
        nombre = os.ttyname(esclavo)
        try:
            os.remove(TTY_ENLACE)
        except OSError:
            pass
        os.symlink(nombre, TTY_ENLACE)
        self._tty_fd = maestro
        self._tty_esclavo = esclavo       # abierto para que el pty no se cierre
        self.evento("adaptador USB-RS485 en %s -> %s" % (TTY_ENLACE, nombre))

    async def _usb_atender(self, lector, escritor):
        """El /dev/ttyUSB0 del PC del alumno (contenedor tab-editor, openplc/usb485.py)
        llega aqui por TCP (172.30.99.1:4860), una linea por mensaje:
          PC -> pasarela   "L <baudios> <formato>"   la linea de su tty (stty, QModMaster...)
                           "T <hex>"                 una trama que acaba de salir al par
          pasarela -> PC   "P <cruzado 0/1> <ruido>" su polaridad en el bus y el ruido
                           "R <baud> <fmt> <cruzado> <hex>"  trama de otro nodo, con su linea
        El convertidor lee las tramas con su propia UART (bus485.py), como los equipos."""
        self._usb_clientes.add(escritor)
        self.evento("convertidor USB-RS485 del PC conectado (/dev/ttyUSB0)")
        self._usb_aviso_linea()
        try:
            while True:
                linea = await lector.readline()
                if not linea:
                    break
                partes = linea.decode(errors="replace").split()
                if len(partes) == 3 and partes[0] == "L":
                    self.linea_pc = [int(partes[1]), partes[2]]
                    self._repartir_lineas()
                elif len(partes) == 2 and partes[0] == "T":
                    self._a_bus_desde_pc(bytes.fromhex(partes[1]))
        except (ConnectionError, OSError, ValueError):
            pass
        self._usb_clientes.discard(escritor)
        escritor.close()

    def _usb_aviso_linea(self):
        st = self._st_usb()
        msg = ("P %d %.4f\n" % (1 if st.get("invertido") else 0, self.ruido(st.get("puerto")))).encode()
        for w in list(getattr(self, "_usb_clientes", ())):
            if not w.is_closing():
                w.write(msg)

    def _a_bus_desde_pc(self, t: bytes):
        st = self._st_usb()
        if t and st["en_bus"]:
            self._socks485[st["puerto"]].sendto(t, (BUS_485, st["puerto"]))

    def _st_usb(self):
        return self.bus.get("usb485", {"en_bus": False, "invertido": False, "puerto": PUERTO_485})

    def _tty_legible(self):
        # Lo que escribe QModMaster: se junta hasta un silencio de 3,5 caracteres
        # (a 19200 baud son ~2 ms; aqui se usa un margen mas holgado).
        try:
            datos = os.read(self._tty_fd, 512)
        except (BlockingIOError, OSError):
            return
        self._tty_buf = getattr(self, "_tty_buf", b"") + datos
        if getattr(self, "_tty_timer", None):
            self._tty_timer.cancel()
        self._tty_timer = asyncio.get_running_loop().call_later(0.015, self._tty_trama)

    def _tty_trama(self):
        # pty local (run/ttyTAB485, solo Linux): sin capa fisica, a 19200 8N1.
        t, self._tty_buf = self._tty_buf, b""
        self._a_bus_desde_pc(t)

    class _Proto485(asyncio.DatagramProtocol):
        def __init__(self, pas, puerto):
            self.pas = pas
            self.puerto = puerto

        def datagram_received(self, data, addr):
            self.pas.anotar_trama(tramas.rtu(data, addr[0], self.puerto - PUERTO_485))
            if addr[0] == IP_485_PC:
                return
            st = self.pas._st_usb()
            if not st["en_bus"] or st["puerto"] != self.puerto:
                return
            if self.pas._tty_fd is not None:
                try:
                    os.write(self.pas._tty_fd, data)
                except OSError:
                    pass
            baud, fmt, cruzado = (self.pas.lineas().get(addr[0]) or [19200, "8N1", False])[:3]
            msg = ("R %d %s %d %s\n" % (baud, fmt, 1 if cruzado else 0, data.hex())).encode()
            for w in list(self.pas._usb_clientes):
                if not w.is_closing():
                    w.write(msg)

    # ── Tramas para la pantalla del PC en las gafas ──────────────────────────
    def anotar_trama(self, d):
        if d:
            self._n_trama += 1
            d["n"] = self._n_trama
            d["campos"] = [[nom, tramas.hexa(b)] for nom, b in d.get("campos", [])]
            self.tramas.append(d)

    async def _bucle_captura(self):
        herr = os.path.join(RAIZ, "herramientas")
        # Dentro del contenedor tab-pasarela (Windows) ya se tiene la red de la
        # VM y NET_RAW: se captura aqui mismo. Lanzar otro contenedor con -v no
        # serviria, porque la ruta de herramientas/ es la de este contenedor y
        # no la que ve el demonio de Docker.
        local = os.environ.get("TAB_SNIFFER_LOCAL") == "1"
        while True:
            if not local:
                await asyncio.to_thread(docker, "rm", "-f", "tab-sniffer")
            try:
                if local:
                    orden = [sys.executable, "-u", os.path.join(herr, "sniffer.py"), "tab-lan", "-"]
                else:
                    orden = ["docker", "run", "--rm", "-i", "--name", "tab-sniffer", "--network", "host",
                             "--cap-add", "NET_RAW", "--cap-add", "NET_ADMIN", "-v", herr + ":/h:ro",
                             "python:3.12-slim", "python", "-u", "/h/sniffer.py", "tab-lan", "-"]
                proc = await asyncio.create_subprocess_exec(
                    *orden,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    stdin=asyncio.subprocess.DEVNULL)
            except OSError:
                await asyncio.sleep(5)
                continue
            self.evento("captura de tab-lan en marcha")
            lector = tramas.LectorPcap()
            while True:
                datos = await proc.stdout.read(65536)
                if not datos:
                    break
                for pkt in lector.meter(datos):
                    self.anotar_trama(tramas.ethernet(pkt))
            await proc.wait()
            await asyncio.sleep(3)

    # ── Gafas ─────────────────────────────────────────────────────────────────
    def foto(self):
        vivos = {n: time.time() - self.visto.get(n, 0) < 2.0 for n in EQUIPOS}
        return {
            "t": "estado",
            "equipos": {n: {**self.equipos.get(n, {}), "encendido": vivos[n],
                            "lan": bool(self.lan.get(n)) and bool(self.cable.get(n)),
                            "wifi": bool(self.lan.get(n)) and self._wifi_on(n),
                            "apagado": bool(self.pausado.get(n)),
                            "usb": str(self._otro_extremo(n + ".usb") or "").startswith("pc.usb"),
                            "ip": self.ip.get(n, "") if self.lan.get(n) else ""}
                        for n in EQUIPOS},
            "cables": self.cables,
            "switch": self.puertos_sw,
            "bus": self.bus,
            "energia": {"t%d.%s" % (n, e): self.energia.get("t%d.%s" % (n, e), True)
                        for n in range(1, N_TABLEROS + 1) for e in ENERGIA},
            "tty": TTY_ENLACE if self._tty_fd is not None else "",
            "eventos": self.eventos[-6:],
            "tramas": list(self.tramas)[-16:],
            "hmi": self.hmi,
            "hmi_toques": list(self.hmi_toques),
            # Quien escucha: las gafas entran por tab-puerta (172.30.99.5) o
            # por la WiFi; el panel del PC (panel/panel.py) por PANEL_IP.
            "gafas": sum(1 for w in self.clientes
                         if (w.get_extra_info("peername") or ("",))[0] != PANEL_IP),
        }

    async def mensaje(self, d, escritor):
        t = d.get("t")
        if t == "cable":
            cid, a, b = str(d.get("id")), d.get("a"), d.get("b")
            error = self.validar(a, b)
            if error:
                self.evento("cable rechazado %s-%s: %s" % (a, b, error))
                escritor.write((json.dumps({"t": "error", "id": cid, "txt": error}) + "\n").encode())
                return
            self.cables[cid] = {"a": a, "b": b, "color": d.get("color", "")}
            self.evento("cable %s: %s <-> %s" % (cid, a, b))
            await self.aplicar()
        elif t == "quitar":
            if self.cables.pop(str(d.get("id")), None):
                self.evento("cable %s retirado" % d.get("id"))
                await self.aplicar()
        elif t == "limpiar":
            self.cables.clear()
            self.evento("tablero descableado")
            await self.aplicar()
        elif t == "wifi":
            nom = d.get("equipo")
            if nom in EQUIPOS and EQUIPOS[nom]["wifi"]:
                self.wifi[nom] = bool(d.get("v"))
                self.evento("WiFi de %s %s" % (nom, "ENCENDIDA" if self.wifi[nom] else "apagada"))
                await self.aplicar()
        elif t == "energia":
            clave = str(d.get("id", ""))
            if clave.split(".")[-1] in ENERGIA:
                self.energia[clave] = bool(d.get("v"))
                self.evento("interruptor %s %s" % (clave, "ON" if d.get("v") else "OFF"))
                await self.aplicar()
        elif t == "hmi":
            # El panel publica la pantalla del alumno (o {} si no hay diseño cargado).
            n = str(d.get("n", ""))
            if n in ("1", "2"):
                self.hmi[n] = d.get("e") or {}
        elif t == "hmi_toque":
            # Toque en la HMI del 3D: se numera y se difunde; el panel lo aplica una vez.
            self._hmi_seq += 1
            self.hmi_toques.append({"seq": self._hmi_seq, "n": int(d.get("n", 1)),
                                    "widget": str(d.get("widget", ""))[:24], "ev": str(d.get("ev", "")),
                                    "v": d.get("v")})
        elif t == "orden":
            nom = d.get("equipo")
            o = d.get("orden", {})
            # El EPC (guia L2) lo cablea el 3D con una orden "epc"; la recordamos para
            # reenviarla si el equipo se reinicia (al subir un .ino), como hacemos con el bus.
            if o.get("cmd") == "epc" and nom in EQUIPOS:
                self.epc_estado[nom] = bool(o.get("conectado"))
            self.orden(nom, o)
        elif t == "saturar":
            # Taller U6, Parte III: el atacante satura el segmento. Como en el banco virtual
            # un flood no "ocupa el medio" de otros (Docker enruta por host), se modela como
            # un estado: todos los equipos de la LAN reciben el nivel de carga durante `seg`
            # segundos y su tiempo de ciclo se degrada. 0 = parar.
            nivel = max(0, min(100, int(d.get("nivel", 0))))
            seg = float(d.get("seg", 30))
            self._aplicar_carga(nivel)
            self.evento("saturacion del segmento al %d%% (%s)" % (nivel, "%.0f s" % seg if nivel else "parada"))
            if nivel and seg > 0:
                if getattr(self, "_t_satura", None):
                    self._t_satura.cancel()

                async def _fin():
                    await asyncio.sleep(seg)
                    self._aplicar_carga(0)
                    self.evento("saturacion terminada: la red se recupera")
                self._t_satura = asyncio.ensure_future(_fin())
        elif t == "bus_electrico":
            # Medidas del 3D (resistencia y tension de reposo entre A y B de cada equipo)
            if isinstance(d.get("equipos"), dict) and d["equipos"] != self.electrico:
                self.electrico = d["equipos"]
                self._lineas_enviadas = None        # fuerza el reparto con el ruido nuevo
                self._repartir_lineas()

    async def _atender(self, lector, escritor):
        quien = escritor.get_extra_info("peername")
        que = "panel del PC" if quien[0] == PANEL_IP else "gafas"
        self.evento("%s conectadas desde %s" % (que, quien[0]) if que == "gafas" else "panel del PC conectado")
        self.clientes.add(escritor)
        try:
            while True:
                linea = await lector.readline()
                if not linea:
                    break
                try:
                    await self.mensaje(json.loads(linea), escritor)
                except (ValueError, KeyError, TypeError) as e:
                    self.evento("mensaje malo: %s" % e)
        except (ConnectionError, OSError):
            pass
        self.clientes.discard(escritor)
        escritor.close()
        self.evento("gafas desconectadas (%s)" % quien[0] if que == "gafas" else "panel del PC desconectado")

    async def _bucle_difusion(self):
        while True:
            linea = (json.dumps(self.foto()) + "\n").encode()
            for w in list(self.clientes):
                if w.is_closing():
                    self.clientes.discard(w)
                    continue
                # Si unas gafas no leen, no se les acumula estado sin fin.
                if w.transport.get_write_buffer_size() < 256 * 1024:
                    w.write(linea)
            await asyncio.sleep(0.1)

    @staticmethod
    def _difusiones():
        try:
            r = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            return []
        out = []
        for linea in r.stdout.splitlines():
            p = linea.split()
            if len(p) > 5 and "brd" in p and not p[1].startswith(("tab-", "docker", "br-", "veth", "lxc")):
                out.append(p[p.index("brd") + 1])
        return out

    async def _baliza(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        msg = json.dumps({"t": "tablero", "puerto": PUERTO_GAFAS}).encode()
        while True:
            # 255.255.255.255 solo sale por la ruta por defecto: si el PC esta
            # por cable y las gafas por WiFi, no les llegaria. Se anuncia en la
            # direccion de difusion de cada interfaz (salvo las del tablero).
            for dest in ["255.255.255.255"] + self._difusiones():
                try:
                    s.sendto(msg, (dest, PUERTO_BALIZA))
                except OSError:
                    pass
            await asyncio.sleep(1.0)

    async def _sincronizar(self, avisar=True):
        """Se parte de lo que dice docker y se corrige hacia el cableado
        guardado. Hace falta al arrancar y tambien despues: un `docker compose
        up` que recrea un contenedor lo deja sin los cables puestos a mano."""
        for nom, eq in list(EQUIPOS.items()) + list(ESTACIONES.items()):
            rc, out = await asyncio.to_thread(
                docker, "inspect", "-f", "{{.State.Running}}|{{.State.Paused}}|{{json .NetworkSettings.Networks}}",
                eq["contenedor"])
            if rc != 0 or not out.startswith("true"):
                if avisar and nom in EQUIPOS:
                    self.evento("AVISO: %s no esta corriendo (docker compose up -d)" % eq["contenedor"])
                self.lan[nom] = self.pausado[nom] = None
                self.red_avisada.pop(nom, None)
                continue
            _, pausa, redes = out.split("|", 2)
            self.pausado[nom] = pausa.strip() == "true"
            redes = json.loads(redes)
            self.lan[nom] = RED_LAN in redes
            if self.lan[nom]:
                self.ip[nom] = (redes[RED_LAN] or {}).get("IPAddress", "") or self.ip.get(nom, "")
        await self.aplicar()

    async def _bucle_reconciliar(self):
        while True:
            await asyncio.sleep(3.0)
            await self._sincronizar(avisar=False)

    async def correr(self):
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(lambda: Pasarela._ProtoEstado(self),
                                            local_addr=("172.30.99.1", PUERTO_ESTADO))
        for puerto in range(PUERTO_485, PUERTO_485 + 10):   # un puerto por bus
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind(("0.0.0.0", puerto))
            await loop.create_datagram_endpoint(
                lambda p=puerto: Pasarela._Proto485(self, p), sock=s)
            self._socks485[puerto] = s
        self._abrir_tty()
        await asyncio.start_server(self._usb_atender, "172.30.99.1", 4860)
        loop.add_reader(self._tty_fd, self._tty_legible)
        await self._sincronizar()
        srv = await asyncio.start_server(self._atender, "0.0.0.0", PUERTO_GAFAS, reuse_address=True)
        self.evento("esperando a las gafas en el puerto %d" % PUERTO_GAFAS)
        for f in (self._bucle_difusion, self._bucle_contadores, self._baliza,
                  self._bucle_reconciliar, self._bucle_captura, self._bucle_segmentos, self._bucle_otlab):
            asyncio.ensure_future(f())
        async with srv:
            await srv.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(Pasarela().correr())
    except KeyboardInterrupt:
        sys.exit(0)
    except OSError as e:
        print("No se pudo arrancar la pasarela: %s" % e)
        print("¿Esta levantado el tablero?  cd tablero && docker compose up -d")
        sys.exit(1)
