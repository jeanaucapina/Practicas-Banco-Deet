# L11 · Pirámide CIM completa: del ERP al campo (ISA-95)

Hasta aquí las guías vivieron en los niveles bajos de la pirámide de automatización (campo, PLC, supervisión). En esta práctica **montas los dos niveles de arriba** —MES (nivel 3) y ERP (nivel 4)— sobre el **mismo banco** y cierras el lazo entero: una orden creada en el ERP baja hasta mover un actuador del PLC, y la producción real sube de vuelta como OEE.

```
  Nivel 4  ERP   ── Odoo (Fabricación/MRP)            "¿qué y cuánto fabricar?"
     │  orden de fabricación ↓        ↑ OEE, avance
  Nivel 3  MES   ── mes.py (ejecución + OEE)           "¿cómo va la orden ahora?"
     │  Modbus TCP ↓                  ↑ conteo de piezas
  Nivel 2  SCADA ── panel / Node-RED / FUXA            supervisión (guías L9)
     │
  Nivel 1  PLC   ── ESP32 PLC, Modbus TCP (L7)         lógica de control
     │
  Nivel 0  campo ── actuadores y sensores del tablero  el proceso físico
```

Qué es de verdad y qué se emula:

- **ERP.** Es **Odoo 17 Community real** en tu Docker, con el módulo **Fabricación** (MRP). Las órdenes de fabricación son reales; el MES las lee por la API JSON-RPC de Odoo.
- **MES.** Es un servicio propio (`mes.py`, Flask + SQLite + cliente Modbus). No hay ningún MES comercial escondido: es el mínimo honesto que ata ERP y PLC, para que se vea el mecanismo.
- **PLC.** Es el **ESP32 PLC de la L7** con su servidor Modbus TCP, sin tocar su programa. El MES usa su mapa de registros tal cual.

## Montaje

*Preparar el tablero* cablea el PC y el ESP32 PLC al switch, da energía al PLC y carga en él el ejemplo **`esp32plc_modbus_tcp`** (el servidor Modbus de la L7: la "línea de producción"). Mapa de registros (holding, de la L6/L7):

| Reg | Qué es | Uso en L11 |
|----:|--------|------------|
| 0 | entrada analógica I0.7 | — |
| 1 | realimentación del actuador 0 | — |
| 2 | contador de entrantes | — |
| **3** | **contador de salientes (transacciones servidas)** | **piezas producidas** |
| **4** | **actuador 0** | **1 = línea en marcha** |

El MES arranca la línea escribiendo `1` en el registro 4 y cuenta una pieza por cada transacción que el PLC sirve (registro 3). Es un modelo didáctico: lo importante es el **recorrido vertical** de la orden, no la física de la pieza.

## Niveles 3 y 4: tu pila CIM en Docker

*Preparar el tablero* deja en `~/trabajo/L11` (carpeta `tablero/run/pc/L11`):

- `docker-compose.yml`: Odoo 17 + PostgreSQL (nivel 4) y el MES (nivel 3), enchufados al segmento del banco (`tab_lan`): Odoo en **192.168.1.63**, MES en **192.168.1.62**.
- `mes.py`: el código del MES (lee Odoo, manda al PLC, calcula OEE).

«Preparar el tablero» **ya levanta esta pila** en segundo plano (la primera vez baja sus imágenes y puede tardar varios minutos). Los comandos de abajo sirven para reiniciarla, verla o bajarla.

```
cd tablero/run/pc/L11
docker compose -p l11 up -d        # Odoo tarda ~1 min la primera vez
```

- **ERP (Odoo):** http://localhost:8069
  1. En el primer arranque, crea la base de datos: **nombre `banco`**, correo `admin`, contraseña `admin` (son las que el MES espera; cámbialas en `docker-compose.yml` si quieres).
  2. Instala la app **Fabricación**.
  3. Crea un producto fabricable y una **orden de fabricación** (Fabricación → Órdenes de fabricación), con una cantidad (p. ej. 20). Confírmala.
- **MES:** http://localhost:8095 — el tablero muestra la orden en curso, piezas producidas / objetivo y el **OEE** en vivo.

Si Odoo aún no tiene ninguna orden confirmada (o lo dejas apagado), el MES trabaja con una **orden de demostración** `MO/DEMO` (objetivo 20) para que la parte baja de la pirámide se pueda probar igual. En cuanto creas la orden en Odoo, el MES la toma: fuerza el relevo con `GET /api/nueva_orden` o espera a que termine la demo.

## Ver la fabricación en el tablero

El MES no solo cuenta: también **muestra el avance** en las salidas del ESP32 PLC, que se ven en el 3D:

| Salida | Registro | Qué indica |
|---|---|---|
| REL-A | 4 | línea en marcha (se apaga al terminar la orden) |
| REL-B | 5 | la orden va al menos por **1/3** |
| Q0.2 | 6 | la orden va al menos por **2/3** |
| Q0.3 | 7 | **cinta**: gira mientras la orden está en curso |

Para verlo con carga real, cablea (opcional, no se evalúa): el **foco de 24 V** entre `RELA` de la bornera y `0V`, y el **motor** entre `Q3` y `GND` del ESP32 PLC. Con una orden en curso el foco se enciende y el motor gira; las salidas REL-B y Q0.2 se encienden al pasar 1/3 y 2/3; al terminar, foco y motor se apagan y las lámparas de avance quedan encendidas. Cada escritura de avance suma una transacción al contador del registro 3; el MES la descuenta para no contarla como pieza.

## Qué comprueba «Comprobar mi solución»

1. **Nivel 1** · el PLC de producción responde en `192.168.1.10:502`.
2. **Nivel 4** · Odoo está levantado y su web responde.
3. **Nivel 3** · el MES está levantado y sano (`/api/salud`).
4. **Integración vertical** · el MES ve al PLC por Modbus (lazo 3 ↔ 1 cerrado).
5. **Orden ejecutada** · la orden bajó al PLC y el MES cuenta producción real (`producidas ≥ 1`).
6. **Lazo hacia arriba** · el MES calcula y expone el **OEE** de la orden.

## Entregable

- Captura del tablero del MES con la orden avanzando y el OEE.
- En el PDF: el diagrama de la pirámide de **tu** banco con direcciones IP y protocolo en cada tramo (ERP↔MES por JSON-RPC/HTTP, MES↔PLC por Modbus TCP, PLC↔campo por E/S), y una frase por nivel de qué decisión toma.
- Reto: modifica `mes.py` para que el OEE incluya **disponibilidad** (fracción de tiempo con la línea en marcha) y **calidad** (descarta como rechazo 1 de cada N piezas), no solo rendimiento.

## Al terminar

```
docker compose -p l11 down         # baja Odoo, Postgres y el MES
```
