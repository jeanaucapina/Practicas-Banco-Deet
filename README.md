# Banco virtual de Informática Industrial · DEET (Universidad de Cuenca)

El tablero de comunicaciones del laboratorio, en tu PC: Controllino, ESP32 PLC, switch,
HMI, OpenPLC, Node-RED, ChirpStack, Odoo/MES y Wireshark corren en Docker y los usas desde
el navegador. Incluye el **portal de prácticas** (L0–L12, U2, U4, U6) con autocorrector.

## Instalar

1. Windows 10/11 con **Docker Desktop** (WSL 2) y **Git**. Disco libre: 20 GB.
2. En PowerShell:

```powershell
git clone https://github.com/jeanaucapina/Practicas-Banco-Deet banco
cd banco
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # una sola vez
.\lab.ps1 navegador
```

**¿Bajaste el ZIP de GitHub en vez de clonar?** Descomprímelo y haz doble clic en **`iniciar.cmd`** (o `.\iniciar.cmd` en PowerShell): evita el error de seguridad de PowerShell sin cambiar nada del sistema. Sirve igual que `lab.ps1 navegador`; con otra orden: `iniciar.cmd parar`.

Se abre **http://localhost:8090/lab**. La primera vez tarda (construye las imágenes);
después, menos de un minuto. Para apagarlo: `.\lab.ps1 parar`.

Requisitos, puertos, convivencia con ot-lab y problemas frecuentes:
[docs/INSTALACION.md](docs/INSTALACION.md).

## Actualizar

```powershell
git pull
.\lab.ps1 navegador
```

Ctrl+Shift+R en el navegador si el 3D no se actualiza.

## Espacio en disco

Las prácticas con servidor propio (L11 Odoo, L10 ChirpStack, FUXA…) bajan sus imágenes al
usarlas. En el portal, el desplegable **«Espacio en disco»** las baja por adelantado o las
suelta al terminar sin perder tus datos.
