@echo off
rem Pone a farmear el asistente y abre el visor (http://localhost:8000).
cd /d "%~dp0"
del "asistente\STOP" 2>nul
type nul > "asistente\ENABLED"
powershell -NoProfile -Command "if (-not (Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*vigilante.py*' })) { Start-Process '%~dp0.venv\Scripts\pythonw.exe' -ArgumentList '\"%~dp0vigilante.py\"' -WorkingDirectory '%~dp0' }"
echo Asistente activado. Abriendo el visor...
powershell -NoProfile -Command "for($i=0;$i -lt 45;$i++){ try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://localhost:8000/asistente | Out-Null; break } catch { Start-Sleep 1 } }"
start "" http://localhost:8000
