# Taller U6 · Parte V — zonas, conductos y respuesta al compromiso (plantilla del grupo)

Rellena esto y llévalo al PDF. No lo lee el autocorrector; lo evalúa el docente.

## Diagrama de zonas y conductos (IEC 62443-3-2)

```
ZONA DE CAMPO — SL ?        ZONA DE CONTROL — SL ?        ZONA DE SUPERVISIÓN — SL ?
sensores, potenciómetro,    ESP32 PLC 14 (Modbus TCP      broker TLS 8883, Node-RED,
relé [4]                    192.168.1.10), switch (VLAN)  panel
         └── E/S ──────────────┘         └── conducto Modbus TCP ──┘   └── MQTT/TLS ──┘
conducto Modbus TCP: sólo FC3/FC6 del operador, con frescura (firewall entre control y supervisión)
conducto MQTT: cifrado (8883), autenticado y con ACL por rol
```

## Security Level objetivo por zona (justifica el atacante del que protege cada una)

| Zona | SL objetivo | Atacante del que protege | SL alcanzado hoy | Qué control falta |
|---|---|---|---|---|
| Campo | | | | |
| Control | | | | |
| Supervisión | | | | |

## Procedimiento ante «RTU/IED comprometido» (el ESP32 emite mandos)

Contención inmediata (y su FR):
1.
2.

Recuperación (y su FR):
1.
2.

Por qué la clave por dispositivo evita re-clavar toda la red:
