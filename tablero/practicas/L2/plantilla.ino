// Practica L2 - Parte II (Listado L2.1 de la guia): lectura del spin box de la HMI STONE
// y mando PWM del motor del EPC por D0 del puerto X1.
#include <Controllino.h>
#include <Stone_HMI_Define.h>
#include <Procesar_HMI.h>

const int PIN_MOTOR = CONTROLLINO_D0;     // D0 del puerto X1 (5 V) -> IN MOTOR DC
int duty = 0, pwm = 0;                    // consigna 0-100 % y valor aplicado 0-255

void setup() {
  Serial.begin(115200);                   // monitor serie por USB
  Serial2.begin(115200);                  // enlace RS-232 con el HMI: 115200 8N1
  Stone_HMI_Init();                       // inicializa la estructura hmi_msg
  pinMode(PIN_MOTOR, OUTPUT);
  analogWrite(PIN_MOTOR, 0);              // arranque seguro: motor detenido
}

void loop() {
  Uart_HMI_Data_Receive();                // vuelca la trama en hmi_msg
  int v = HMI_get_value("spin_box", "spin_box1");   // -1 si no hay dato nuevo
  if (v >= 0 && v <= 100) {
    duty = v;
    pwm = map(duty, 0, 100, 0, 255);      // 0-100 % -> 0-255 cuentas
    analogWrite(PIN_MOTOR, pwm);
    Serial.print("duty = "); Serial.print(duty);
    Serial.print(" % -> PWM = "); Serial.println(pwm);
  } else if (v != -1) { Serial.println("Valor fuera del rango 0-100"); }
  delay(10);                              // periodo de sondeo del HMI
}
