#!/usr/bin/env bash
# Open Brain — One-line installer
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/jebus197/OpenBrain/main/scripts/install.sh | bash
#   or:
#   ./scripts/install.sh
#
# What it does:
#   1. Checks prerequisites (Python 3.9+, PostgreSQL, pgvector)
#   2. Clones the repo (or uses existing checkout)
#   3. Creates virtualenv and installs dependencies
#   4. Launches the interactive setup wizard
#

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
# 1. Python check
# ---------------------------------------------------------------------------

echo -e "  ${BOLD}Checking prerequisites...${RESET}"

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        major=$("$cmd" -c "import sys; print(sys.version_info.major)")
        minor=$("$cmd" -c "import sys; print(sys.version_info.minor)")
        if [ "$major" -ge 3 ] && [ "$minor" -ge 9 ]; then
            PYTHON="$cmd"
            ok "Python $version"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python 3.9+ required. Install from https://python.org or via pyenv."
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. PostgreSQL check
# ---------------------------------------------------------------------------

if command -v psql &>/dev/null; then
    pg_version=$(psql --version 2>/dev/null | head -1)
    ok "PostgreSQL: $pg_version"
else
    warn "PostgreSQL not found. Install it before running the setup wizard."
    echo "    macOS:  brew install postgresql@16 && brew services start postgresql@16"
    echo "    Ubuntu: sudo apt install postgresql postgresql-contrib"
    echo ""
fi

# pgvector check
if command -v psql &>/dev/null; then
    if psql -d postgres -c "SELECT 1 FROM pg_available_extensions WHERE name = 'vector';" --no-psqlrc -t -q 2>/dev/null | grep -q 1; then
        ok "pgvector extension available"
    else
        warn "pgvector not found. Install it before running the setup wizard."
        echo "    macOS:  brew install pgvector"
        echo "    Ubuntu: sudo apt install postgresql-16-pgvector"
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
