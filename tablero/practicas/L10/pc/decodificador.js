// Practica L10 - Listado L10.4: decodificador de subida (ChirpStack: Device profile ->
// Codec -> JavaScript functions; The Things Stack: Payload formatters -> Uplink).
// Trama de 9 B (Fig. L10.4): VER|A_T|A_N, TEMP (2 B), NIV (2 B), TS (4 B), big-endian.
function decodeUplink(input) {
  var b = input.bytes;
  if (b.length !== 9) { return { errors: ["longitud != 9 B"] }; }
  if (((b[0] >> 4) & 0x0F) !== 1) { return { errors: ["version no soportada"] }; }

  // (b[5] << 24) puede salir negativo en JavaScript: se fuerza sin signo.
  var ts = ((b[5] << 24) >>> 0) + (b[6] << 16) + (b[7] << 8) + b[8];

  return { data: {
    temperatura: ((b[1] << 8) | b[2]) / 10.0,     // decimas -> grados C
    nivel: ((b[3] << 8) | b[4]) / 10.0,           // decimas -> %
    alarma_temp: ((b[0] >> 3) & 0x01) === 1,
    alarma_nivel: ((b[0] >> 2) & 0x01) === 1,
    ts_nodo: ts,                                  // segundos Unix
    ts_iso: new Date(ts * 1000).toISOString()
  }};
}

function encodeDownlink(input) {
  return { fPort: 10, bytes: [] };                // sin bajada en esta practica
}
