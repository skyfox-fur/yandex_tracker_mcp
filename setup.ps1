# Yandex Tracker MCP — First-time setup (Windows)
# Usage: .\setup.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== Yandex Tracker MCP Setup ===" -ForegroundColor Green
Write-Host ""

# Check for Python
try {
    $pythonVersion = python --version 2>&1 | Select-Object -First 1
    Write-Host "✓ Found $pythonVersion"
} catch {
    Write-Host "Error: python is required but not installed." -ForegroundColor Red
    Write-Host "Please install Python 3.10 or later from https://www.python.org"
    exit 1
}

# Create virtual environment
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
} else {
    Write-Host "✓ Virtual environment already exists"
}

# Activate virtual environment
& ".\.venv\Scripts\Activate.ps1"
Write-Host "✓ Virtual environment activated"

# Upgrade pip
Write-Host "Upgrading pip..."
python -m pip install --quiet --upgrade pip setuptools wheel

# Install dependencies from pyproject.toml
Write-Host "Installing dependencies..."
pip install --quiet -e .

Write-Host ""
Write-Host "=== Setup complete! ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Create .env from .env.example:"
Write-Host "     Copy-Item .env.example .env"
Write-Host "  2. Edit .env with your Tracker credentials (TRACKER_TOKEN, TRACKER_ORG_ID)"
Write-Host "  3. Test the connection:"
Write-Host "     .\.venv\Scripts\Activate.ps1"
Write-Host "     python -c 'import server; print(""OK"")'"
Write-Host "  4. Add to Claude Code:"
Write-Host "     claude mcp add yandex-tracker --scope user ``"
Write-Host "       -e TRACKER_TOKEN=`$YOUR_TOKEN ``"
Write-Host "       -e TRACKER_ORG_ID=`$YOUR_ORG_ID ``"
Write-Host "       -- `$PWD\.venv\Scripts\python.exe `$PWD\server.py"
Write-Host ""
Write-Host "See README.md and CLAUDE.md for more details."
