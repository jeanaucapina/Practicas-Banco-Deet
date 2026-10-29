(* Ejemplo para OpenPLC del tablero: cada pulsador del panel del Controllino
   enciende una fila de la matriz 3x3, y D18 es una marcha con
   enclavamiento (I16 marcha, I18 paro).
   Las E/S son las del Controllino del tablero por Modbus TCP (ver
   tablero/openplc/LEEME.md). En OpenPLC Editor esto mismo se dibuja en LD. *)
PROGRAM filas
  VAR
    I16 AT %IX102.0 : BOOL;
    I17 AT %IX102.1 : BOOL;
    I18 AT %IX102.2 : BOOL;
    D0 AT %QX100.0 : BOOL;
    D1 AT %QX100.1 : BOOL;
    D2 AT %QX100.2 : BOOL;
    D6 AT %QX100.6 : BOOL;
    D7 AT %QX100.7 : BOOL;
    D8 AT %QX101.0 : BOOL;
    D12 AT %QX101.4 : BOOL;
    D13 AT %QX101.5 : BOOL;
    D14 AT %QX101.6 : BOOL;
    D18 AT %QX102.2 : BOOL;
  END_VAR

  D0 := I16; D6 := I16; D12 := I16;
  D1 := I17; D7 := I17; D13 := I17;
  D2 := I18; D8 := I18; D14 := I18;
  (* Enclavamiento clasico: marcha I16, paro I18 *)
  D18 := (I16 OR D18) AND NOT I18;
END_PROGRAM


CONFIGURATION Config0
  RESOURCE Res0 ON PLC
    TASK task0(INTERVAL := T#20ms, PRIORITY := 0);
    PROGRAM instance0 WITH task0 : filas;
  END_RESOURCE
END_CONFIGURATION
