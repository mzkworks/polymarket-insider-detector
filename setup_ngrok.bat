@echo off
title ngrok First-Time Setup
color 0E

echo ========================================
echo   ngrok First-Time Setup
echo ========================================
echo.
echo If this is your FIRST TIME using ngrok, you need to:
echo   1. Sign up for a free account at https://ngrok.com/
echo   2. Get your authtoken from https://dashboard.ngrok.com/get-started/your-authtoken
echo   3. Run the command below with YOUR authtoken
echo.
echo ========================================
echo.
echo Do you already have an ngrok authtoken? (Y/N)
set /p HAS_TOKEN="> "

if /i "%HAS_TOKEN%"=="N" (
    echo.
    echo Opening ngrok signup page in your browser...
    start https://dashboard.ngrok.com/signup
    echo.
    echo After signing up:
    echo   1. Go to: https://dashboard.ngrok.com/get-started/your-authtoken
    echo   2. Copy your authtoken
    echo   3. Run this script again
    echo.
    pause
    exit /b
)

echo.
echo Enter your ngrok authtoken:
echo (It looks like: 2abc123def456...)
set /p AUTHTOKEN="> "

if "%AUTHTOKEN%"=="" (
    echo.
    echo [ERROR] No authtoken provided!
    timeout /t 3
    exit /b 1
)

echo.
echo Setting up ngrok with your authtoken...
C:\Users\ktosh\ngrok\ngrok.exe config add-authtoken %AUTHTOKEN%

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo   SUCCESS! ngrok is configured!
    echo ========================================
    echo.
    echo You can now run: start_dashboard.bat
    echo.
) else (
    echo.
    echo ========================================
    echo   FAILED - Check the error above
    echo ========================================
    echo.
    echo Make sure:
    echo   1. Your authtoken is correct
    echo   2. ngrok.exe is at: C:\Users\ktosh\ngrok\ngrok.exe
    echo.
)

pause
