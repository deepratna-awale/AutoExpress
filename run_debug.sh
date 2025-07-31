#!/bin/bash

echo "  ___          _          _____                                  ";
echo " / _ \        | |        |  ___|                                 ";
echo "/ /_\ \ _   _ | |_  ___  | |__ __  __ _ __   _ __  ___  ___  ___ ";
echo "|  _  || | | || __|/ _ \ |  __|\ \/ /| '_ \ | '__|/ _ \/ __|/ __|";
echo "| | | || |_| || |_| (_) || |___ >  < | |_) || |  |  __/\__ \\__ \";
echo "\_| |_/ \__,_| \__|\___/ \____//_/\_\| .__/ |_|   \___||___/|___/";
echo "                                     | |                         ";
echo "                                     |_|                         "; 

# Activate the Python virtual environment
source .venv/bin/activate

# Run the Flask application in debug mode
flask --app autoexpress run --host=0.0.0.0 --port=5000 --debug

# Deactivate the virtual environment after Flask stops
deactivate
