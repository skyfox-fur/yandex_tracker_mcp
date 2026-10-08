#!/usr/bin/env bash
set -euo pipefail

# Yandex Tracker MCP — First-time setup
# Usage: ./setup.sh

echo "=== Yandex Tracker MCP Setup ==="
echo ""

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but not installed."
    echo "Please install Python 3.10 or later and try again."
    exit 1
fi

python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Found Python $python_version"

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
source .venv/bin/activate

echo "✓ Virtual environment activated"

# Upgrade pip
echo "Upgrading pip..."
pip install --quiet --upgrade pip setuptools wheel

# Install dependencies from pyproject.toml
echo "Installing dependencies..."
pip install --quiet -e .

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Create .env from .env.example:"
echo "     cp .env.example .env"
echo "  2. Edit .env with your Tracker credentials (TRACKER_TOKEN, TRACKER_ORG_ID)"
echo "  3. Test the connection:"
echo "     source .venv/bin/activate"
echo "     python -c 'import server; print(\"OK\")'"
echo "  4. Add to Claude Code:"
echo "     claude mcp add yandex-tracker --scope user \\"
echo "       -e TRACKER_TOKEN=\$YOUR_TOKEN \\"
echo "       -e TRACKER_ORG_ID=\$YOUR_ORG_ID \\"
echo "       -- \$PWD/.venv/bin/python \$PWD/server.py"
echo ""
echo "See README.md and CLAUDE.md for more details."
