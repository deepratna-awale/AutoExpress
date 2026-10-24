#!/usr/bin/env bash
# Starts the standalone app with Flask's debug server (auto-reload, debugger).
# For development only: use ./run.sh otherwise.

cd "$(dirname "$0")" || exit 1

echo "  ___          _          _____                                  "
echo " / _ \        | |        |  ___|                                 "
echo "/ /_\ \ _   _ | |_  ___  | |__ __  __ _ __   _ __  ___  ___  ___ "
echo "|  _  || | | || __|/ _ \ |  __|\ \/ /| '_ \ | '__|/ _ \/ __|/ __|"
echo "| | | || |_| || |_| (_) || |___ >  < | |_) || |  |  __/\__ \\\\__ \\"
echo "\_| |_/ \__,_| \__|\___/ \____//_/\_\| .__/ |_|   \___||___/|___/"
echo "                                     | |                         "
echo "                                     |_|                         "
echo ""

if [ ! -x ".venv/bin/python" ]; then
    echo "AutoExpress isn't installed yet. Run ./install.sh first."
    exit 1
fi

# The debugger allows running code from the browser, so only listen locally.
exec .venv/bin/python -m flask --app autoexpress run --debug \
    --host="${AUTOEXPRESS_HOST:-127.0.0.1}" --port="${AUTOEXPRESS_PORT:-5000}"
