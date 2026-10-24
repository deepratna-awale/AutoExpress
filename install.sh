#!/usr/bin/env bash
# Sets up the standalone app: a Python virtual environment in .venv with the
# "standalone" dependencies from pyproject.toml (the versions pinned in uv.lock
# when uv is installed), and the Next.js web interface in frontend/out.
#
#   ./install.sh                  install, reusing an existing .venv
#   ./install.sh --clean          delete .venv first and start over
#   ./install.sh --skip-frontend  Python only (the classic interface is served)
#
# Works on Linux and macOS. Needs Python 3.10+; the web interface also needs
# Node.js 20.9+ (26 recommended) with pnpm or corepack.

cd "$(dirname "$0")" || exit 1

echo "  ___          _          _____                                    _____             _          _  _             "
echo " / _ \        | |        |  ___|                                  |_   _|           | |        | || |            "
echo "/ /_\ \ _   _ | |_  ___  | |__ __  __ _ __   _ __  ___  ___  ___    | |  _ __   ___ | |_  __ _ | || |  ___  _ __ "
echo "|  _  || | | || __|/ _ \ |  __|\ \/ /| '_ \ | '__|/ _ \/ __|/ __|   | | | '_ \ / __|| __|/ _\`|| || | / _ \| '__|"
echo "| | | || |_| || |_| (_) || |___ >  < | |_) || |  |  __/\__ \\\\__ \  _| |_| | | |\__ \| |_| (_| || || ||  __/| |   "
echo "\_| |_/ \__,_| \__|\___/ \____//_/\_\| .__/ |_|   \___||___/|___/  \___/|_| |_||___/ \__|\__,_||_||_| \___||_|   "
echo "                                     | |                                                                         "
echo "                                     |_|                                                                         "
echo "================================================"

CLEAN=0
SKIP_FRONTEND=0
for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN=1 ;;
        --skip-frontend) SKIP_FRONTEND=1 ;;
        -h|--help)
            sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "Unknown option: $arg (see ./install.sh --help)"; exit 1 ;;
    esac
done

LOGFILE="install_logs.txt"
echo "Installation log - $(date)" > "$LOGFILE"

log() { echo "$1" | tee -a "$LOGFILE"; }
fail() {
    echo "ERROR: $1" | tee -a "$LOGFILE"
    echo "See $LOGFILE for details."
    exit 1
}

# Python 3.10 or newer
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    fail "Python 3.10 or newer was not found. Install it from https://www.python.org/downloads/ (Debian/Ubuntu: sudo apt install python3 python3-venv python3-pip)."
fi
log "Using $("$PYTHON" --version 2>&1) ($(command -v "$PYTHON"))."

# Virtual environment
if [ "$CLEAN" -eq 1 ] && [ -d ".venv" ]; then
    log "Deleting the existing virtual environment..."
    rm -rf ".venv" >> "$LOGFILE" 2>&1 || fail "Could not delete .venv."
fi
if [ ! -x ".venv/bin/python" ]; then
    log "Creating the virtual environment in .venv..."
    rm -rf ".venv" >> "$LOGFILE" 2>&1
    if ! "$PYTHON" -m venv .venv >> "$LOGFILE" 2>&1; then
        fail "Could not create the virtual environment. On Debian/Ubuntu install the venv module first: sudo apt install python3-venv"
    fi
else
    log "Reusing the existing virtual environment (./install.sh --clean starts over)."
fi
VENV_PYTHON=".venv/bin/python"

log "Upgrading pip..."
"$VENV_PYTHON" -m pip install --upgrade pip >> "$LOGFILE" 2>&1 || fail "Could not upgrade pip."

[ -f "pyproject.toml" ] || fail "pyproject.toml not found."
if command -v uv >/dev/null 2>&1 && [ -f "uv.lock" ]; then
    log "Installing the dependencies pinned in uv.lock..."
    uv export --frozen --extra standalone --no-dev --no-emit-project -o .venv/requirements.lock.txt >> "$LOGFILE" 2>&1 &&
        uv pip install --python "$VENV_PYTHON" --require-hashes -r .venv/requirements.lock.txt >> "$LOGFILE" 2>&1 ||
        fail "Could not install the dependencies."
else
    log "Installing the dependencies (install uv to get the exact versions in uv.lock)..."
    "$VENV_PYTHON" -m pip install -e ".[standalone]" >> "$LOGFILE" 2>&1 || fail "Could not install the dependencies."
fi
log "Python dependencies installed."

# Web interface
build_frontend() {
    if ! command -v node >/dev/null 2>&1; then
        log "WARNING: Node.js was not found, so the web interface was not built. Install Node.js 26 from https://nodejs.org/ and run ./install.sh again. Until then the classic interface is served."
        return
    fi
    local major
    major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null)"
    if [ -z "$major" ] || [ "$major" -lt 20 ]; then
        log "WARNING: Node.js $(node --version 2>/dev/null) is too old for the web interface (needs 20.9+, 26 recommended). The classic interface is served until it's built."
        return
    fi

    local pnpm
    if command -v pnpm >/dev/null 2>&1; then
        pnpm="pnpm"
    elif command -v corepack >/dev/null 2>&1; then
        pnpm="corepack pnpm"
    else
        log "WARNING: pnpm was not found (npm install -g pnpm, or corepack enable). The classic interface is served until the web interface is built."
        return
    fi

    log "Building the web interface with Node.js $(node --version)..."
    if (cd frontend && $pnpm install --frozen-lockfile && $pnpm build) >> "$LOGFILE" 2>&1; then
        log "Web interface built in frontend/out."
    else
        log "WARNING: The web interface failed to build (see $LOGFILE). The classic interface is served until it's built."
    fi
}

if [ "$SKIP_FRONTEND" -eq 1 ]; then
    log "Skipping the web interface (--skip-frontend)."
else
    build_frontend
fi

echo "================================================"
log "AutoExpress is installed. Start it with ./run.sh and open http://127.0.0.1:5000"
