<#
Laboratorio VR en Windows: todo lo que corre en Docker, en un solo sitio.

  .\lab.ps1 arrancar    tableros + broker + pasarela + puerta 7070; abre el 7070 en
                         el firewall y, si las gafas estan por USB, les pasa la IP del PC
  .\lab.ps1 navegador  lo mismo sin gafas: tablero 3D en el navegador (http://localhost:8091)
                         dentro del panel (http://localhost:8090); sin firewall ni adb
  .\lab.ps1 ventana    tablero 3D en VENTANA NATIVA (Godot de escritorio, GPU dedicada/Vulkan):
                         va mucho mas fluido que el navegador; el dashboard sigue en el navegador
  .\lab.ps1 solucion L13|L14|L15   (docente) pone la solucion de la practica de OPC UA y la ejecuta
  .\lab.ps1 clave-docente    cambia la clave del «Modo docente» del portal (soluciones)
  .\lab.ps1 otlab [quitar]   convivencia con ot-lab (github.com/Pbarbecho/ot-lab), automatica
                         (puertos sin choques; la pasarela enchufa sus contenedores al banco
                         en 192.168.1.200-208); esto lo fuerza al momento, quitar lo desactiva
  .\lab.ps1 web         exporta el tablero 3D web con Godot local a tablero\run\web (solo
                         docentes/desarrollo; el alumno usa la imagen o `navegador`)
  .\lab.ps1 wireshark [tab-lan|tab-wifi|tab-485]   abre Wireshark en este PC con la captura en
                         vivo de esa red del tablero (por defecto tab-lan). Lo mismo hace el
                         boton «Abrir Wireshark» del portal (esquema tablerolab://)
  .\lab.ps1 gafas       solo lo ultimo (tras cambiar de red o de IP), sin tocar Docker
  .\lab.ps1 subir <equipo> <archivo.ino>   compila tu .ino y lo carga en ese equipo
                         (t1.controllino, t2.controllino, t1.esp32plc, t2.esp32plc);
                         "fabrica" en vez del .ino vuelve al programa de fabrica
  .\lab.ps1 serie <equipo>   monitor serie de ese equipo (Ctrl+C para salir)
  .\lab.ps1 openplc [parar]  OpenPLC por tablero (programas LD/FBD/ST de OpenPLC Editor):
                         web http://localhost:8081 (T1) y :8082 (T2), usuario openplc/openplc
  .\lab.ps1 subir t1.openplc <programa.st>   carga un .st sin pasar por la web
  .\lab.ps1 scada [parar]    FUXA, SCADA/HMI web (alternativa al Node-RED de la L9):
                         http://localhost:1891, conectado al banco por Modbus TCP y MQTT
  .\lab.ps1 scada quitar    como parar, y suelta la imagen de FUXA (2,3 GB) hasta la proxima vez
  .\lab.ps1 compactar   (administrador) devuelve a C: el espacio de las imagenes que sueltas:
                         el disco virtual de Docker Desktop no se encoge solo
  .\lab.ps1 parar       apaga y BORRA los contenedores (no quedan consumiendo)
  .\lab.ps1 estado      que esta corriendo y cuanta memoria/CPU gasta
  .\lab.ps1 logs        registro de la pasarela en vivo (Ctrl+C para salir)
  .\lab.ps1 apk [preset] compila e instala el APK en las gafas por USB
                         presets: "Quest Win" (KukaLab, por defecto) | "Quest Tablero Win" |
                         "Quest Comunicaciones Win" (laboratorio De Lorenzo de AM)
                         Los Win llevan otro identificador (.win): las apps firmadas en el
                         PC Linux no se pueden actualizar desde aqui y conviven con estas.

Todo va en el proyecto de Compose "tablero": en Docker Desktop sale agrupado
con ese nombre. Si ves contenedores tab-* o tab-pasarela corriendo y no estas
usando el laboratorio, `.\lab.ps1 parar`.
#>
param([string]$accion = "estado", [string]$preset = "Quest Win", [string]$archivo = "")

# Continue: docker y adb escriben el progreso por stderr, y en PowerShell 5.1
# con "Stop" eso se toma como un error y corta el script.
$ErrorActionPreference = "Continue"
$raiz = $PSScriptRoot
$compose = @("compose", "-f", "$raiz\tablero\docker-compose.yml", "--profile", "pasarela")
$todos = $compose + @("--profile", "openplc", "--profile", "nodered", "--profile", "scada")  # para parar tambien OpenPLC, Node-RED y FUXA
$godot = "$env:LOCALAPPDATA\Godot463\Godot_v4.6.3-stable_win64_console.exe"

function Docker-Listo {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Docker Desktop no esta arrancado. Abrelo y repite." -ForegroundColor Yellow
        exit 1
    }
}

function Gafas {
    $l = (adb devices 2>$null) -match "`tdevice$"
    return [bool]$l
}

$paquetes = @("org.ucuenca.tablero.win", "org.ucuenca.tablero")
$regla = "Tablero DEET - pasarela 7070"

function IPs-PC {
    # Solo adaptadores fisicos conectados: fuera VirtualBox, WSL, Docker, Tailscale.
    $fis = (Get-NetAdapter -Physical | Where-Object Status -eq 'Up').ifIndex
    @((Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $fis -contains $_.InterfaceIndex -and $_.IPAddress -notmatch '^169\.254\.' }).IPAddress)
}

function Abrir-Firewall {
    # La WiFi del campus queda como red "Publica" y Windows bloquea todo lo
    # entrante: sin esta regla las gafas nunca llegan al 7070 por WiFi.
    if (Get-NetFirewallRule -DisplayName $regla -ErrorAction SilentlyContinue) { return }
    Write-Host "Abriendo el puerto 7070 en el firewall (Windows pedira permiso de administrador una sola vez)..." -ForegroundColor Yellow
    $cmd = "New-NetFirewallRule -DisplayName '$regla' -Direction Inbound -Protocol TCP -LocalPort 7070 " +
           "-Action Allow -Profile Any -RemoteAddress 10.0.0.0/8,192.168.0.0/16 | Out-Null"
    try { Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile", "-Command", $cmd }
    catch { Write-Host "Sin permiso: las gafas solo conectaran por USB." -ForegroundColor Yellow }
}

function Avisar-Gafas {
    # Por USB: adb reverse (127.0.0.1 en las gafas = este PC) y, para cuando se
    # desenchufe, las IPs actuales del PC dentro de la app (run-as: APK debug).
    if (-not (Gafas)) { return $false }
    adb reverse tcp:7070 tcp:7070 | Out-Null
    $lista = (@(IPs-PC) + "127.0.0.1") -join " "
    foreach ($p in $paquetes) {
        if (-not ((adb shell pm list packages $p) -match "package:$p$")) { continue }
        adb shell "run-as $p sh -c 'echo $lista > files/pasarela_pc.txt'"
    }
    return $true
}

function Ruta-Wireshark {
    foreach ($c in @("$env:ProgramFiles\Wireshark\Wireshark.exe", "${env:ProgramFiles(x86)}\Wireshark\Wireshark.exe")) {
        if (Test-Path $c) { return $c }
    }
    $r = (Get-ItemProperty "HKLM:\SOFTWARE\Wireshark" -ErrorAction SilentlyContinue).InstallDir
    if ($r -and (Test-Path "$r\Wireshark.exe")) { return "$r\Wireshark.exe" }
    return $null
}

function Registrar-Esquema {
    # tablerolab://wireshark/<red>: el navegador pide permiso y llama a
    # `lab.ps1 uri`. Va en HKCU (sin administrador) y solo se registra una vez.
    $k = "HKCU:\Software\Classes\tablerolab"
    $orden = "powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`" uri `"%1`""
    if ((Get-ItemProperty "$k\shell\open\command" -ErrorAction SilentlyContinue)."(default)" -eq $orden) { return }
    New-Item -Force $k | Out-Null
    Set-ItemProperty $k "(default)" "URL:Tablero DEET"
    Set-ItemProperty $k "URL Protocol" ""
    New-Item -Force "$k\shell\open\command" | Out-Null
    Set-ItemProperty "$k\shell\open\command" "(default)" $orden
}

function Web-Target {
    # El servicio "web" sirve el tablero 3D. Con un build local (tablero\run\web,
    # de `.\lab.ps1 web`) basta el servidor; sin el, Docker lo exporta dentro de
    # la imagen (primera vez: baja ~1 GB de plantillas de Godot y tarda).
    if (Test-Path "$raiz\tablero\run\web\index.html") { $env:TAB_WEB_TARGET = "servidor" }
    else {
        $env:TAB_WEB_TARGET = "completo"
        if (-not (docker image ls -q tablero-web)) {
            Write-Host "Primera vez: Docker exporta el tablero 3D web (descarga ~1 GB, unos minutos)..." -ForegroundColor Yellow
        }
    }
}

switch ($accion) {
    "arrancar" {
        Docker-Listo
        Registrar-Esquema
        Web-Target
        docker @compose up -d --build
        # El editor de escalera queda encendido; las CPUs de OpenPLC, creadas pero
        # paradas: se encienden desde el panel (o .\lab.ps1 openplc), porque
        # mandan en las salidas del Controllino.
        docker @todos create --build openplc1 openplc2 nodered 2>$null | Out-Null
        docker @todos up -d --build editor 2>$null | Out-Null     # el editor no toca el Controllino: siempre listo
        Abrir-Firewall
        if (Avisar-Gafas) {
            Write-Host "Gafas por USB: conectadas y con la IP actual del PC; ya puedes desenchufarlas." -ForegroundColor Green
        } else {
            Write-Host "Gafas sin USB: usaran la ultima IP que se les paso. Si el PC cambio de IP, enchufalas y ejecuta: .\lab.ps1 gafas" -ForegroundColor Yellow
        }
        $ips = (IPs-PC) -join ", "
        Write-Host ""
        Write-Host "  Pasarela para las gafas: puerto 7070 en $ips"
        Write-Host "  Modbus TCP (segmento del banco 192.168.1.0/24): ESP32 192.168.1.10:502 - Controllino 192.168.1.11 - PC 192.168.1.100"
        Write-Host "  MQTT: broker 192.168.1.50:1883 (solo dentro de Docker). LoRaWAN: pasarela 192.168.1.70 (guia L10)"
        Write-Host "  S7-1200 simulado (S7comm): 127.0.0.1:102 desde este PC, rack 0 slot 1 (192.168.1.40 en la LAN)"
        Write-Host "  Taller U6 (seguridad): atacante 192.168.1.101, terminal http://localhost:7682"
        Write-Host "  Tramas en vivo: en la pantalla del PC dentro de las gafas."
        Write-Host "  Panel del laboratorio (todo en una pagina): http://localhost:8090" -ForegroundColor Green
        Write-Host "  Para apagarlo todo:  .\lab.ps1 parar" -ForegroundColor Cyan
        Start-Process "http://localhost:8090"
    }
    "navegador" {
        Docker-Listo
        Registrar-Esquema
        Web-Target
        docker @compose up -d --build
        docker @todos create --build openplc1 openplc2 nodered 2>$null | Out-Null
        docker @todos up -d --build editor 2>$null | Out-Null
        Write-Host ""
        Write-Host "  Laboratorio en el navegador (3D + programar): http://localhost:8090/lab" -ForegroundColor Green
        Write-Host "  Panel tecnico:                                http://localhost:8090"
        Write-Host "  Tablero 3D solo:                              http://localhost:8091"
        Write-Host "  Para apagarlo todo:  .\lab.ps1 parar" -ForegroundColor Cyan
        Start-Process "http://localhost:8090/lab"
    }
    "ventana" {
        # Tablero 3D en una VENTANA NATIVA (Godot de escritorio), no en el navegador. Usa
        # Vulkan/Forward+ y la GPU dedicada directa: va mucho mas fluido que la version web
        # (WASM + WebGL). Se conecta a la MISMA pasarela Docker por TCP 7070 (como las gafas),
        # asi que los cables, las E/S y la captura son los mismos. El dashboard y lo demas
        # (portal, Odoo, MES, FUXA, Wireshark) siguen en el navegador en sus puertos.
        Docker-Listo
        $godot = "$env:LOCALAPPDATA\Godot463\Godot_v4.6.3-stable_win64_console.exe"
        if (-not (Test-Path $godot)) {
            Write-Host "No encuentro Godot 4.6.3 en $godot" -ForegroundColor Red; break
        }
        # Asegura que la puerta 7070 (socat) este publicada para el TCP nativo.
        docker @compose up -d puerta 2>$null | Out-Null
        Write-Host ""
        Write-Host "  Tablero 3D en ventana nativa (GPU dedicada, Vulkan). Cierra la ventana para salir." -ForegroundColor Green
        Write-Host "  El resto sigue en el navegador:  portal http://localhost:8090/lab  ·  MES :8095  ·  FUXA :1891  ·  Odoo :8069" -ForegroundColor Cyan
        # --rendering-method forward_plus: el proyecto trae "mobile" por defecto (pensado para
        # el Quest); en un PC con GPU dedicada Forward+ (Vulkan) va mas fino. --rendering-driver
        # vulkan por si el equipo arrancara en otro. Si el PC no soporta Vulkan, quita estos dos.
        & $godot --xr-mode off --rendering-method forward_plus --rendering-driver vulkan `
            --path "$raiz\godot" "res://scenes/TableroLab.tscn"
    }
    "wireshark" {
        Docker-Listo
        $red = if ($preset -in @("tab-lan", "tab-wifi", "tab-485")) { $preset } else { "tab-lan" }
        $ws = Ruta-Wireshark
        if (-not $ws) {
            Write-Host "Wireshark no esta instalado. Instalalo con:  winget install WiresharkFoundation.Wireshark" -ForegroundColor Yellow
            exit 1
        }
        # El pipe va por cmd: el de PowerShell 5.1 estropea los datos binarios.
        $filtro = "modbus || mqtt || s7comm || icmp"
        $extra = ""
        if ($red -eq "tab-485") { $filtro = "mbrtu || modbus"; $extra = "-d udp.port==4850-4859,mbrtu" }
        $dock = "docker run --rm -i --network host --cap-add NET_RAW --cap-add NET_ADMIN " +
                "-v `"$raiz\tablero\herramientas:/h:ro`" python:3.12-slim python -u /h/sniffer.py $red -"
        $linea = "$dock | `"$ws`" -k -i - $extra -Y `"$filtro`" -t ad"
        Start-Process cmd -ArgumentList "/c", "`"$linea`"" -WindowStyle Hidden
        Write-Host "Wireshark abierto con la captura en vivo de $red." -ForegroundColor Green
    }
    "uri" {
        # Llamado por el navegador con tablerolab://wireshark/<red>. Lista blanca:
        # nunca se ejecuta nada que venga en la URL.
        if ($preset -match '^tablerolab://wireshark/(tab-lan|tab-wifi|tab-485)/?$') {
            & $PSCommandPath wireshark $Matches[1]
        }
    }
    "web" {
        if (-not (Test-Path $godot)) { Write-Host "Falta Godot 4.6.3 en $godot" -ForegroundColor Red; exit 1 }
        New-Item -ItemType Directory -Force "$raiz\tablero\run\web" | Out-Null
        Remove-Item "$raiz\tablero\run\web\index.*" -ErrorAction SilentlyContinue
        & $godot --headless --xr-mode off --path "$raiz\godot" --export-release "Web Tablero" "$raiz\tablero\run\web\index.html"
        if (-not (Test-Path "$raiz\tablero\run\web\index.pck")) { Write-Host "La exportacion no genero el build web." -ForegroundColor Red; exit 1 }
        git -C $raiz checkout -- '*.import' 2>$null
        Write-Host "Build web en tablero\run\web (tab-web lo sirve en vivo: recarga la pagina con Ctrl+F5)." -ForegroundColor Green
    }
    "gafas" {
        # Solo lo de las gafas, sin tocar Docker: tras un cambio de IP del PC.
        Abrir-Firewall
        if (Avisar-Gafas) { Write-Host ("Gafas al dia: PC en " + ((IPs-PC) -join ", ")) -ForegroundColor Green }
        else { Write-Host "Enchufa las gafas por USB y acepta 'Permitir depuracion USB'." -ForegroundColor Yellow }
    }
    "subir" {
        # Como el boton "Subir" del Arduino IDE, pero al equipo virtual.
        $equipo = $preset
        if ($equipo -match '^t([12])\.openplc$') {
            Docker-Listo
            $c = "tab" + $Matches[1] + "-openplc"
            if (-not ($archivo -and (Test-Path $archivo) -and $archivo -like "*.st")) {
                Write-Host "Uso: .\lab.ps1 subir $equipo C:\ruta\programa.st  (OpenPLC Editor > Generar programa para OpenPLC Runtime)" -ForegroundColor Yellow; exit 1
            }
            $st = Get-Item $archivo
            $nombre = ($st.BaseName -replace '[^A-Za-z0-9_]', '_') + ".st"
            docker cp $st.FullName "${c}:/root/OpenPLC_v3/webserver/st_files/$nombre"
            Write-Host "Compilando $nombre en OpenPLC..."
            docker exec $c python2 /openplc/cargar.py $nombre
            if ($LASTEXITCODE -ne 0) { Write-Host "No compila: revisa los errores de arriba." -ForegroundColor Red; exit 1 }
            docker restart $c | Out-Null
            Write-Host "Cargado: OpenPLC del tablero $($Matches[1]) en RUN con $nombre" -ForegroundColor Green
            break
        }
        if ($equipo -notmatch '^t[12]\.(controllino|esp32plc)$') {
            Write-Host "Equipo: t1.controllino | t2.controllino | t1.esp32plc | t2.esp32plc" -ForegroundColor Yellow; exit 1
        }
        Docker-Listo
        $c = "tab" + $equipo.Substring(1, 1) + "-" + $equipo.Split('.')[1]
        $dir = "$raiz\tablero\programas\$equipo"
        if ($archivo -eq "fabrica") {
            Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
            docker restart $c | Out-Null
            Write-Host "$equipo vuelve al programa de fabrica." -ForegroundColor Green
            break
        }
        if (-not ($archivo -and (Test-Path $archivo) -and $archivo -like "*.ino")) {
            Write-Host "Uso: .\lab.ps1 subir $equipo C:\ruta\practica\practica.ino" -ForegroundColor Yellow; exit 1
        }
        $ino = Get-Item $archivo
        # El .ino y lo que tenga al lado (.h/.cpp), como una carpeta de sketch.
        Remove-Item -Recurse -Force "$dir\fuente" -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force "$dir\fuente" | Out-Null
        Copy-Item $ino.FullName "$dir\fuente\"
        Get-ChildItem $ino.DirectoryName -File | Where-Object { $_.Extension -in ".h", ".hpp", ".cpp", ".c" } |
            Copy-Item -Destination "$dir\fuente\"
        Write-Host "Compilando $($ino.Name) para $equipo..."
        docker exec $c python compilar.py
        if ($LASTEXITCODE -ne 0) {
            Write-Host "No compila: corrige los errores de arriba. El equipo sigue con el programa anterior." -ForegroundColor Red
            exit 1
        }
        docker restart $c | Out-Null
        Write-Host "Subido: $equipo corre $($ino.Name). Monitor serie: .\lab.ps1 serie $equipo" -ForegroundColor Green
    }
    "openplc" {
        Docker-Listo
        if ($preset -eq "parar") {
            docker @todos stop openplc1 openplc2 editor | Out-Null
            Write-Host "OpenPLC parado: el Controllino vuelve a mandar solo." -ForegroundColor Green
            break
        }
        docker @todos up -d --build openplc1 openplc2 editor
        Write-Host ""
        Write-Host "  Editor grafico (escalera/bloques) en el navegador: http://localhost:6080  - o desde el panel http://localhost:8090" -ForegroundColor Green
        Write-Host "  OpenPLC tablero 1: http://localhost:8081   tablero 2: http://localhost:8082  (openplc / openplc)"
        Write-Host "  E/S = el Controllino de cada tablero por Modbus TCP: enchufalo al switch en las gafas y deja su HMI en ESCLAVO."
        Write-Host "  Mapa de E/S y ejemplo: tablero\openplc\LEEME.md.  Para pararlo: .\lab.ps1 openplc parar" -ForegroundColor Cyan
    }
    "solucion" {
        # Docente: pone la SOLUCION de una practica de OPC UA (L13-L15) y la ejecuta, para ver como
        # funciona. Requiere haber pulsado «Preparar el tablero» de esa practica en el portal (y, para
        # el cableado, «Cablear solucion» del modo docente). Las soluciones no van en el paquete de alumnos.
        Docker-Listo
        $id = "$preset".ToUpper()
        $carpeta = "$raiz\tablero\practicas\$id\solucion"
        if ($id -notin @("L13", "L14", "L15") -or -not (Test-Path $carpeta)) {
            Write-Host "Uso: .\lab.ps1 solucion L13|L14|L15 [parar]   (solo en el banco del docente: tablero\practicas\<id>\solucion)" -ForegroundColor Yellow; break
        }
        $dest = "$raiz\tablero\run\pc\$id"
        $p = $id.ToLower()
        if ($archivo -eq "parar") {
            docker ps -aq --filter "name=$p-cliente" | ForEach-Object { docker rm -f $_ | Out-Null }
            $plantilla = "$raiz\tablero\practicas\$id\pc\modelo.json"
            if (Test-Path $plantilla) {       # el modelo vuelve a la plantilla del alumno
                Copy-Item $plantilla "$dest\modelo.json" -Force
                docker restart "$p-opcua" 2>$null | Out-Null
            }
            Write-Host "Solucion de $id detenida (y modelo.json devuelto a la plantilla del alumno)." -ForegroundColor Green; break
        }
        if (-not (Test-Path $dest)) { Write-Host "Primero pulsa «Preparar el tablero» de $id en el portal." -ForegroundColor Yellow; break }
        Copy-Item "$carpeta\*" $dest -Force
        if ($id -eq "L15") {      # Parte II de la L15: NodeIds numericos
            $txt = (Get-Content "$dest\modelo.json" -Raw -Encoding UTF8) -replace '"nodeid":\s*"texto"', '"nodeid": "numerico"'
            [IO.File]::WriteAllText("$dest\modelo.json", $txt, (New-Object System.Text.UTF8Encoding $false))   # sin BOM
        }
        docker ps -aq --filter "name=$p-cliente" | ForEach-Object { docker rm -f $_ | Out-Null }
        Push-Location $dest
        docker compose -p $p up -d 2>&1 | Out-Null
        docker restart "$p-opcua" | Out-Null            # recoge el modelo.json de la solucion
        Write-Host "Servidor OPC UA de $id arrancando (unos 40 s: instala asyncua la primera vez)..."
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep 3
            if ((docker logs "$p-opcua" 2>&1 | Select-String "Servidor OPC UA en")) { break }
        }
        if (-not (docker ps -q --filter "name=$p-opcua")) {
            Pop-Location
            Write-Host "El servidor OPC UA de $id no esta corriendo: docker logs $p-opcua" -ForegroundColor Red; break
        }
        if ($id -ne "L13") {
            $script = (Get-ChildItem $carpeta -Filter *.py | Select-Object -First 1).Name
            docker compose -p $p run --rm -d cliente python $script | Out-Null
            Write-Host "Ejecutando tu solucion ($script) en un contenedor. Ver su salida: docker logs (docker ps -q --filter name=$p-cliente)" -ForegroundColor Cyan
        }
        Pop-Location
        Write-Host ""
        Write-Host "  Listo: $id con la solucion puesta." -ForegroundColor Green
        Write-Host "  Mueve el potenciometro en el 3D (cableado con «Cablear solucion»): el rele A se cierra por encima de ~500 (L14) o de 700 y se abre por debajo de 500 (L15)."
        Write-Host "  UaExpert: opc.tcp://localhost:4841/banco/  ·  Para parar el script:  .\lab.ps1 solucion $id parar" -ForegroundColor Cyan
    }
    "clave-docente" {
        # Clave del modo docente del portal (ver y subir las soluciones). Solo se guarda su
        # SHA-256 en tablero\panel\clave_docente.sha256, que no va en el paquete de alumnos.
        $s = Read-Host "Nueva clave del docente" -AsSecureString
        $c = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
        if ($c.Length -lt 6) { Write-Host "Minimo 6 caracteres." -ForegroundColor Yellow; break }
        $h = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($c))).Replace("-", "").ToLower()
        [IO.File]::WriteAllText("$raiz\tablero\panel\clave_docente.sha256", "$h`n")
        Write-Host "Clave del docente cambiada. En el portal: boton «Modo docente»." -ForegroundColor Green
    }
    "otlab" {
        # Convivencia con ot-lab, el entorno de los talleres (github.com/Pbarbecho/ot-lab).
        # Es AUTOMATICA: los puertos del banco no chocan con los suyos (Node-RED 1890, FUXA
        # 1891, ChirpStack 8089) y la pasarela enchufa sola sus contenedores al segmento del
        # banco (.200-.208) en cuanto aparecen, se levante primero cual sea. Este comando lo
        # hace al momento; `quitar` los desenchufa y desactiva lo automatico (run\otlab_no).
        Docker-Listo
        $marca = "$raiz\tablero\run\otlab_no"
        $otlab = @(@("openplc", 200), @("ignition", 201), @("fuxa", 202), @("node-red", 203), @("mosquitto", 204),
                   @("modbus-sim", 205), @("opcua-py", 206), @("opc-plc", 207), @("conpot", 208))
        $hay = docker ps --filter "label=com.docker.compose.project=ot-lab" --format "{{.Names}}"
        if ($preset -eq "quitar") {
            New-Item -ItemType File -Force $marca | Out-Null
            foreach ($o in $otlab) { docker network disconnect -f tab_lan $o[0] 2>$null | Out-Null }
            Write-Host "ot-lab fuera del segmento del banco y sin enchufado automatico (sus contenedores siguen corriendo)." -ForegroundColor Green
            Write-Host "Para volver: .\lab.ps1 otlab" -ForegroundColor Cyan
            break
        }
        Remove-Item $marca -ErrorAction SilentlyContinue
        if (-not $hay) {
            Write-Host "Enchufado automatico activo: cuando levantes ot-lab (cd ot-lab; docker compose up -d) se une solo al banco." -ForegroundColor Green
            break
        }
        foreach ($o in $otlab) {
            $c = $o[0]; $ip = "192.168.1.$($o[1])"
            if ($hay -notcontains $c) { continue }
            docker network connect --ip $ip tab_lan $c 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { Write-Host "  $c -> $ip" } else { Write-Host "  $c ya estaba en el banco" }
        }
        Write-Host ""
        Write-Host "  ot-lab y el banco conviven. ot-lab: Node-RED :1880, FUXA :1881, Ignition :8088." -ForegroundColor Green
        Write-Host "  Banco: Node-RED :1890, FUXA :1891, ChirpStack :8089. Desde ot-lab se ve el broker 192.168.1.50 y los PLC."
        Write-Host "  L4: con ot-lab arriba crea planta_net en 172.27.0.0/24 (ver su enunciado)." -ForegroundColor Yellow
    }
    "scada" {
        Docker-Listo
        if ($preset -eq "parar") {
            docker @todos stop fuxa | Out-Null
            Write-Host "FUXA parado." -ForegroundColor Green
            break
        }
        if ($preset -eq "quitar") {          # suelta tambien la imagen (2,3 GB); tus proyectos de ./fuxa se conservan
            docker @todos rm -s -f fuxa | Out-Null
            $img = docker image ls frangoteam/fuxa -q
            if ($img) { docker rmi $img | Out-Null }
            Write-Host "FUXA quitado (contenedor e imagen). La proxima vez que lo pidas se vuelve a bajar." -ForegroundColor Green
            break
        }
        docker @todos up -d fuxa
        Write-Host ""
        Write-Host "  FUXA (SCADA/HMI web, alternativa al tablero de Node-RED de la L9): http://localhost:1891" -ForegroundColor Green
        Write-Host "  Conectores ya cableados al banco: Modbus TCP 192.168.1.10:502 (ESP32 PLC) y MQTT 192.168.1.50:1883 (broker)."
        Write-Host "  Guia: tablero\practicas\L9\enunciado.md (Parte B, FUXA).  Para pararlo: .\lab.ps1 scada parar" -ForegroundColor Cyan
    }
    "compactar" {
        # Docker Desktop NO devuelve a C: el espacio de las imagenes que sueltas: su disco virtual
        # (docker_data.vhdx) solo crece. Esto lo compacta. Pide PowerShell como administrador y
        # cierra Docker unos minutos.
        $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        $vhd = "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx"
        if (-not $admin) { Write-Host "Abre PowerShell como administrador y repite: .\lab.ps1 compactar" -ForegroundColor Yellow; break }
        if (-not (Test-Path $vhd)) { Write-Host "No encuentro $vhd (Docker Desktop con WSL 2)." -ForegroundColor Yellow; break }
        $antes = [math]::Round((Get-Item $vhd).Length / 1GB, 1)
        Write-Host "Disco de Docker: $antes GB. Cerrando Docker Desktop y WSL..."
        Get-Process "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force
        wsl --shutdown
        Start-Sleep 8
        $guion = Join-Path $env:TEMP "compactar_docker.txt"
        "select vdisk file=`"$vhd`"`r`nattach vdisk readonly`r`ncompact vdisk`r`ndetach vdisk`r`nexit" | Set-Content $guion -Encoding ascii
        diskpart /s $guion | Out-Null
        Remove-Item $guion -ErrorAction SilentlyContinue
        $despues = [math]::Round((Get-Item $vhd).Length / 1GB, 1)
        Write-Host "Listo: $antes GB -> $despues GB. Abre Docker Desktop de nuevo." -ForegroundColor Green
    }
    "serie" {
        $equipo = $preset
        $c = "tab" + $equipo.Substring(1, 1) + "-" + $equipo.Split('.')[1]
        docker logs -f --tail 30 $c
    }
    "parar" {
        Docker-Listo
        docker @todos down --remove-orphans
        docker rm -f tab-sniffer 2>$null | Out-Null
        if (Gafas) { adb reverse --remove tcp:7070 2>$null | Out-Null }
        Write-Host "Laboratorio apagado: no queda ningun contenedor del tablero." -ForegroundColor Green
    }
    "estado" {
        Docker-Listo
        docker @compose ps --format "table {{.Name}}\t{{.Status}}"
        $ids = docker @compose ps -q
        if ($ids) { docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" $ids }
        else { Write-Host "Nada corriendo." }
        Write-Host ("Gafas por USB: " + $(if (Gafas) { "autorizadas" } else { "no" }))
    }
    "logs" {
        docker logs -f --tail 50 tab-pasarela
    }
    "apk" {
        if (-not (Test-Path $godot)) { Write-Host "Falta Godot 4.6.3 en $godot" -ForegroundColor Red; exit 1 }
        New-Item -ItemType Directory -Force "$raiz\build" | Out-Null
        $nombre = ($preset -replace ' ', '_').ToLower() + ".apk"
        $apk = "$raiz\build\$nombre"
        Remove-Item $apk -ErrorAction SilentlyContinue
        # --xr-mode off: sin visor en el PC, OpenXR abre un dialogo modal.
        # Sin demonio de Gradle: el demonio hereda la salida de Godot y Godot se
        # quedaba esperandolo para siempre DESPUES de escribir el APK.
        $env:GRADLE_OPTS = "-Dorg.gradle.daemon=false"
        & $godot --headless --xr-mode off --path "$raiz\godot" --install-android-build-template --export-debug $preset $apk
        if (-not (Test-Path $apk)) { Write-Host "La exportacion no genero el APK." -ForegroundColor Red; exit 1 }
        # Importar en Windows deja los .import con CRLF: mismo contenido, ruido en git.
        git -C $raiz checkout -- '*.import' 2>$null
        Write-Host "APK: $apk"
        if (Gafas) { adb install -r $apk; Avisar-Gafas | Out-Null }
        else { Write-Host "Gafas no autorizadas: acepta 'Permitir depuracion USB' en el visor y ejecuta: adb install -r `"$apk`"" -ForegroundColor Yellow }
    }
    default { Get-Help $PSCommandPath }
}
