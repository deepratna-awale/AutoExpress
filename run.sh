#!/usr/bin/env bash
# Starts the standalone app on http://127.0.0.1:5000 (production server).
# Settings come from environment variables, see autoexpress/config.py, e.g.
#   AUTOEXPRESS_BACKEND_URL=https://<pod-id>-8188.proxy.runpod.net ./run.sh

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

if [ ! -f "frontend/out/index.html" ]; then
    echo "The web interface isn't built, so the classic interface is served."
    echo "Install Node.js 26 and run ./install.sh again to build it."
    echo ""
fi

echo "Starting AutoExpress on http://127.0.0.1:${AUTOEXPRESS_PORT:-5000}"
echo "Your WebUI can run on this machine or anywhere else (RunPod etc.): paste its"
echo "address in the page and press connect. A1111 and Forge need the --api flag."
echo ""

exec .venv/bin/python -m autoexpress
