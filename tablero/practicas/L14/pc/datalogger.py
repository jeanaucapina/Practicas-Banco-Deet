#!/usr/bin/env python3
"""L14 · Datalogger OPC UA del tablero (Parte A) y termostato (reto).

Lee el potenciometro del ESP32 PLC (I0.7) a traves de tu servidor OPC UA y lo guarda en un
CSV cada segundo. Ejecutalo EN ESTA CARPETA (para que el CSV quede en ~/trabajo/L14):

    pip install asyncua                 # una vez, en tu Windows
    python datalogger.py                # o:  docker compose -p l14 run --rm cliente python datalogger.py

Con Ctrl+C se detiene. Deja el script corriendo mientras pulsas «Comprobar mi solucion».
"""
import asyncio
import csv
import datetime
import os

from asyncua import Client

# --- CONFIGURACION ---------------------------------------------------------------
URL = os.environ.get("OPCUA_URL", "opc.tcp://localhost:4841/banco/")
NODO_POT = "ns=2;i=1011"          # Potenciometro (mira su NodeId en UaExpert o en modelo.json)


async def main():
    print(f"Conectando a {URL} ...")
    async with Client(url=URL) as cliente:
        print("¡Conectado!")
        pot = cliente.get_node(NODO_POT)

        # TODO (reto, termostato): obten tambien los nodos Remote (ns=2;i=1010) y RelA (ns=2;i=1014)
        #   remoto = cliente.get_node("ns=2;i=1010")
        #   rele_a = cliente.get_node("ns=2;i=1014")
        #   await remoto.write_value(True)      # sin control remoto el servidor rechaza tus escrituras

        with open("datos_planta.csv", "w", newline="") as archivo:
            escritor = csv.writer(archivo)
            escritor.writerow(["Fecha", "Hora", "Valor_Potenciometro"])
            print("Capturando datos (Ctrl+C para detener)...")
            try:
                while True:
                    valor = await pot.read_value()
                    ahora = datetime.datetime.now()
                    escritor.writerow([ahora.strftime("%Y-%m-%d"), ahora.strftime("%H:%M:%S"), valor])
                    archivo.flush()          # sin esto el CSV se queda en memoria y nadie lo ve crecer
                    print(f"[{ahora:%H:%M:%S}] Dato guardado: {valor}")

                    # TODO (reto): si valor > 500 cierra RelA (write_value(True)); si no, abrelo (False)

                    await asyncio.sleep(1)
            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\nCaptura detenida.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
