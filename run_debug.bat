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

:: Release zips bundle their own Python in runtime\; a source checkout uses .venv.
set "PYTHON=.venv\Scripts\python.exe"
if exist "runtime\python.exe" set "PYTHON=runtime\python.exe"
if not exist "%PYTHON%" (
    echo Emotica isn't installed yet. Run install.bat first.
    pause
    exit /b 1
)

:: The debugger allows running code from the browser, so only listen locally.
if not defined EMOTICA_HOST set EMOTICA_HOST=127.0.0.1
if not defined EMOTICA_PORT set EMOTICA_PORT=5000
"%PYTHON%" -m flask --app emotica run --debug --host=%EMOTICA_HOST% --port=%EMOTICA_PORT%
