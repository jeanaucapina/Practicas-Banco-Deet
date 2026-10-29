# -*- coding: utf-8 -*-
"""Carga un programa .st (el que genera OpenPLC Editor con "Generar programa
para OpenPLC Runtime") como el boton "Upload program" de la web:

    python2 /openplc/cargar.py <nombre.st>     (ya copiado en st_files/)

Compila con el script de OpenPLC; si va bien lo registra como programa activo
(el contenedor se reinicia despues y arranca en RUN con el)."""
import os
import sqlite3
import subprocess
import sys
import time

WEB = '/root/OpenPLC_v3/webserver'
os.chdir(WEB)
nombre = sys.argv[1]
if subprocess.call(['bash', './scripts/compile_program.sh', nombre]) != 0:
    sys.exit(1)
db = sqlite3.connect('openplc.db')
db.execute('INSERT INTO Programs (Name, Description, File, Date_upload) VALUES (?, ?, ?, ?)',
           (nombre[:-3], 'subido con lab.ps1', nombre, int(time.time())))
db.commit()
db.close()
