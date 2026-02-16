@echo off
title Dashboard Status Check
color 0B

echo ========================================
echo   Dashboard Status Check
echo ========================================
echo.

:: Check if Python/Streamlit is running
tasklist /FI "IMAGENAME eq python.exe" 2>NUL | find /I /N "python.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [OK] Streamlit dashboard is RUNNING
    echo      Local: http://localhost:8501
) else (
    echo [X]  Streamlit dashboard is NOT running
)

echo.

:: Check if ngrok is running
tasklist /FI "IMAGENAME eq ngrok.exe" 2>NUL | find /I /N "ngrok.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [OK] ngrok tunnel is RUNNING
    echo      Check ngrok window for public URL
) else (
    echo [X]  ngrok is NOT running
)

echo.
echo ========================================
echo.
echo To start the dashboard: run start_dashboard.bat
echo.
pause
