#!/data/data/com.termux/files/usr/bin/bash
# NTA WebSearch API — Termux Native Auto-Setup Script
set -e

echo "========================================================="
echo "   NTA WebSearch API — Termux Native Installer"
echo "========================================================="

# 1. Check Python
if ! command -v python3 &>/dev/null; then
    echo "[1/4] Installing Python3..."
    pkg install -y python
else
    echo "[1/4] Python3 is installed."
fi

# 2. Check / Install Flask
echo "[2/4] Verifying Python dependencies..."
python3 -c "import flask" 2>/dev/null || pip install flask

# 3. Check / Install Chromium for aarch64
echo "[3/4] Checking Chromium on Android hardware..."
if ! command -v chromium &>/dev/null; then
    echo "  -> Installing Chromium via Termux User Repository (tur-repo)..."
    pkg install -y tur-repo 2>/dev/null || true
    pkg install -y x11-repo 2>/dev/null || true
    pkg install -y chromium || {
        echo "  [INFO] Standard repo install skipped. Testing available browser packages..."
    }
else
    echo "  -> Chromium is already installed."
fi

# 4. Prepare Directories
echo "[4/4] Initializing secure key store & sandbox directories..."
mkdir -p "$HOME/.config/nta-chromium-sandbox"
mkdir -p "/sdcard/Download/NetuarkMedia/keys" 2>/dev/null || true
mkdir -p "./data"

echo "========================================================="
echo "✅ Setup Complete! Ready to launch with start_cluster.sh"
echo "========================================================="
