# Open Brain — Windows PowerShell Installer
#
# Usage:
#   .\scripts\install.ps1
#
# If execution policy blocks it:
#   Set-ExecutionPolicy -Scope Process Bypass; .\scripts\install.ps1
#
# What it does:
#   1. Checks for Python 3.9+ (searches common install locations if not in PATH)
#   2. Checks prerequisites (PostgreSQL, pgvector)
#   3. Clones the repo (or uses existing checkout)
#   4. Creates virtualenv and installs dependencies
#   5. Launches the interactive setup wizard
#
# macOS/Linux users: use scripts/install.sh instead.

$ErrorActionPreference = "Stop"

function Write-Ok($msg)   { Write-Host "  OK " -ForegroundColor Green -NoNewline; Write-Host $msg }
function Write-Warn($msg) { Write-Host "  !! " -ForegroundColor Yellow -NoNewline; Write-Host $msg }
function Write-Fail($msg) { Write-Host "  FAIL " -ForegroundColor Red -NoNewline; Write-Host $msg }

Write-Host ""
Write-Host "  Open Brain - Installer" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Python check
# ---------------------------------------------------------------------------

Write-Host "  Checking prerequisites..." -ForegroundColor White

function Test-PythonVersion($cmd) {
    try {
        $major = & $cmd -c "import sys; print(sys.version_info.major)" 2>$null
        $minor = & $cmd -c "import sys; print(sys.version_info.minor)" 2>$null
        return ([int]$major -ge 3) -and ([int]$minor -ge 9)
    } catch {
        return $false
    }
}

$Python = $null

# Try PATH first
foreach ($cmd in @("python3", "python", "py")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found -and (Test-PythonVersion $cmd)) {
        $Python = $cmd
        break
    }
}

# If not in PATH, search common Windows locations
if (-not $Python) {
    $searchDirs = @(
        # python.org installer
        "$env:LOCALAPPDATA\Programs\Python\Python3*"
        # System-wide python.org
        "C:\Python3*"
        # Microsoft Store
        "$env:LOCALAPPDATA\Microsoft\WindowsApps"
        # Scoop
        "$env:USERPROFILE\scoop\apps\python\current"
        "$env:USERPROFILE\scoop\apps\python\current\Scripts"
        # Chocolatey
        "C:\ProgramData\chocolatey\bin"
        # Anaconda / Miniconda
        "$env:USERPROFILE\anaconda3"
        "$env:USERPROFILE\miniconda3"
        "$env:LOCALAPPDATA\anaconda3"
        "$env:LOCALAPPDATA\miniconda3"
    )

    $foundPython = $null
    $foundDir = $null

    foreach ($dirPattern in $searchDirs) {
        foreach ($dir in (Resolve-Path $dirPattern -ErrorAction SilentlyContinue)) {
            foreach ($name in @("python3.exe", "python.exe")) {
                $candidate = Join-Path $dir $name
                if (Test-Path $candidate) {
                    if (Test-PythonVersion $candidate) {
                        $foundPython = $candidate
                        $foundDir = $dir.ToString()
                        break
                    }
                }
            }
            if ($foundPython) { break }
        }
        if ($foundPython) { break }
    }

    if ($foundPython) {
        $ver = & $foundPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        Write-Host ""
        Write-Warn "Python $ver found at: $foundPython"
        Write-Host "  but its directory is not in your PATH."
        Write-Host ""
        Write-Host "  To fix for the current session:" -ForegroundColor White
        Write-Host "    `$env:PATH += `";$foundDir`"" -ForegroundColor White
        Write-Host ""
        Write-Host "  To fix permanently:" -ForegroundColor White
        Write-Host "    [Environment]::SetEnvironmentVariable('PATH', `$env:PATH + ';$foundDir', 'User')" -ForegroundColor White
        Write-Host ""
        Read-Host "  Press Enter after updating your PATH to retry, or Ctrl-C to exit"
        Write-Host ""

        # Retry from PATH
        foreach ($cmd in @("python3", "python", "py")) {
            $found = Get-Command $cmd -ErrorAction SilentlyContinue
            if ($found -and (Test-PythonVersion $cmd)) {
                $Python = $cmd
                break
            }
        }

        # Fall back to found path directly
        if (-not $Python) {
            $Python = $foundPython
            Write-Warn "Using $foundPython directly (not in PATH)"
        }
    }
}

if (-not $Python) {
    Write-Fail "Python 3.9+ not found."
    Write-Host ""
    Write-Host "  Install options for Windows:"
    Write-Host "    winget install Python.Python.3.12"
    Write-Host "    choco install python3"
    Write-Host "    scoop install python"
    Write-Host "    or download from https://python.org"
    Write-Host ""
    Write-Host "  IMPORTANT: Check 'Add Python to PATH' during installation."
    exit 1
}

$version = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Ok "Python $version ($Python)"

# ---------------------------------------------------------------------------
# 2. PostgreSQL check
# ---------------------------------------------------------------------------

$psql = Get-Command psql -ErrorAction SilentlyContinue
if ($psql) {
    $pgVer = (& psql --version 2>$null) -split "`n" | Select-Object -First 1
    Write-Ok "PostgreSQL: $pgVer"
} else {
    Write-Warn "PostgreSQL not found. Install it before running the setup wizard."
    Write-Host "    Download: https://www.postgresql.org/download/windows/"
    Write-Host "    Or: winget install PostgreSQL.PostgreSQL.16"
    Write-Host "    Or: choco install postgresql16"
    Write-Host "    Or: scoop install postgresql"
    Write-Host ""
}

# pgvector check
if ($psql) {
    try {
        $result = & psql -d postgres -c "SELECT 1 FROM pg_available_extensions WHERE name = 'vector';" --no-psqlrc -t -q 2>$null
        if ($result -match "1") {
            Write-Ok "pgvector extension available"
        } else {
            Write-Warn "pgvector not found. Install it before running the setup wizard."
            Write-Host "    See: https://github.com/pgvector/pgvector#windows"
            Write-Host ""
        }
    } catch {
        Write-Warn "Could not check pgvector (PostgreSQL server may not be running)"
    }
}

# ---------------------------------------------------------------------------
# 3. Get the code
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "  Getting Open Brain..." -ForegroundColor White

$installDir = if ($env:OPEN_BRAIN_DIR) { $env:OPEN_BRAIN_DIR } else { "$env:USERPROFILE\OpenBrain" }

if ((Test-Path "$installDir\pyproject.toml") -or (Test-Path "$installDir\open_brain\__init__.py")) {
    Write-Ok "Using existing installation at $installDir"
    Set-Location $installDir
} elseif (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Host "  Installing to: $installDir"
    if (Test-Path $installDir) {
        Set-Location $installDir
        git pull --ff-only 2>$null
        Write-Ok "Updated existing repo"
    } else {
        git clone https://github.com/jebus197/OpenBrain.git $installDir
        Set-Location $installDir
        Write-Ok "Cloned repository"
    }
} else {
    Write-Fail "git not found. Install git or clone the repo manually."
    exit 1
}

# ---------------------------------------------------------------------------
# 4. Virtual environment + dependencies
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "  Setting up Python environment..." -ForegroundColor White

$venvDir = "$installDir\.venv"

if (-not (Test-Path $venvDir)) {
    & $Python -m venv $venvDir
    Write-Ok "Created virtualenv at $venvDir"
} else {
    Write-Ok "Virtualenv exists at $venvDir"
}

& "$venvDir\Scripts\Activate.ps1"

& pip install --upgrade pip -q 2>$null
Write-Ok "pip updated"

try {
    & pip install -e ".[dev]" -q 2>$null
} catch {
    & pip install -e . -q
}
Write-Ok "Dependencies installed"

# ---------------------------------------------------------------------------
# 5. Launch wizard
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "  Installation complete." -ForegroundColor Green
Write-Host ""
Write-Host "  To activate the environment:"
Write-Host "    $venvDir\Scripts\Activate.ps1"
Write-Host ""

$response = Read-Host "  Launch setup wizard now? [Y/n]"
if ($response -match '^[Nn]$') {
    Write-Host "  Run 'ob-setup' later to configure Open Brain."
} else {
    & $Python -m open_brain.setup_wizard
}
