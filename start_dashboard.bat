@echo off
title Polymarket Insider Detector - Launcher
color 0A

echo ========================================
echo   Polymarket Insider Detector
echo   Starting Dashboard...
echo ========================================
echo.

:: Change to project directory
cd /d "%~dp0"

:: Start Streamlit in background
echo [1/3] Starting Streamlit dashboard...
start /B python -m streamlit run src/dashboard/app.py --server.address 0.0.0.0 > streamlit.log 2>&1

:: Wait for Streamlit to start
echo [2/3] Waiting for dashboard to initialize...
timeout /t 5 /nobreak > nul

:: Start ngrok in new window (keep window open even on error)
echo [3/3] Starting ngrok tunnel...
start "ngrok - Polymarket Dashboard" cmd /k "C:\Users\ktosh\ngrok\ngrok.exe http 8501"

:: Wait for ngrok to initialize
timeout /t 3 /nobreak > nul

echo.
echo ========================================
echo   DASHBOARD IS RUNNING!
echo ========================================
echo.
echo Local Access:
echo   http://localhost:8501
echo.
echo Remote Access:
echo   Check the ngrok window for the public URL
echo   It will look like: https://xxxx-xx-xx-xx-xx.ngrok.io
echo.
echo Password: polymarket2025
echo.
echo ========================================
echo.
echo Press any key to STOP the dashboard...
pause > nul

:: Cleanup - kill processes
echo.
echo Stopping dashboard...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *streamlit*" > nul 2>&1
taskkill /F /IM ngrok.exe > nul 2>&1

echo Dashboard stopped!
timeout /t 2 /nobreak > nul
