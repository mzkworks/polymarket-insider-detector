@echo off
REM Auto-refreshing progress monitor
REM Shows progress every 5 minutes with ingestion status
REM Press Ctrl+C to stop monitoring

cd /d "c:\Users\ktosh\Desktop\bot"

title Polymarket Ingestion Monitor

:loop
cls
echo.
echo ========================================
echo   POLYMARKET INGESTION MONITOR
echo ========================================
echo   Current Time: %date% %time%
echo ========================================
echo.

REM Check if ingestion is running by looking for python process
tasklist /FI "IMAGENAME eq python.exe" 2>NUL | find /I /N "python.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo Status: [RUNNING] Python process detected
) else (
    echo Status: [STOPPED] No Python process found
)

REM Check log file age if it exists
if exist "ingestion_weekend.log" (
    for %%A in (ingestion_weekend.log) do (
        echo Log file: %%~tA (%%~zA bytes^)
    )
) else (
    echo Log file: Not found
)

echo.
echo ----------------------------------------
echo DATABASE PROGRESS:
echo ----------------------------------------

python -c "from src.data.database import Database; db = Database(); import sqlite3; conn = sqlite3.connect(db.db_path); conn.row_factory = sqlite3.Row; completed = conn.execute('SELECT COUNT(*) FROM ingestion_state WHERE key LIKE \"market_%%_trades\"').fetchone()[0]; total_trades = conn.execute('SELECT COUNT(*) FROM trades').fetchone()[0]; markets_with_trades = conn.execute('SELECT COUNT(DISTINCT market_id) FROM trades').fetchone()[0]; remaining = 411546 - completed; print(f'Completed: {completed:,} / 411,546 ({completed/411546*100:.1f}%%)'); print(f'Remaining: {remaining:,} markets'); print(f''); print(f'Markets with trades: {markets_with_trades:,}'); print(f'Total trades: {total_trades:,}'); print(f'Avg trades/market: {total_trades/markets_with_trades:.1f}' if markets_with_trades > 0 else 'N/A'); conn.close()"

echo.
echo ========================================
echo Next refresh in 5 minutes (300 seconds)
echo Press Ctrl+C to stop monitoring
echo ========================================
echo.

REM Wait 5 minutes before next check
timeout /t 300 /nobreak >nul

goto loop
