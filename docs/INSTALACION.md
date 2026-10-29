# Instalación del banco virtual de Informática Industrial (alumnos)

El banco de comunicaciones del laboratorio DEET corre en **tu PC**, dentro de Docker. Lo usas desde el navegador: portal de prácticas, tablero 3D, autocorrector, Wireshark, Node-RED, el ERP/MES de la L11, etc. No hace falta Godot ni gafas.

## Requisitos

| | Mínimo | Recomendado |
|---|---|---|
| Sistema | Windows 10 22H2 o Windows 11, 64 bits | Windows 11 |
| Virtualización | activada en la BIOS/UEFI (VT-x / AMD-V) | |
| RAM | 8 GB (el banco usa ~1,5 GB) | **16 GB** (para la L11, que levanta Odoo, o para tener ot-lab a la vez) |
| Disco libre | **20 GB** (banco base, ~8 GB de imágenes; ver «Espacio en disco») | **30 GB** (con L10, L11, FUXA y ot-lab a la vez) |
| Gráfica | cualquiera, también integrada | dedicada (el 3D detecta la GPU y sube la calidad) |
| Red | Internet solo para la primera instalación (descarga de imágenes) | |
| Navegador | Chrome o Edge actualizados | |

Software:

1. **WSL 2** (lo instala Docker Desktop si falta). Desde PowerShell como administrador: `wsl --install`.
2. **Docker Desktop** para Windows (motor WSL 2). Probado con Docker 29.8 y WSL 2.7.
3. **Git** para Windows (para descargar y actualizar el banco).
4. *Opcional:* **Wireshark** (`winget install WiresharkFoundation.Wireshark`). El portal abre la captura en vivo con un botón.
5. *Opcional:* **Python 3.10+**, solo para las herramientas de línea de comandos.

## Instalación

```powershell
git clone <url del repositorio del curso> banco      # o descomprime el .zip que te den
cd banco
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # una sola vez: deja ejecutar lab.ps1
.\lab.ps1 navegador
```

La primera vez tarda (10 a 30 min según la red): construye las imágenes y exporta el 3D web. Las siguientes, menos de un minuto. Al terminar se abre **http://localhost:8090/lab**.

- **Elegir práctica:** desplegable «Práctica» → **Preparar el tablero** → resolver → **Comprobar mi solución**. Al preparar otra práctica, el portal **baja solo las pilas Docker** de las anteriores (Odoo, ChirpStack, tu servidor OPC UA…); tus datos y archivos se conservan.
- **Apagar todo** (libera RAM y CPU): `.\lab.ps1 parar`.
- **Ver qué corre:** `.\lab.ps1 estado`.
- **Si el 3D del navegador va lento** y tienes gráfica dedicada, está `.\lab.ps1 ventana`. Necesita Godot 4.6.3 en `%LOCALAPPDATA%\Godot463`; pregunta al docente.

## Espacio en disco: imágenes bajo demanda

El banco base ocupa unos 8 GB. Las prácticas con servidor propio traen **imágenes extra** que solo se bajan cuando las usas:

| Práctica | Extra | Tamaño |
|---|---|---|
| L11 | Odoo (ERP) + PostgreSQL | ~3,5 GB |
| FUXA (SCADA opcional, `.\lab.ps1 scada`) | FUXA | ~2,3 GB |
| L5 | herramientas de red emulada | ~0,9 GB |
| L10 | ChirpStack + PostgreSQL + Redis | ~0,6 GB |

En el portal, desplegable **«Espacio en disco»** (y una línea bajo cada práctica que lo necesita):

- **Descargar**: baja las imágenes antes de empezar (haz esto en casa o con buena red; Odoo son 1-2 GB comprimidos).
- **Liberar espacio**: para los contenedores de esa práctica y borra sus imágenes. **Tus datos se conservan** (base de Odoo, dispositivos de ChirpStack); la próxima vez se vuelven a bajar.
- **Limpiar caché de construcción**: residuo de la primera instalación (varios GB), sin efecto en nada que use el banco.

Desde la consola: `.\lab.ps1 scada quitar` suelta FUXA.

**Ojo, Windows:** Docker Desktop guarda todo en un disco virtual (`docker_data.vhdx`) que **solo crece**. Liberar imágenes deja ese espacio libre *dentro de Docker* (se reutiliza para la siguiente práctica, así que el disco virtual no pasa de lo que ocupen a la vez), pero **no lo devuelve a C:**. Para recuperarlo, PowerShell como administrador: `.\lab.ps1 compactar` (cierra Docker unos minutos).

## Puertos que usa en tu PC

Todos escuchan solo en tu PC (`127.0.0.1`), salvo el 7070 (gafas) y el 102 (S7).

| Puerto | Qué |
|---|---|
| 8090 | portal y panel del laboratorio |
| 8091 | tablero 3D |
| 7070 | pasarela (gafas Quest) |
| 6080, 7681, 7682 | escritorio, terminal del PC y terminal del atacante (U6) |
| 8081, 8082 | OpenPLC de cada tablero |
| 102 | S7-1200 simulado |
| 1890 | Node-RED del banco (L9) |
| 1891 | FUXA del banco (SCADA, opcional) |
| 1882 | tu Node-RED de la L9, si levantas su `docker compose` |
| 8089 | ChirpStack (L10, solo mientras lo levantas) |
| 8069, 8095 | Odoo y MES (L11, solo mientras los levantas) |
| 4841 | servidor OPC UA del banco (L13, L14 y L15, de a una; UaExpert: `opc.tcp://localhost:4841/banco/`) |

## Convivencia con ot-lab

Si tienes instalado **ot-lab**, el entorno de los talleres (github.com/Pbarbecho/ot-lab), los dos corren **a la vez y sin hacer nada**, levantes primero el que sea:

- **Los puertos no chocan.** ot-lab usa Node-RED 1880, FUXA 1881 e Ignition 8088; el banco usa Node-RED 1890, FUXA 1891 y ChirpStack 8089.
- **El banco enchufa solo a ot-lab en su segmento** (192.168.1.200–208) en cuanto lo ve. Desde el Node-RED, FUXA o Ignition de ot-lab se llega al broker del banco (192.168.1.50) y a los PLC (192.168.1.10/.11). Si el portal pide encender Node-RED con ot-lab arriba, abre el de ot-lab.
- **L4:** su red `planta_net` no puede usar 172.28.0.0/24, que es la de ot-lab. El enunciado explica cómo usar 172.27.0.0/24.
- `.\lab.ps1 otlab quitar` los separa y desactiva lo automático; `.\lab.ps1 otlab` lo vuelve a activar.

## Problemas frecuentes

- **«Docker no está arrancado»**: abre Docker Desktop y espera a que diga *Engine running*.
- **«Pool overlaps with other one on this address space»** (L4): ot-lab está corriendo. Ver arriba.
- **«port is already allocated»**: otro programa usa ese puerto (ver la tabla). En Windows, `netstat -ano | findstr :<puerto>` dice cuál.
- **El 3D no se actualiza tras una actualización del banco**: Ctrl+Shift+R en el navegador.
- **Docker ocupa mucho disco**: usa «Espacio en disco» del portal (arriba). `docker system prune` también borra lo que no se usa y no toca el banco, pero no devuelve el espacio a C: sin `.\lab.ps1 compactar`.
