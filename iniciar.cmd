@echo off
rem Lanzador del banco: funciona aunque hayas bajado el ZIP de GitHub (sin Set-ExecutionPolicy ni Unblock-File).
rem   iniciar.cmd               = abre el laboratorio en el navegador
rem   iniciar.cmd parar|estado  = cualquier orden de lab.ps1
cd /d "%~dp0"
set ORDEN=%*
if "%ORDEN%"=="" set ORDEN=navegador
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0lab.ps1" %ORDEN%
if errorlevel 1 pause
