#!/bin/bash

echo "  ___          _          _____                                  "
echo " / _ \        | |        |  ___|                                 "
echo "/ /_\ \ _   _ | |_  ___  | |__ __  __ _ __   _ __  ___  ___  ___ "
echo "|  _  || | | || __|/ _ \ |  __|\ \/ /| '_ \ | '__|/ _ \/ __|/ __|"
echo "| | | || |_| || |_| (_) || |___ >  < | |_) || |  |  __/\__ \\\\__ \\"
echo "\_| |_/ \__,_| \__|\___/ \____//_/\_\| .__/ |_|   \___||___/|___/"
echo "                                     | |                         "
echo "                                     |_|                         "

echo ""
echo "Starting AutoExpress..."
echo "Make sure your WebUI is running (A1111/Forge need the --api flag)."
echo ""

# Activate the Python virtual environment
source .venv/bin/activate

# Run the Flask application
python -m autoexpress

# Deactivate the virtual environment after Flask stops
deactivate
