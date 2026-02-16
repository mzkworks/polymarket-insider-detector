@echo off
title Stop Dashboard
color 0C

echo ========================================
echo   Stopping Dashboard...
echo ========================================
echo.

:: Kill Streamlit
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *streamlit*" > nul 2>&1
if "%ERRORLEVEL%"=="0" (
    echo [OK] Stopped Streamlit dashboard
) else (
    echo [i]  Streamlit was not running
)

:: Kill ngrok
taskkill /F /IM ngrok.exe > nul 2>&1
if "%ERRORLEVEL%"=="0" (
    echo [OK] Stopped ngrok tunnel
) else (
    echo [i]  ngrok was not running
)

echo.
echo ========================================
echo   Dashboard stopped successfully!
echo ========================================
echo.
timeout /t 3 /nobreak > nul
