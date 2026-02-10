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
sudo apt install -y ffmpeg mpv espeak-ng jackd2 libjack-jackd2-dev zita-ajbridge

# Add user to required groups
for grp in input audio; do
    if ! groups "$USER" | grep -q "\b${grp}\b"; then
        echo "Adding $USER to ${grp} group..."
        sudo usermod -aG "$grp" "$USER"
    fi
done
echo "(Log out and back in if group membership was changed.)"

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

# Create data directories
mkdir -p ~/.auto-kj/cache
mkdir -p ~/.auto-kj/models

echo ""
echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Place your wakeword model at ~/.auto-kj/models/hey_karaoke.onnx"
echo "     (plus .onnx.data if exported with external tensors)"
echo "  2. Optional: set ANTHROPIC_API_KEY in ~/.env for AI command parsing"
echo "  3. Run with:"
echo "       source .venv/bin/activate"
echo "       python auto-kj/main.py"
echo "  4. Or install the systemd service:"
echo "       sudo cp auto-kj.service /etc/systemd/system/"
echo "       sudo systemctl enable --now auto-kj"
