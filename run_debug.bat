@echo off
:: Starts the standalone app with Flask's debug server (auto-reload, debugger).
:: For development only: use run.bat otherwise.
setlocal
cd /d "%~dp0"

echo "  ___          _          _____                                  "
echo " / _ \        | |        |  ___|                                 "
echo "/ /_\ \ _   _ | |_  ___  | |__ __  __ _ __   _ __  ___  ___  ___ "
echo "|  _  || | | || __|/ _ \ |  __|\ \/ /| '_ \ | '__|/ _ \/ __|/ __|"
echo "| | | || |_| || |_| (_) || |___ >  < | |_) || |  |  __/\__ \\__ \"
echo "\_| |_/ \__,_| \__|\___/ \____//_/\_\| .__/ |_|   \___||___/|___/"
echo "                                     | |                         "
echo "                                     |_|                         "
echo.

if not exist ".venv\Scripts\python.exe" (
    echo AutoExpress isn't installed yet. Run install.bat first.
    pause
    exit /b 1
)

:: The debugger allows running code from the browser, so only listen locally.
if not defined AUTOEXPRESS_HOST set AUTOEXPRESS_HOST=127.0.0.1
if not defined AUTOEXPRESS_PORT set AUTOEXPRESS_PORT=5000
".venv\Scripts\python.exe" -m flask --app autoexpress run --debug --host=%AUTOEXPRESS_HOST% --port=%AUTOEXPRESS_PORT%
