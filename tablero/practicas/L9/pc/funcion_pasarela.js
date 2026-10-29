// Practica L9 - Listado L9.5: nodo function de la pasarela (3 salidas).
// Pegalo en un nodo «function» con 3 salidas, entre Modbus-Read (FC3, 8 registros) y los mqtt out.
// OJO banco: el ADC del ESP32 PLC 14 del banco es de 12 bits (0..4095), como dice la L7;
// la guia escala con 1023. Decide y justifica en el informe cual usas (FONDO).
const FONDO = 4095;
const R = msg.payload, GRUPO = "spBv1.0/Planta1", NODO = "PLC01";
const BANDA = 2.0;      // banda muerta en unidades de ingenieria (2 % de 100 C)
const LATIDO = 30000;   // refresco maximo en ms: el silencio no debe ser ambiguo
const T = 100.0 * R[0] / FONDO, ts = Date.now();
let ultimo = context.get("ultimo") || { v: null, t: 0 }, salidas = [null, null, null];
// --- Salida 1: variable de proceso por excepcion, con latido de refresco ---
const cambio = (ultimo.v === null) || (Math.abs(T - ultimo.v) >= BANDA);
if (cambio || (ts - ultimo.t) >= LATIDO) {
    context.set("ultimo", { v: T, t: ts });
    salidas[0] = { topic: GRUPO + "/DDATA/" + NODO + "/TT-101", qos: 0, retain: true,
        payload: JSON.stringify({ v: +T.toFixed(2), u: "C", t: ts, crudo: R[0],
            motivo: cambio ? "banda" : "latido" }) };
}
// --- Salida 2: estado de la salida digital, siempre por excepcion ---
if (R[1] !== (context.get("d0") ?? -1)) {
    context.set("d0", R[1]);
    salidas[1] = { topic: GRUPO + "/DDATA/" + NODO + "/YL-102", qos: 1, retain: true,
        payload: JSON.stringify({ v: R[1], u: "bool", t: ts }) };
}
// --- Salida 3: diagnostico del nodo de borde (contadores [2] y [3]) ---
salidas[2] = { topic: GRUPO + "/NDATA/" + NODO, qos: 0, retain: false,
    payload: JSON.stringify({ Rx_Count: R[2], Tx_Count: R[3], t: ts }) };
node.status({ fill: "green", shape: "dot", text: T.toFixed(1) + " C" });
return salidas;
