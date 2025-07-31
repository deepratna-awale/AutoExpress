@echo off

echo "  ___          _          _____                                  ";
echo " / _ \        | |        |  ___|                                 ";
echo "/ /_\ \ _   _ | |_  ___  | |__ __  __ _ __   _ __  ___  ___  ___ ";
echo "|  _  || | | || __|/ _ \ |  __|\ \/ /| '_ \ | '__|/ _ \/ __|/ __|";
echo "| | | || |_| || |_| (_) || |___ >  < | |_) || |  |  __/\__ \\__ \";
echo "\_| |_/ \__,_| \__|\___/ \____//_/\_\| .__/ |_|   \___||___/|___/";
echo "                                     | |                         ";
echo "                                     |_|                         "; 

echo.
echo Starting AutoExpress...
echo Please ensure your Automatic1111 WebUI is running with API enabled (--api flag)
echo.

:: Activate the Python virtual environment
call .venv\Scripts\activate

:: Run the Flask application
flask --app autoexpress run --host=0.0.0.0 --port=5000

:: Deactivate the virtual environment after Flask stops
call deactivate
