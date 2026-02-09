#!/usr/bin/env bash
set -euo pipefail

echo "=== auto-kj installer ==="

# Check for root (needed for apt)
if [ "$EUID" -eq 0 ]; then
    echo "Don't run as root — the script will use sudo when needed."
    exit 1
fi

# System dependencies
echo ""
echo "Installing system packages..."
sudo apt update -qq
sudo apt install -y ffmpeg mpv espeak-ng portaudio19-dev

# Add user to input group for keyboard capture
if ! groups "$USER" | grep -q '\binput\b'; then
    echo ""
    echo "Adding $USER to input group (needed for keyboard capture)..."
    sudo usermod -aG input "$USER"
    echo "You'll need to log out and back in for this to take effect."
fi

# Check for uv
if ! command -v uv &>/dev/null; then
    echo ""
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Python 3.11 (spleeter/tensorflow need it)
if ! uv python find 3.11 &>/dev/null; then
    echo ""
    echo "Installing Python 3.11..."
    uv python install 3.11
fi

# Virtual environment
echo ""
echo "Creating virtual environment..."
cd "$(dirname "$0")"
uv venv --python 3.11 .venv

echo ""
echo "Installing Python dependencies..."
uv pip install -r auto-kj/requirements.txt

# Download wakeword models
echo ""
echo "Downloading wakeword models..."
.venv/bin/python -c "from openwakeword.utils import download_models; download_models()"

echo ""
echo "=== Installation complete ==="
echo ""
echo "Run with:"
echo "  source .venv/bin/activate"
echo "  python auto-kj/main.py"
