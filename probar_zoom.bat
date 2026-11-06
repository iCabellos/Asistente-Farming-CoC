@echo off
rem Comprueba el zoom out. Antes: asistente detenido, juego abierto en la aldea y zoom acercado.
cd /d "%~dp0asistente"
"..\.venv\Scripts\python.exe" probar_zoom.py
pause
