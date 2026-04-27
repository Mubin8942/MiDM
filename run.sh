#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  MiDM — Debian/Ubuntu Setup & Run Script
#  Supports: Ubuntu 20.04+, Debian 11+, WSL2 (Ubuntu/Debian)
# ═══════════════════════════════════════════════════════════════

set -e

# ── Colors ──────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# ── Helpers ─────────────────────────────────────────────────────
ok()   { echo -e "  ${GREEN}✔${RESET}  $1"; }
info() { echo -e "  ${BLUE}→${RESET}  $1"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
fail() { echo -e "  ${RED}✘${RESET}  $1"; exit 1; }
step() { echo -e "\n${BOLD}${CYAN}[$1]${RESET} ${BOLD}$2${RESET}"; }
hr()   { echo -e "${DIM}──────────────────────────────────────────────────${RESET}"; }

# ── Banner ───────────────────────────────────────────────────────
clear
echo -e "${BOLD}${BLUE}"
cat << 'BANNER'
  ███╗   ███╗██╗██████╗ ███╗   ███╗
  ████╗ ████║██║██╔══██╗████╗ ████║
  ██╔████╔██║██║██║  ██║██╔████╔██║
  ██║╚██╔╝██║██║██║  ██║██║╚██╔╝██║
  ██║ ╚═╝ ██║██║██████╔╝██║ ╚═╝ ██║
  ╚═╝     ╚═╝╚═╝╚═════╝ ╚═╝     ╚═╝
  Modern Internet Download Manager
BANNER
echo -e "${RESET}"
echo -e "  ${DIM}Debian/Ubuntu Setup & Run Script${RESET}"
hr

# ── Detect environment ───────────────────────────────────────────
IS_WSL=false
IS_HEADLESS=false

if grep -qi microsoft /proc/version 2>/dev/null; then
    IS_WSL=true
    warn "WSL2 detected — Tauri GUI will not work inside WSL."
    info "Backend (Python) will run fine. For the UI, run the frontend natively on Windows."
    echo ""
fi

if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ] && [ "$IS_WSL" = false ]; then
    IS_HEADLESS=true
    warn "No display server detected — running in backend-only mode."
    echo ""
fi

# ── Script directory ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Parse arguments ──────────────────────────────────────────────
MODE="${1:-auto}"    # auto | setup | backend | dev | build | help

if [ "$MODE" = "help" ] || [ "$MODE" = "--help" ] || [ "$MODE" = "-h" ]; then
    echo -e "${BOLD}Usage:${RESET}"
    echo "  ./run.sh                 Auto: setup (if needed) then run backend"
    echo "  ./run.sh setup           Install all dependencies only"
    echo "  ./run.sh backend         Run Python backend server only"
    echo "  ./run.sh dev             Run backend + Tauri UI (requires display)"
    echo "  ./run.sh build           Build production .deb / AppImage"
    echo "  ./run.sh help            Show this help"
    echo ""
    exit 0
fi

# ════════════════════════════════════════════════════════════════
#  STEP 1 — System Dependencies
# ════════════════════════════════════════════════════════════════
setup_system_deps() {
    step "1/5" "Installing system packages"

    # Require apt-get
    if ! command -v apt-get &>/dev/null; then
        fail "apt-get not found. This script requires Debian/Ubuntu."
    fi

    # Require sudo
    if ! command -v sudo &>/dev/null; then
        fail "sudo is not installed. Please install it: apt-get install sudo"
    fi

    info "Updating package lists..."
    sudo apt-get update -qq

    PKGS=(
        python3 python3-pip python3-venv
        curl wget git build-essential
        pkg-config libssl-dev
    )

    # Tauri requires these on Linux (skip in WSL/headless)
    if [ "$IS_WSL" = false ] && [ "$IS_HEADLESS" = false ]; then
        PKGS+=(
            libwebkit2gtk-4.1-dev
            libgtk-3-dev
            libayatana-appindicator3-dev
            librsvg2-dev
            libxdo-dev
            libxcb-shape0-dev
            libxcb-xfixes0-dev
        )
    fi

    info "Installing: ${PKGS[*]}"
    # Try quiet first, fall back to verbose on error
    sudo apt-get install -y -qq "${PKGS[@]}" 2>/dev/null || \
        sudo apt-get install -y "${PKGS[@]}"

    ok "System packages installed"
}

# ════════════════════════════════════════════════════════════════
#  STEP 2 — Python Virtual Environment
# ════════════════════════════════════════════════════════════════
setup_python() {
    step "2/5" "Setting up Python environment"

    PYTHON_BIN=$(command -v python3 || true)

    if [ -z "$PYTHON_BIN" ]; then
        fail "python3 not found after installation. Check your apt sources."
    fi

    # Use pure bash/awk version parsing — avoids POSIX grep -P issues on Debian
    PYTHON_VER=$($PYTHON_BIN --version 2>&1 | awk '{print $2}')
    PYTHON_MAJOR=$(echo "$PYTHON_VER" | cut -d. -f1)
    PYTHON_MINOR=$(echo "$PYTHON_VER" | cut -d. -f2)
    info "Found Python $PYTHON_VER"

    if [ "$PYTHON_MAJOR" -gt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -ge 11 ]; }; then
        ok "Python $PYTHON_VER meets minimum requirement (3.11+)"
    else
        warn "Python $PYTHON_VER found, but 3.11+ is recommended."
        info "Attempting to install python3.11..."
        sudo apt-get install -y python3.11 python3.11-venv 2>/dev/null && \
            PYTHON_BIN=$(command -v python3.11) || \
            warn "Could not install 3.11 — continuing with $PYTHON_VER"
    fi

    # Create virtual environment
    VENV_DIR="$SCRIPT_DIR/.venv"
    if [ ! -d "$VENV_DIR" ]; then
        info "Creating virtual environment at .venv/"
        "$PYTHON_BIN" -m venv "$VENV_DIR"
        ok "Virtual environment created"
    else
        ok "Virtual environment already exists"
    fi

    # Activate
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"

    info "Upgrading pip..."
    pip install --quiet --upgrade pip

    # Create a default requirements.txt if one doesn't exist
    if [ ! -f "$SCRIPT_DIR/requirements.txt" ]; then
        warn "requirements.txt not found — creating a default one."
        cat > "$SCRIPT_DIR/requirements.txt" << 'EOF'
aiohttp>=3.9.0
aiofiles>=23.2.1
httpx>=0.27.0
humanize>=4.9.0
websockets>=12.0
EOF
        ok "Default requirements.txt created"
    fi

    info "Installing Python dependencies from requirements.txt..."
    pip install --quiet -r "$SCRIPT_DIR/requirements.txt"

    ok "Python packages installed"
}

# ════════════════════════════════════════════════════════════════
#  STEP 3 — Node.js (only needed for dev/build modes)
# ════════════════════════════════════════════════════════════════
setup_node() {
    # Skip Node setup entirely if there's no frontend directory
    # and we're not in dev/build mode
    if [ ! -d "$SCRIPT_DIR/midm-ui" ] && [ "$MODE" != "dev" ] && [ "$MODE" != "build" ]; then
        warn "midm-ui/ directory not found — skipping Node.js setup (not needed for backend-only mode)"
        return
    fi

    step "3/5" "Setting up Node.js"

    if command -v node &>/dev/null; then
        NODE_VER=$(node --version)
        info "Node.js $NODE_VER already installed"

        NODE_MAJOR=$(echo "$NODE_VER" | tr -d 'v' | cut -d. -f1)
        if [ "$NODE_MAJOR" -lt 18 ]; then
            warn "Node.js $NODE_VER is too old (need 18+). Upgrading..."
            install_node
        else
            ok "Node.js $NODE_VER is compatible"
        fi
    else
        install_node
    fi

    # Only install npm packages if midm-ui exists
    if [ -d "$SCRIPT_DIR/midm-ui" ]; then
        if [ ! -f "$SCRIPT_DIR/midm-ui/package.json" ]; then
            warn "midm-ui/package.json not found — skipping npm install"
        else
            info "Installing npm packages..."
            cd "$SCRIPT_DIR/midm-ui"
            npm install --silent
            cd "$SCRIPT_DIR"
            ok "Frontend npm packages installed"
        fi
    else
        warn "midm-ui/ not found — skipping npm install"
    fi
}

install_node() {
    info "Installing Node.js 20 LTS via NodeSource..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - 2>/dev/null
    sudo apt-get install -y nodejs -qq
    ok "Node.js $(node --version) installed"
}

# ════════════════════════════════════════════════════════════════
#  STEP 4 — Rust (required for Tauri, skip in WSL/headless/backend)
# ════════════════════════════════════════════════════════════════
setup_rust() {
    if [ "$IS_WSL" = true ] || [ "$IS_HEADLESS" = true ]; then
        warn "Skipping Rust install (WSL/headless — Tauri not needed for backend-only mode)"
        return
    fi

    # Also skip if we're only going to run the backend
    if [ "$MODE" = "backend" ] || [ "$MODE" = "auto" ]; then
        warn "Skipping Rust install (backend-only mode)"
        return
    fi

    step "4/5" "Setting up Rust"

    if command -v rustc &>/dev/null; then
        ok "Rust $(rustc --version | awk '{print $2}') already installed"
        rustup update stable --quiet 2>/dev/null || true
    else
        info "Installing Rust via rustup..."
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --quiet
        # shellcheck source=/dev/null
        source "$HOME/.cargo/env"
        ok "Rust $(rustc --version | awk '{print $2}') installed"
    fi

    export PATH="$HOME/.cargo/bin:$PATH"
}

# ════════════════════════════════════════════════════════════════
#  STEP 5 — Mark setup complete
# ════════════════════════════════════════════════════════════════
finish_setup() {
    step "5/5" "Finalizing setup"

    echo "$(date --iso-8601=seconds)" > "$SCRIPT_DIR/.midm_setup_done"

    echo ""
    hr
    echo -e "  ${GREEN}${BOLD}Setup complete!${RESET}"
    hr
    echo ""
    echo -e "  ${BOLD}Run commands:${RESET}"
    echo -e "    ${CYAN}./run.sh backend${RESET}   — Start download engine only"
    echo -e "    ${CYAN}./run.sh dev${RESET}        — Start backend + UI (needs display)"
    echo -e "    ${CYAN}./run.sh build${RESET}      — Build AppImage / .deb package"
    echo ""
}

# ════════════════════════════════════════════════════════════════
#  RUN — Backend server
# ════════════════════════════════════════════════════════════════
run_backend() {
    step "▶" "Starting MiDM Backend"

    VENV_DIR="$SCRIPT_DIR/.venv"
    if [ ! -d "$VENV_DIR" ]; then
        warn "Virtual environment not found. Running setup first..."
        do_setup
    fi

    # Verify server.py exists before attempting to run
    BACKEND_SCRIPT="$SCRIPT_DIR/backend/server.py"
    if [ ! -f "$BACKEND_SCRIPT" ]; then
        fail "backend/server.py not found. Make sure the project files are present at: $SCRIPT_DIR/backend/"
    fi

    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"

    echo ""
    hr
    echo -e "  ${GREEN}${BOLD}MiDM Backend Server${RESET}"
    echo -e "  ${DIM}WebSocket → ws://127.0.0.1:7475/ws${RESET}"
    echo -e "  ${DIM}HTTP API  → http://127.0.0.1:7475${RESET}"
    hr
    echo -e "  ${DIM}Press Ctrl+C to stop${RESET}"
    echo ""

    python3 "$BACKEND_SCRIPT"
}

# ════════════════════════════════════════════════════════════════
#  RUN — Full dev mode (backend + Tauri UI)
# ════════════════════════════════════════════════════════════════
run_dev() {
    if [ "$IS_WSL" = true ]; then
        echo ""
        warn "You are in WSL2. Tauri cannot open a GUI window inside WSL."
        echo ""
        echo -e "  ${BOLD}To run MiDM with UI from WSL:${RESET}"
        echo -e "  1. Start the backend here:  ${CYAN}./run.sh backend${RESET}"
        echo -e "  2. On Windows, open a cmd/PowerShell in the project folder and run:"
        echo -e "     ${CYAN}cd midm-ui && npm run tauri dev${RESET}"
        echo ""
        read -rp "  Start backend-only instead? [Y/n] " choice
        case "${choice,,}" in
            n|no) exit 0 ;;
            *)    run_backend ;;
        esac
        return
    fi

    if [ "$IS_HEADLESS" = true ]; then
        warn "No display detected. Starting backend only."
        run_backend
        return
    fi

    if [ ! -d "$SCRIPT_DIR/midm-ui" ]; then
        fail "midm-ui/ directory not found. Cannot start Tauri UI."
    fi

    step "▶" "Starting MiDM (Backend + Tauri UI)"

    VENV_DIR="$SCRIPT_DIR/.venv"
    if [ ! -d "$VENV_DIR" ]; then
        warn "Virtual environment not found. Running setup first..."
        do_setup
    fi

    BACKEND_SCRIPT="$SCRIPT_DIR/backend/server.py"
    if [ ! -f "$BACKEND_SCRIPT" ]; then
        fail "backend/server.py not found at: $BACKEND_SCRIPT"
    fi

    # Start backend in background
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"
    info "Starting Python backend..."
    python3 "$BACKEND_SCRIPT" &
    BACKEND_PID=$!

    # Give backend 2s to initialize
    sleep 2

    # Verify backend actually started
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        fail "Backend failed to start. Check backend/server.py for errors."
    fi

    # Trap Ctrl+C to kill both processes cleanly
    trap "echo ''; info 'Shutting down...'; kill $BACKEND_PID 2>/dev/null; exit 0" INT TERM

    info "Starting Tauri UI..."
    export PATH="$HOME/.cargo/bin:$PATH"
    cd "$SCRIPT_DIR/midm-ui"
    npm run tauri dev

    # If Tauri exits, also stop backend
    kill "$BACKEND_PID" 2>/dev/null || true
}

# ════════════════════════════════════════════════════════════════
#  BUILD — AppImage + .deb
# ════════════════════════════════════════════════════════════════
run_build() {
    step "▶" "Building MiDM for Linux"

    if [ ! -d "$SCRIPT_DIR/midm-ui" ]; then
        fail "midm-ui/ directory not found. Cannot build Tauri app."
    fi

    if [ "$IS_WSL" = true ]; then
        warn "Building inside WSL may produce binaries that only run on WSL."
        read -rp "  Continue anyway? [y/N] " choice
        case "${choice,,}" in
            y|yes) ;;
            *) exit 0 ;;
        esac
    fi

    export PATH="$HOME/.cargo/bin:$PATH"

    # Ensure Rust is available
    if ! command -v cargo &>/dev/null; then
        fail "Rust/cargo not found. Run './run.sh setup' first (without WSL/headless mode)."
    fi

    # Bundle Python backend with PyInstaller
    info "Packaging Python backend with PyInstaller..."
    VENV_DIR="$SCRIPT_DIR/.venv"
    if [ ! -d "$VENV_DIR" ]; then
        fail "Virtual environment not found. Run './run.sh setup' first."
    fi

    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"

    BACKEND_SCRIPT="$SCRIPT_DIR/backend/server.py"
    if [ ! -f "$BACKEND_SCRIPT" ]; then
        fail "backend/server.py not found at: $BACKEND_SCRIPT"
    fi

    pip install --quiet pyinstaller

    pyinstaller \
        --onefile \
        --name midm-backend \
        --distpath "$SCRIPT_DIR/dist" \
        --workpath "$SCRIPT_DIR/build_tmp" \
        --specpath "$SCRIPT_DIR/build_tmp" \
        "$BACKEND_SCRIPT"

    ok "Backend binary: dist/midm-backend"

    # Copy binary to Tauri resources
    mkdir -p "$SCRIPT_DIR/midm-ui/src-tauri/resources"
    cp "$SCRIPT_DIR/dist/midm-backend" "$SCRIPT_DIR/midm-ui/src-tauri/resources/"

    # Build Tauri
    info "Building Tauri AppImage + .deb..."
    cd "$SCRIPT_DIR/midm-ui"
    npm run tauri build

    echo ""
    hr
    echo -e "  ${GREEN}${BOLD}Build complete!${RESET}"
    hr
    BUNDLE_DIR="$SCRIPT_DIR/midm-ui/src-tauri/target/release/bundle"
    echo -e "  ${BOLD}Outputs:${RESET}"
    find "$BUNDLE_DIR" \( -name "*.AppImage" -o -name "*.deb" \) 2>/dev/null | \
        while read -r f; do
            SIZE=$(du -sh "$f" | cut -f1)
            echo -e "    ${GREEN}✔${RESET}  $f ${DIM}($SIZE)${RESET}"
        done
    echo ""
}

# ════════════════════════════════════════════════════════════════
#  Do full setup — smart: skips Node/Rust for backend-only
# ════════════════════════════════════════════════════════════════
do_setup() {
    setup_system_deps
    setup_python

    # Only install Node/Rust if dev or build mode is explicitly requested
    if [ "$MODE" = "dev" ] || [ "$MODE" = "build" ] || [ "$MODE" = "setup" ]; then
        setup_node
        setup_rust
    else
        info "Skipping Node.js and Rust (not needed for backend mode)"
        info "Run './run.sh setup' to install everything including Tauri dependencies"
    fi

    finish_setup
}

# ════════════════════════════════════════════════════════════════
#  Main dispatcher
# ════════════════════════════════════════════════════════════════
case "$MODE" in
    setup)
        do_setup
        ;;
    backend)
        if [ ! -f "$SCRIPT_DIR/.midm_setup_done" ]; then
            info "First run detected — running setup..."
            do_setup
        fi
        run_backend
        ;;
    dev)
        if [ ! -f "$SCRIPT_DIR/.midm_setup_done" ]; then
            info "First run detected — running setup..."
            do_setup
        fi
        run_dev
        ;;
    build)
        if [ ! -f "$SCRIPT_DIR/.midm_setup_done" ]; then
            info "First run detected — running setup..."
            do_setup
        fi
        run_build
        ;;
    auto|*)
        if [ ! -f "$SCRIPT_DIR/.midm_setup_done" ]; then
            do_setup
        fi
        run_backend
        ;;
esac