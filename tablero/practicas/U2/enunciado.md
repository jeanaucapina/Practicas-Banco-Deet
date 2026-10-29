# U2 · Taller: el modelo OSI y el acceso al medio

Es un taller de papel y lápiz, en grupos, como dice la guía (enlace arriba). Las tablas U2.3–U2.5 y las conclusiones van en la hoja del grupo. El banco sirve para dos cosas: **ver** las tramas que se mapean y **medir** lo que se calcula. *Comprobar mi solución* revisa las cifras del Ejercicio 2 y del análisis.

*Preparar el tablero* hace tres cosas:

- cablea el **USB-RS485 del PC** al bus del Controllino 1, que con su programa de fábrica es el esclavo 1 a 19 200 baudios 8N1;
- deja en `~/trabajo/U2` (carpeta `tablero/run/pc/U2`) la hoja `respuestas.txt`;
- deja también `medir_fc3.py`.

## Ejercicio 1 · El mapa OSI de una trama real (con captura propia)

Captura la transacción del Enunciado B:

1. Abre Wireshark en vivo sobre la red **RS-485** (`tab-485`). Usa *Decode As → UDP 4850 → mbrtu*.
2. En la terminal del PC, lanza:

   ```
   mbpoll -m rtu -b 19200 -P none -a 1 -t 4 -0 -r 0 -c 8 -1 /dev/ttyUSB0
   ```

3. Verás la consulta `01 03 00 00 00 08 44 0C` y la respuesta de 21 B.

El silencio t3,5 no viaja en ningún byte. Es el hueco entre tramas, y la captura lo muestra como el tiempo entre los dos paquetes.

Para el Enunciado A, carga `controllino_trama_maestro` y `esp32plc_trama_esclavo` (los ejemplos de L3) y captura igual. La trama `AA | DIR | CMD | LEN | DATOS | CRC16` sale tal cual. Con *Decode As* en *data* se ve en crudo.

## Ejercicio 2 · El peor caso, calculado y medido

Calcula los tres escenarios con las Ec. (U2.1) y (U2.2). Luego mide el (a) en el bus:

```
cd ~/trabajo/U2
python3 medir_fc3.py --n 40
```

El script envía cuarenta FC3 reales y da tres cosas:

- el tiempo de cada transacción: mínimo, media y máximo;
- la parte teórica: Tcon + Tresp + 2 t3,5 = 18,75 ms;
- el Tproc que queda.

Compara la media con tu Ttrans. El esclavo del banco tarda en contestar unos pocos milisegundos, menos que los 5 ms conservadores del enunciado. Fíjate también en el máximo: la dispersión existe, pero está **acotada**.

Apunta en `respuestas.txt`:

- tus cifras: Tcon, Tresp, Ttrans, Tciclo, CAN, Tslot y las esperas máximas;
- `N_max`;
- la media medida.

## Ejercicio 3 · Direccionamiento: qué pasa si dos nodos comparten la dirección

Vívelo en el bus antes de llenar la fila RS-485 de la Tabla U2.5:

1. Cablea también el **Controllino 2** al mismo par (su programa de fábrica es el esclavo **2**).
2. Carga en el ESP32 1 el ejemplo `esp32plc_esclavo_averia`, que también contesta como **2**, y cablea sus A y B al bus.
3. Lanza `python3 medir_fc3.py --esclavo 2`.

Los dos contestan a la vez y las respuestas colisionan en el par: CRC mal o basura. Nadie lo detecta como «dirección duplicada»: el maestro solo ve tramas rotas.

Contrasta con la red IP. En la LAN del banco, la pasarela se niega a enchufar un segundo equipo con una IP ya usada y avisa del **conflicto**: es lo que en la planta delata el ARP.

> Un bus RS-485 sin maestro también colisiona. Con el ESP32 haciendo de maestro (`esp32plc_maestro_rtu`) y `mbpoll` preguntando a la vez desde el PC, las tramas se pisan. Es el acceso **sin** arbitraje: el problema que el sondeo resuelve.

> **Comprobar mi solución** mira dos cosas:
> - que el PC lea el esclavo 1 por el USB-RS485;
> - que en `respuestas.txt` estén, dentro del margen de redondeo, Tcon, Tresp, Ttrans y Tciclo de la Ec. (U2.1), N_max, la Ttrans medida (18–35 ms), el tiempo de trama CAN y su peor caso, Tslot y las esperas máximas tras 1, 5 y 10 colisiones.
>
> Las tablas de texto y la defensa del relator las evalúa el docente.
