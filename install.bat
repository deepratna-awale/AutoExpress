@echo off

echo "  ___          _          _____                                    _____             _          _  _             ";
echo " / _ \        | |        |  ___|                                  |_   _|           | |        | || |            ";
echo "/ /_\ \ _   _ | |_  ___  | |__ __  __ _ __   _ __  ___  ___  ___    | |  _ __   ___ | |_  __ _ | || |  ___  _ __ ";
echo "|  _  || | | || __|/ _ \ |  __|\ \/ /| '_ \ | '__|/ _ \/ __|/ __|   | | | '_ \ / __|| __|/ _\` || || | / _ \| '__|";
echo "| | | || |_| || |_| (_) || |___ >  < | |_) || |  |  __/\__ \\__ \  _| |_| | | |\__ \| |_| (_| || || ||  __/| |   ";
echo "\_| |_/ \__,_| \__|\___/ \____//_/\_\| .__/ |_|   \___||___/|___/  \___/|_| |_||___/ \__|\__,_||_||_| \___||_|   ";
echo "                                     | |                                                                         ";
echo "                                     |_|                                                                         ";

echo ================================================
:: Define log file
set LOGFILE=install_logs.txt

:: Clear the log file at the start
echo ================================================== > %LOGFILE%
echo Installation Log - %date% %time% >> %LOGFILE%
echo ================================================== >> %LOGFILE%

:: Check if Python is installed
echo Checking if Python is installed...
echo [INFO] Checking if Python is installed... >> %LOGFILE%
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to PATH. >> %LOGFILE%
    echo [ERROR] Python is not installed or not added to PATH.
    exit /b 1
)
echo [SUCCESS] Python found.
echo [SUCCESS] Python found. >> %LOGFILE%

:: Check if .venv folder exists and delete it
if exist ".venv" (
    echo Virtual environment detected. Deleting existing environment...
    echo [INFO] Virtual environment detected. Deleting existing environment... >> %LOGFILE%
    rmdir /s /q ".venv" >> %LOGFILE% 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to delete the existing virtual environment. >> %LOGFILE%
        echo [ERROR] Failed to delete the existing virtual environment.
        exit /b 1
    )
    echo [SUCCESS] Existing virtual environment deleted.
    echo [SUCCESS] Existing virtual environment deleted. >> %LOGFILE%
)

:: Create a new virtual environment
echo Creating new virtual environment...
echo [INFO] Creating new virtual environment... >> %LOGFILE%
python -m venv .venv >> %LOGFILE% 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create the virtual environment. >> %LOGFILE%
    echo [ERROR] Failed to create the virtual environment.
    exit /b 1
)
echo [SUCCESS] Virtual environment created successfully.
echo [SUCCESS] Virtual environment created successfully. >> %LOGFILE%

:: Activate the virtual environment
echo Activating virtual environment...
echo [INFO] Activating virtual environment... >> %LOGFILE%
call .venv\Scripts\activate >> %LOGFILE% 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Failed to activate the virtual environment. >> %LOGFILE%
    echo [ERROR] Failed to activate the virtual environment.
    exit /b 1
)

:: Upgrade pip to the latest version
echo Upgrading pip to the latest version...
echo [INFO] Upgrading pip... >> %LOGFILE%
python.exe -m pip install --upgrade pip >> %LOGFILE% 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Failed to upgrade pip. >> %LOGFILE%
    echo [ERROR] Failed to upgrade pip.
    deactivate
    exit /b 1
)
echo [SUCCESS] Pip upgraded successfully.
echo [SUCCESS] Pip upgraded successfully. >> %LOGFILE%

:: Check if requirements.txt exists
if not exist requirements.txt (
    echo [ERROR] requirements.txt not found. >> %LOGFILE%
    echo [ERROR] requirements.txt not found.
    deactivate
    exit /b 1
)

:: Install requirements
echo Installing requirements from requirements.txt...
echo [INFO] Installing requirements from requirements.txt... >> %LOGFILE%
pip install -r requirements.txt >> %LOGFILE% 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install requirements. >> %LOGFILE%
    echo [ERROR] Failed to install requirements.
    deactivate
    exit /b 1
)
echo [SUCCESS] Requirements installed successfully.
echo [SUCCESS] Requirements installed successfully. >> %LOGFILE%

:: Deactivate the virtual environment
echo Deactivating virtual environment...
echo [INFO] Deactivating virtual environment... >> %LOGFILE%
call deactivate >> %LOGFILE% 2>&1

echo ================================================== >> %LOGFILE%
echo All requirements installed successfully. >> %LOGFILE%
echo All requirements installed successfully.
echo ==================================================

pause
