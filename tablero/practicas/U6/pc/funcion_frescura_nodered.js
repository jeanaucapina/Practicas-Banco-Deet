// Taller U6 - Parte II (Listado U6.5): nodo "function" de Node-RED que impone la frescura
// (Ec. U6.1) sobre el mando del rele, mapeado a SR 3.1 (integridad de la comunicacion) y
// SR 3.8 (integridad de la sesion: rechazo de repeticiones). Es la misma regla que
// frescura.py; va detras de un "mqtt in" suscrito a planta/actuador/# del broker endurecido
// y delante del unico nodo con permiso de escritura FC6 sobre el PLC.
//   msg.payload = { reg, val, seq, ts }   (seq contador monotono, ts epoch ms)
const DELTA = 5000;                                   // ventana de frescura: 5000 ms
let m = msg.payload;
let last = flow.get("ult_seq") || {};                 // ultimo seq aceptado por registro
let visto = last[m.reg] || 0;
let ahora = Date.now();

if (m.seq <= visto) {                                 // repeticion: se descarta
    node.warn("REPLAY descartado reg=" + m.reg + " seq=" + m.seq);
    return null;
}
if (Math.abs(ahora - m.ts) > DELTA) {                 // trama vieja reinyectada
    node.warn("CADUCADO descartado reg=" + m.reg + " dt=" + (ahora - m.ts));
    return null;
}
last[m.reg] = m.seq;                                  // se acepta y se recuerda (persistelo entre reinicios)
flow.set("ult_seq", last);
return msg;                                           // pasa a la escritura FC6 real
