@echo off
:: Sets up the standalone app: a Python virtual environment in .venv with
:: requirements.txt, and the Next.js web interface in frontend\out.
::
::   install.bat                  install, reusing an existing .venv
::   install.bat --clean          delete .venv first and start over
::   install.bat --skip-frontend  Python only (the classic interface is served)
::
:: Needs Python 3.10+; the web interface also needs Node.js 20.9+ (26
:: recommended) with pnpm or corepack.
setlocal
cd /d "%~dp0"

echo "  ___          _          _____                                    _____             _          _  _             "
echo " / _ \        | |        |  ___|                                  |_   _|           | |        | || |            "
echo "/ /_\ \ _   _ | |_  ___  | |__ __  __ _ __   _ __  ___  ___  ___    | |  _ __   ___ | |_  __ _ | || |  ___  _ __ "
echo "|  _  || | | || __|/ _ \ |  __|\ \/ /| '_ \ | '__|/ _ \/ __|/ __|   | | | '_ \ / __|| __|/ _`|| || | / _ \| '__|"
echo "| | | || |_| || |_| (_) || |___ >  < | |_) || |  |  __/\__ \\__ \  _| |_| | | |\__ \| |_| (_| || || ||  __/| |   "
echo "\_| |_/ \__,_| \__|\___/ \____//_/\_\| .__/ |_|   \___||___/|___/  \___/|_| |_||___/ \__|\__,_||_||_| \___||_|   "
echo "                                     | |                                                                         "
echo "                                     |_|                                                                         "
echo ================================================

set CLEAN=0
set SKIP_FRONTEND=0
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--clean" (set CLEAN=1& shift & goto parse_args)
if /i "%~1"=="--skip-frontend" (set SKIP_FRONTEND=1& shift & goto parse_args)
echo Unknown option: %~1
echo Options: --clean, --skip-frontend
exit /b 1
:args_done

set LOGFILE=install_logs.txt
echo Installation log - %date% %time% > "%LOGFILE%"

:: Python 3.10 or newer: "python" first, then the "py" launcher
set PYTHON=
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 set PYTHON=python
if not defined PYTHON (
    py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
    if not errorlevel 1 set PYTHON=py -3
)
if not defined PYTHON (
    call :fail "Python 3.10 or newer was not found. Install it from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'."
    exit /b 1
)
for /f "delims=" %%v in ('%PYTHON% --version 2^>^&1') do call :log "Using %%v."

:: Virtual environment
if "%CLEAN%"=="1" if exist ".venv" (
    call :log "Deleting the existing virtual environment..."
    rmdir /s /q ".venv" >> "%LOGFILE%" 2>&1
    if exist ".venv" (
        call :fail "Could not delete .venv. Close anything that is using it and try again."
        exit /b 1
    )
)
if exist ".venv\Scripts\python.exe" (
    call :log "Reusing the existing virtual environment (install.bat --clean starts over)."
    goto venv_ready
)
call :log "Creating the virtual environment in .venv..."
if exist ".venv" rmdir /s /q ".venv" >> "%LOGFILE%" 2>&1
%PYTHON% -m venv .venv >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    call :fail "Could not create the virtual environment."
    exit /b 1
)
:venv_ready
set VENV_PYTHON=.venv\Scripts\python.exe

call :log "Upgrading pip..."
"%VENV_PYTHON%" -m pip install --upgrade pip >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    call :fail "Could not upgrade pip."
    exit /b 1
)

if not exist requirements.txt (
    call :fail "requirements.txt not found."
    exit /b 1
)
call :log "Installing requirements..."
"%VENV_PYTHON%" -m pip install -r requirements.txt >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    call :fail "Could not install the requirements."
    exit /b 1
)
call :log "Python requirements installed."

:: Web interface
if "%SKIP_FRONTEND%"=="1" (
    call :log "Skipping the web interface (--skip-frontend)."
    goto done
)
where node >nul 2>&1
if errorlevel 1 (
    call :log "WARNING: Node.js was not found, so the web interface was not built. Install Node.js 26 from https://nodejs.org/ and run install.bat again. Until then the classic interface is served."
    goto done
)
node -e "process.exit(+process.versions.node.split('.')[0] < 20 ? 1 : 0)" >nul 2>&1
if errorlevel 1 (
    call :log "WARNING: Node.js is too old for the web interface (needs 20.9+, 26 recommended). The classic interface is served until it's built."
    goto done
)
set PNPM=
where pnpm >nul 2>&1
if not errorlevel 1 set PNPM=pnpm
if not defined PNPM (
    where corepack >nul 2>&1
    if not errorlevel 1 set PNPM=corepack pnpm
)
if not defined PNPM (
    call :log "WARNING: pnpm was not found (npm install -g pnpm, or corepack enable). The classic interface is served until the web interface is built."
    goto done
)
for /f "delims=" %%v in ('node --version') do call :log "Building the web interface with Node.js %%v..."
pushd frontend
call %PNPM% install --frozen-lockfile >> "..\%LOGFILE%" 2>&1
if errorlevel 1 goto frontend_failed
call %PNPM% build >> "..\%LOGFILE%" 2>&1
if errorlevel 1 goto frontend_failed
popd
call :log "Web interface built in frontend\out."
goto done

:frontend_failed
popd
call :log "WARNING: The web interface failed to build (see %LOGFILE%). The classic interface is served until it's built."

:done
echo ================================================
call :log "AutoExpress is installed. Start it with run.bat and open http://127.0.0.1:5000"
pause
exit /b 0

:log
echo %~1
echo %~1>> "%LOGFILE%"
exit /b 0

:fail
echo ERROR: %~1
echo ERROR: %~1>> "%LOGFILE%"
echo See %LOGFILE% for details.
pause
exit /b 1
