@echo off
rem Comprueba que el PC ve el emulador por ADB. Debe salir "127.0.0.1:5555  device".
adb connect 127.0.0.1:5555
adb devices
pause
