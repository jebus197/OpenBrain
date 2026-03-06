#!/usr/bin/env bash
# Open Brain — Cross-platform installer (macOS + Linux)
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/jebus197/OpenBrain/main/scripts/install.sh | bash
#   or:
#   ./scripts/install.sh
#
# What it does:
#   1. Detects OS (macOS / Linux)
#   2. Checks for Python 3.9+ (searches common install locations if not in PATH)
#   3. Checks prerequisites (PostgreSQL, pgvector)
#   4. Clones the repo (or uses existing checkout)
#   5. Creates virtualenv and installs dependencies
#   6. Launches the interactive setup wizard
#
# Windows users: use scripts/install.ps1 instead.

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[92m'
YELLOW='\033[93m'
RED='\033[91m'
CYAN='\033[96m'
RESET='\033[0m'

ok()   { echo -e "  ${GREEN}OK${RESET} $1"; }
warn() { echo -e "  ${YELLOW}!!${RESET} $1"; }
fail() { echo -e "  ${RED}FAIL${RESET} $1"; }

echo -e "\n${BOLD}${CYAN}  Open Brain — Installer${RESET}\n"

# ---------------------------------------------------------------------------
# 0. OS detection
# ---------------------------------------------------------------------------

OS="$(uname -s)"
case "$OS" in
    Darwin)  OS_NAME="macOS" ;;
    Linux)   OS_NAME="Linux" ;;
    CYGWIN*|MINGW*|MSYS*)
        echo -e "  ${YELLOW}Windows detected.${RESET}"
        echo "  Please use the PowerShell installer instead:"
        echo "    .\\scripts\\install.ps1"
        echo ""
        echo "  Or from PowerShell:"
        echo "    Set-ExecutionPolicy -Scope Process Bypass; .\\scripts\\install.ps1"
        exit 1
        ;;
    *)
        warn "Unknown OS: $OS — proceeding anyway (may need manual adjustments)"
        OS_NAME="$OS"
        ;;
esac

ok "Operating system: $OS_NAME"

# ---------------------------------------------------------------------------
# 1. Python check — PATH first, then OS-specific common locations
# ---------------------------------------------------------------------------

echo -e "\n  ${BOLD}Checking prerequisites...${RESET}"

_check_python_version() {
    # Returns 0 if $1 is python3.9+, 1 otherwise
    local cmd="$1"
    local major minor
    major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null) || return 1
    minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null) || return 1
    [ "$major" -ge 3 ] && [ "$minor" -ge 9 ]
}

PYTHON=""

# Try PATH first
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null && _check_python_version "$cmd"; then
        PYTHON="$cmd"
        break
    fi
done

# If not in PATH, search OS-specific locations
if [ -z "$PYTHON" ]; then
    SEARCH_DIRS=()
    case "$OS" in
        Darwin)
            SEARCH_DIRS=(
                /opt/homebrew/bin
                /usr/local/bin
                /Library/Frameworks/Python.framework/Versions/*/bin
                /opt/homebrew/Cellar/python@3.*/*/bin
                /usr/local/Cellar/python@3.*/*/bin
            )
            # pyenv
            [ -d "$HOME/.pyenv/shims" ] && SEARCH_DIRS+=("$HOME/.pyenv/shims")
            [ -d "$HOME/.pyenv/versions" ] && SEARCH_DIRS+=("$HOME"/.pyenv/versions/3.*/bin)
            ;;
        Linux)
            SEARCH_DIRS=(
                /usr/bin
                /usr/local/bin
                /snap/bin
            )
            # Versioned system pythons (deadsnakes, etc.)
            for v in 13 12 11 10 9; do
                [ -x "/usr/bin/python3.$v" ] && SEARCH_DIRS+=("/usr/bin")
            done
            # pyenv
            [ -d "$HOME/.pyenv/shims" ] && SEARCH_DIRS+=("$HOME/.pyenv/shims")
            [ -d "$HOME/.pyenv/versions" ] && SEARCH_DIRS+=("$HOME"/.pyenv/versions/3.*/bin)
            ;;
    esac

    FOUND_PYTHON=""
    FOUND_DIR=""
    for dir_pattern in "${SEARCH_DIRS[@]}"; do
        # Handle glob patterns
        for dir in $dir_pattern; do
            [ -d "$dir" ] || continue
            for name in python3 python; do
                candidate="$dir/$name"
                if [ -x "$candidate" ] && _check_python_version "$candidate"; then
                    FOUND_PYTHON="$candidate"
                    FOUND_DIR="$dir"
                    break 3
                fi
            done
        done
    done

    if [ -n "$FOUND_PYTHON" ]; then
        version=$("$FOUND_PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        echo ""
        echo -e "  ${YELLOW}Python $version found at: $FOUND_PYTHON${RESET}"
        echo "  but its directory is not in your PATH."
        echo ""
        echo "  To fix this for the current session, run:"
        echo -e "    ${BOLD}export PATH=\"$FOUND_DIR:\$PATH\"${RESET}"
        echo ""
        case "$OS" in
            Darwin)
                echo "  To make it permanent, add that line to ~/.zshrc (or ~/.bash_profile):"
                echo -e "    ${BOLD}echo 'export PATH=\"$FOUND_DIR:\$PATH\"' >> ~/.zshrc${RESET}"
                ;;
            Linux)
                echo "  To make it permanent, add that line to ~/.bashrc (or ~/.profile):"
                echo -e "    ${BOLD}echo 'export PATH=\"$FOUND_DIR:\$PATH\"' >> ~/.bashrc${RESET}"
                ;;
        esac
        echo ""
        read -p "  Press Enter after updating your PATH to retry, or Ctrl-C to exit... " -r
        echo ""

        # Retry
        for cmd in python3 python; do
            if command -v "$cmd" &>/dev/null && _check_python_version "$cmd"; then
                PYTHON="$cmd"
                break
            fi
        done

        # If still not in PATH, use the found path directly
        if [ -z "$PYTHON" ]; then
            PYTHON="$FOUND_PYTHON"
            warn "Using $FOUND_PYTHON directly (not in PATH — consider updating PATH as shown above)"
        fi
    fi
fi

if [ -z "$PYTHON" ]; then
    fail "Python 3.9+ not found."
    echo ""
    case "$OS" in
        Darwin)
            echo "  Install options for macOS:"
            echo "    brew install python@3.12"
            echo "    or download from https://python.org"
            ;;
        Linux)
            echo "  Install options for Linux:"
            echo "    Ubuntu/Debian: sudo apt install python3 python3-venv"
            echo "    Fedora/RHEL:   sudo dnf install python3"
            echo "    Arch:          sudo pacman -S python"
            echo "    or download from https://python.org"
            ;;
        *)
            echo "  Install Python 3.9+ from https://python.org"
            ;;
    esac
    exit 1
fi

version=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python $version ($PYTHON)"

# ---------------------------------------------------------------------------
# 2. PostgreSQL check
# ---------------------------------------------------------------------------

if command -v psql &>/dev/null; then
    pg_version=$(psql --version 2>/dev/null | head -1)
    ok "PostgreSQL: $pg_version"
else
    warn "PostgreSQL not found. Install it before running the setup wizard."
    case "$OS" in
        Darwin)
            echo "    brew install postgresql@16 && brew services start postgresql@16"
            ;;
        Linux)
            echo "    Ubuntu/Debian: sudo apt install postgresql postgresql-contrib"
            echo "    Fedora/RHEL:   sudo dnf install postgresql-server postgresql-contrib"
            echo "    Arch:          sudo pacman -S postgresql"
            ;;
    esac
    echo ""
fi

# pgvector check
if command -v psql &>/dev/null; then
    if psql -d postgres -c "SELECT 1 FROM pg_available_extensions WHERE name = 'vector';" --no-psqlrc -t -q 2>/dev/null | grep -q 1; then
        ok "pgvector extension available"
    else
        warn "pgvector not found. Install it before running the setup wizard."
        case "$OS" in
            Darwin)
                echo "    brew install pgvector"
                ;;
            Linux)
                echo "    Ubuntu/Debian: sudo apt install postgresql-16-pgvector"
                echo "    Fedora/RHEL:   see https://github.com/pgvector/pgvector#linux"
                echo "    Arch:          yay -S postgresql-pgvector"
                ;;
        esac
        echo ""
    fi
fi

# ---------------------------------------------------------------------------
# 3. Get the code
# ---------------------------------------------------------------------------

echo ""
echo -e "  ${BOLD}Getting Open Brain...${RESET}"

INSTALL_DIR="${OPEN_BRAIN_DIR:-$HOME/OpenBrain}"

if [ -d "$INSTALL_DIR/open_brain/__init__.py" ] || [ -f "$INSTALL_DIR/pyproject.toml" ]; then
    ok "Using existing installation at $INSTALL_DIR"
    cd "$INSTALL_DIR"
elif command -v git &>/dev/null; then
    echo "  Installing to: $INSTALL_DIR"
    if [ -d "$INSTALL_DIR" ]; then
        cd "$INSTALL_DIR"
        git pull --ff-only 2>/dev/null || true
        ok "Updated existing repo"
    else
        git clone https://github.com/jebus197/OpenBrain.git "$INSTALL_DIR"
        cd "$INSTALL_DIR"
        ok "Cloned repository"
    fi
else
    fail "git not found. Install git or clone the repo manually."
    exit 1
fi

# ---------------------------------------------------------------------------
# 4. Virtual environment + dependencies
# ---------------------------------------------------------------------------

echo ""
echo -e "  ${BOLD}Setting up Python environment...${RESET}"

VENV_DIR="$INSTALL_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    $PYTHON -m venv "$VENV_DIR"
    ok "Created virtualenv at $VENV_DIR"
else
    ok "Virtualenv exists at $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

pip install --upgrade pip -q
ok "pip updated"

pip install -e ".[dev]" -q 2>/dev/null || pip install -e . -q
ok "Dependencies installed"

# ---------------------------------------------------------------------------
# 5. Launch wizard
# ---------------------------------------------------------------------------

echo ""
echo -e "  ${BOLD}${GREEN}Installation complete.${RESET}"
echo ""
echo "  To activate the environment:"
echo "    source $VENV_DIR/bin/activate"
echo ""

read -p "  Launch setup wizard now? [Y/n] " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Nn]$ ]]; then
    echo "  Run 'ob-setup' later to configure Open Brain."
else
    $PYTHON -m open_brain.setup_wizard
fi
