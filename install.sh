#!/bin/bash

echo "  ___          _          _____                                    _____             _          _  _             ";
echo " / _ \        | |        |  ___|                                  |_   _|           | |        | || |            ";
echo "/ /_\ \ _   _ | |_  ___  | |__ __  __ _ __   _ __  ___  ___  ___    | |  _ __   ___ | |_  __ _ | || |  ___  _ __ ";
echo "|  _  || | | || __|/ _ \ |  __|\ \/ /| '_ \ | '__|/ _ \/ __|/ __|   | | | '_ \ / __|| __|/ _\`|| || | / _ \| '__|";
echo "| | | || |_| || |_| (_) || |___ >  < | |_) || |  |  __/\__ \\__ \  _| |_| | | |\__ \| |_| (_| || || ||  __/| |   ";
echo "\_| |_/ \__,_| \__|\___/ \____//_/\_\| .__/ |_|   \___||___/|___/  \___/|_| |_||___/ \__|\__,_||_||_| \___||_|   ";
echo "                                     | |                                                                         ";
echo "                                     |_|                                                                         ";

#!/bin/bash

echo "================================================"
# Define log file
LOGFILE="install_logs.txt"

echo "Installation log - $(date)" > "$LOGFILE"
echo "================================================"

# Update and upgrade system packages
echo "Updating and upgrading system packages..."
echo "Updating and upgrading system packages..." >> "$LOGFILE"
sudo apt update -y && sudo apt upgrade -y >> "$LOGFILE" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to update and upgrade system packages." | tee -a "$LOGFILE"
    exit 1
fi
echo "System packages updated and upgraded successfully." | tee -a "$LOGFILE"

# Check if Python is installed
echo "Checking if Python is installed..."
echo "Checking if Python is installed..." >> "$LOGFILE"
if ! command -v python3 &> /dev/null; then
    echo "Python is not installed. Installing Python..."
    echo "Python is not installed. Installing Python..." >> "$LOGFILE"
    sudo apt install -y python3 >> "$LOGFILE" 2>&1
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to install Python." | tee -a "$LOGFILE"
        exit 1
    fi
    echo "Python installed successfully." | tee -a "$LOGFILE"
else
    echo "Python is already installed." | tee -a "$LOGFILE"
fi

# Check and install python3-venv package
echo "Checking if python3-venv package is installed..."
echo "Checking if python3-venv package is installed..." >> "$LOGFILE"
if ! dpkg -l | grep -q python3-venv; then
    echo "python3-venv is not installed. Installing it..."
    sudo apt install -y python3-venv >> "$LOGFILE" 2>&1
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to install python3-venv." | tee -a "$LOGFILE"
        exit 1
    fi
    echo "python3-venv installed successfully." | tee -a "$LOGFILE"
else
    echo "python3-venv is already installed." | tee -a "$LOGFILE"
fi

# Check and install python3-pip package
echo "Checking if python3-pip package is installed..."
echo "Checking if python3-pip package is installed..." >> "$LOGFILE"
if ! dpkg -l | grep -q python3-pip; then
    echo "python3-pip is not installed. Installing it..."
    sudo apt install -y python3-pip >> "$LOGFILE" 2>&1
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to install python3-pip." | tee -a "$LOGFILE"
        exit 1
    fi
    echo "python3-pip installed successfully." | tee -a "$LOGFILE"
else
    echo "python3-pip is already installed." | tee -a "$LOGFILE"
fi

# Check if .venv folder exists and delete it
if [ -d ".venv" ]; then
    echo "Virtual environment found. Deleting it..."
    echo "Virtual environment found. Deleting it..." >> "$LOGFILE"
    rm -rf ".venv" >> "$LOGFILE" 2>&1
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to delete the existing virtual environment." | tee -a "$LOGFILE"
        exit 1
    fi
    echo "Existing virtual environment deleted." | tee -a "$LOGFILE"
fi

# Create a new virtual environment
echo "Creating new virtual environment..."
echo "Creating new virtual environment..." >> "$LOGFILE"
python3 -m venv .venv >> "$LOGFILE" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to create the virtual environment." | tee -a "$LOGFILE"
    exit 1
fi
echo "Virtual environment created successfully." | tee -a "$LOGFILE"

# Activate the virtual environment
echo "Activating virtual environment..."
echo "Activating virtual environment..." >> "$LOGFILE"
source .venv/bin/activate >> "$LOGFILE" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to activate the virtual environment." | tee -a "$LOGFILE"
    exit 1
fi

# Upgrade pip to the latest version
echo "Upgrading pip..."
echo "Upgrading pip..." >> "$LOGFILE"
python3 -m pip install --upgrade pip >> "$LOGFILE" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to upgrade pip." | tee -a "$LOGFILE"
    deactivate
    exit 1
fi
echo "Pip upgraded successfully." | tee -a "$LOGFILE"

# Check if requirements.txt exists
if [ ! -f "requirements.txt" ]; then
    echo "ERROR: requirements.txt not found." | tee -a "$LOGFILE"
    deactivate
    exit 1
fi

# Install requirements
echo "Installing requirements..."
echo "Installing requirements..." >> "$LOGFILE"
pip install -r requirements.txt >> "$LOGFILE" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install requirements." | tee -a "$LOGFILE"
    deactivate
    exit 1
fi
echo "Requirements installed successfully." | tee -a "$LOGFILE"

# Deactivate the virtual environment
echo "Deactivating virtual environment..."
echo "Deactivating virtual environment..." >> "$LOGFILE"
deactivate >> "$LOGFILE" 2>&1

echo "All requirements installed successfully." | tee -a "$LOGFILE"


