@echo off
REM Auto-restarting ingestion script for weekend runs
REM This will keep restarting the ingestion if it fails due to network issues

:loop
echo.
echo ========================================
echo Starting ingestion at %date% %time%
echo ========================================
echo.

cd /d "c:\Users\ktosh\Desktop\bot"
python -m scripts.ingest --months=6 >> ingestion_weekend.log 2>&1

echo.
echo ========================================
echo Ingestion stopped at %date% %time%
echo Waiting 300 seconds before restart...
echo ========================================
echo.

timeout /t 300 /nobreak

goto loop
