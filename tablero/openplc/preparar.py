# -*- coding: utf-8 -*-
"""Arranque de OpenPLC en el tablero (corre con el python2 de la imagen
tuttas/openplc_v3, antes del webserver).

OpenPLC hace de CPU y el Controllino de su tablero de E/S remotas por Modbus
TCP (Slave Devices), como un PLC con periferia descentralizada:

  %IX100.0-%IX101.7  A0..A15 (como digitales)   %QX100.0-%QX102.7  D0..D23
  %IX102.0-%IX102.2  pulsadores I16..I18         %IW100-%IW115      A0..A15 (0-1023)
  %IX102.3-%IX102.4  IN0, IN1

Arranca en RUN con el ultimo programa cargado.
"""
import os
import sqlite3
import sys

WEB = '/root/OpenPLC_v3/webserver'
n = os.environ.get('TAB_TABLERO', '1')
ip = '192.168.1.1' + n
os.chdir(WEB)
sys.path.insert(0, WEB)

db = sqlite3.connect('openplc.db')
c = db.cursor()
c.execute('DELETE FROM Slave_dev')
c.execute('INSERT INTO Slave_dev (dev_name, dev_type, slave_id, com_port, baud_rate, parity, data_bits, '
          'stop_bits, ip_address, ip_port, di_start, di_size, coil_start, coil_size, ir_start, ir_size, '
          'hr_read_start, hr_read_size, hr_write_start, hr_write_size) '
          'VALUES (?, "TCP", ?, "", 115200, "None", 8, 1, ?, 502, 0, 21, 0, 24, 0, 16, 0, 0, 0, 0)',
          ('CONTROLLINO_T' + n, int(n), ip))
c.execute("UPDATE Settings SET Value = 'true' WHERE Key = 'Start_run_mode'")
db.commit()
db.close()

# baud_rate 115200 aunque sea TCP: esta version divide por los baudios en todos
# los dispositivos y con 0 el runtime muere (SIGFPE) nada mas arrancar.
import webserver   # solo para regenerar mbconfig.cfg con su propio formato
webserver.generate_mbconfig()
print('OpenPLC del tablero %s: E/S remotas = Controllino %s:502' % (n, ip))
