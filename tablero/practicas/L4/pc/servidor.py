# Practica L4 - Listado L4.4: servidor Modbus TCP con el mapa canonico de ocho registros.
import asyncio, random
from pymodbus.datastore import (ModbusSequentialDataBlock, ModbusSlaveContext,
                                ModbusServerContext)
from pymodbus.server import StartAsyncTcpServer

# Mapa canonico del curso: [0] A0 (0-1023) | [1] D0 | [2] contador de
# entrantes | [3] contador de salientes | [4]-[7] reles R0-R3
registros = ModbusSequentialDataBlock(0, [512, 1, 0, 0, 0, 0, 0, 0])
contexto = ModbusServerContext(slaves=ModbusSlaveContext(hr=registros, zero_mode=True), single=True)


async def simular_proceso():          # el valor analogico cambia con el tiempo
    # Nota del banco: el Listado L4.4 escribe getValues(3, 0, 1) / setValues(3, 0, ...),
    # que es la API del CONTEXTO (con codigo de funcion). Sobre el bloque de datos de
    # pymodbus 3.6.9 son (direccion, cantidad) y (direccion, valores): con la llamada
    # de la guia esta tarea muere con TypeError y [0] se queda fijo en 512.
    while True:
        v = registros.getValues(0, 1)[0] + random.randint(-25, 25)
        registros.setValues(0, [max(0, min(1023, v))])
        await asyncio.sleep(1.0)


async def main():
    asyncio.create_task(simular_proceso())
    print("servidor escuchando en 0.0.0.0:502", flush=True)
    await StartAsyncTcpServer(context=contexto, address=("0.0.0.0", 502))

asyncio.run(main())
