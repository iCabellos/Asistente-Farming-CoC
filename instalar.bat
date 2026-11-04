@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo.
echo ==========================================================
echo   COC ASISTENTE_DIR - INSTALACION (tarda 5-15 min la primera vez)
echo ==========================================================
echo.

rem ---------- 1. Python 3.12 ----------
set "PY="
where py >nul 2>nul && py -3.12 -V >nul 2>nul && set "PY=py -3.12"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (
  echo [1/5] Instalando Python 3.12...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
) else (
  echo [1/5] Python 3.12: OK
)

rem ---------- 2. Entorno y librerias ----------
echo [2/5] Preparando el entorno de Python...
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :error

rem ---------- 3. ADB (control del emulador) ----------
where adb >nul 2>nul
if errorlevel 1 (
  echo [3/5] Instalando ADB...
  winget install -e --id Google.PlatformTools --accept-package-agreements --accept-source-agreements
) else (
  echo [3/5] ADB: OK
)

rem ---------- 4. Ollama + modelo de vision ----------
set "OLL=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not exist "%OLL%" (
  echo [4/5] Instalando Ollama...
  winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
)
echo [4/5] Descargando el modelo de vision qwen2.5vl:7b (unos 6 GB)...
start "" /B "%OLL%" serve >nul 2>&1
timeout /t 5 >nul
"%OLL%" pull qwen2.5vl:7b || goto :error

rem ---------- 5. Configuracion y accesos directos ----------
if not exist "asistente\config.json" (
  copy /y "asistente\config.example.json" "asistente\config.json" >nul
  echo [5/5] Creado asistente\config.json: rellena tus cuentas ^(paso 4 del README^).
) else (
  echo [5/5] asistente\config.json ya existe: no lo toco.
)
powershell -NoProfile -Command "$s=New-Object -ComObject WScript.Shell; $d=[Environment]::GetFolderPath('Desktop'); foreach($n in 'Iniciar asistente','Detener asistente'){ $l=$s.CreateShortcut(\"$d\$n.lnk\"); $l.TargetPath=\"%~dp0$n.bat\"; $l.WorkingDirectory=\"%~dp0\"; $l.Save() }"
echo       Accesos directos "Iniciar asistente" y "Detener asistente" creados en el escritorio.

echo.
echo ==========================================================
echo   LISTO. Siguiente: paso 4 del README (rellenar config.json)
echo ==========================================================
pause
exit /b 0

:error
echo.
echo *** Algo ha fallado. Lee el mensaje de arriba y mira "Problemas frecuentes" en el README. ***
pause
exit /b 1
