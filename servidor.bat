@echo off
REM ============================================================
REM  UltraHub - arranque del servidor
REM ------------------------------------------------------------
REM  Esta PC es la UNICA que corre el servidor. Los demas (celu,
REM  otra compu) NO ejecutan nada: entran por el navegador a la
REM  direccion que aparece abajo. Asi todos usan la MISMA base.
REM ============================================================
cd /d "%~dp0"
title UltraHub - servidor

echo.
echo  ============================================
echo   UltraHub
echo  ============================================
echo.
echo   Esta PC: http://127.0.0.1:5000
echo.
echo   Desde el celular o la otra compu, en la misma red Wi-Fi:
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /c:"IPv4"') do echo      http://%%i:5000
echo.
echo   Para cortar el servidor: Ctrl+C, o cerra esta ventana.
echo  ============================================
echo.

python -m waitress --host=0.0.0.0 --port=5000 --call app:create_app

echo.
echo  El servidor se detuvo.
pause
