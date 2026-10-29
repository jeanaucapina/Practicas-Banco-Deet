#!/usr/bin/env python3
"""L15 · Control ON/OFF con histeresis por OPC UA (plantilla del alumno).

El «proceso» es el potenciometro del tablero (I0.7, 0-1023: lo mueves en el 3D). El
controlador es este script, que corre en TU computador y habla con el tablero SOLO por OPC UA:

    pot > 700  ->  cierra el rele A (REL-A)      (alarma / ventilador encendido)
    pot < 500  ->  lo abre                       (entre 500 y 700 mantiene el estado: histeresis)

A diferencia del termostato de la L14 (que PREGUNTA cada segundo) aqui te SUSCRIBES: el
servidor te avisa solo cuando cambia el potenciometro.

    python control.py              # o:  docker compose -p l15 run --rm cliente python control.py
"""
import asyncio
import os

from asyncua import Client

URL = os.environ.get("OPCUA_URL", "opc.tcp://localhost:4841/banco/")

# Parte I (gemelo, NodeIds de TEXTO):  "ns=2;s=Tablero1.Potenciometro"
# Parte II (planta, NodeIds NUMERICOS): "ns=2;i=1011"       <- tendras que cambiarlos
NODO_POT = "ns=2;s=Tablero1.Potenciometro"
NODO_REMOTE = "ns=2;s=Tablero1.Remote"
NODO_RELA = "ns=2;s=Tablero1.RelA"
ON, OFF = 700, 500


class Aviso:
    """El servidor llama aqui cuando cambia un nodo suscrito; dejamos el valor en una cola."""

    def __init__(self):
        self.cola = asyncio.Queue()

    def datachange_notification(self, nodo, valor, datos):
        self.cola.put_nowait(valor)


async def main():
    async with Client(url=URL) as cliente:
        remoto = cliente.get_node(NODO_REMOTE)
        rele_a = cliente.get_node(NODO_RELA)
        await remoto.write_value(True)                   # control remoto activado

        aviso = Aviso()
        # TODO 1: crea la suscripcion (500 ms) y suscribete al nodo del potenciometro
        #   sub = await cliente.create_subscription(500, aviso)
        #   await sub.subscribe_data_change(cliente.get_node(NODO_POT))

        encendido = False
        while True:
            pot = await aviso.cola.get()
            # TODO 2: histeresis. Si pot > ON y no esta encendido -> escribe True en RelA;
            #         si pot < OFF y esta encendido -> escribe False. Entre OFF y ON no hagas nada.
            print(f"pot={pot}  RelA={'ON' if encendido else 'OFF'}")


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
