@echo off
rem Abre el panel de rendimiento en tu PC (http://localhost:8001).
cd /d "%~dp0"
start "" "%~dp0..\.venv\Scripts\pythonw.exe" local.py
timeout /t 2 >nul
start "" http://localhost:8001
