@echo off
rem Para el asistente de forma limpia (acaba lo que esta haciendo). El visor sigue abierto.
cd /d "%~dp0"
del "asistente\ENABLED" 2>nul
type nul > "asistente\STOP"
echo Asistente parado.
timeout /t 3 >nul
