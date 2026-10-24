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

# Release zips bundle their own Python in runtime/; a source checkout uses .venv.
if [ -x "runtime/bin/python3" ]; then
    PYTHON="runtime/bin/python3"
    # macOS quarantines downloaded files and would refuse to start the bundled Python.
    if [ "$(uname)" = "Darwin" ]; then
        xattr -dr com.apple.quarantine runtime 2>/dev/null || true
    fi
elif [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    echo "AutoExpress isn't installed yet. Run ./install.sh first."
    exit 1
fi

# The debugger allows running code from the browser, so only listen locally.
exec "$PYTHON" -m flask --app autoexpress run --debug \
    --host="${AUTOEXPRESS_HOST:-127.0.0.1}" --port="${AUTOEXPRESS_PORT:-5000}"
