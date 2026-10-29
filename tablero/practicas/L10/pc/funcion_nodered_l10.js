// Practica L10 - Listado L10.6: nodo function de Node-RED detras de un "mqtt in" (salida:
// objeto JSON) suscrito a  application/+/device/+/event/up  en el broker del laboratorio,
// 192.168.1.50. Con UNA salida hay que devolver [[m1, m2, m3, m4]] (los cuatro, en
// secuencia, por la misma salida) hacia un "mqtt out" sin tema fijo; el [m1, ..., m4] del
// listado de la guia reparte un mensaje por salida y exige configurar 4 salidas.
// Salida: los mismos topicos que ya consume el tablero de L9, mas la calidad del enlace.
let up = msg.payload;
let d = up.uplink_message ? up.uplink_message.decoded_payload    // TTS
                          : up.object;                           // ChirpStack
if (!d) { return null; }
let meta = up.uplink_message ? up.uplink_message.rx_metadata[0] : up.rxInfo[0];

return [[
  { topic: "planta/lorawan/temperatura", payload: d.temperatura },
  { topic: "planta/lorawan/nivel", payload: d.nivel },
  { topic: "planta/lorawan/alarma",
    payload: (d.alarma_temp || d.alarma_nivel) ? 1 : 0 },
  { topic: "planta/lorawan/calidad",
    payload: { rssi: meta.rssi, snr: meta.snr, medio: "LoRaWAN", ts_nodo: d.ts_iso } }
]];
