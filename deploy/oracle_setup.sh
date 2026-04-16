#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${1:-https://github.com/cburdick28-spec/Messager.git}"
APP_DIR="/opt/messager"

echo "[1/6] Installing packages..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git ufw

echo "[2/6] Cloning/updating app..."
if [ -d "$APP_DIR/.git" ]; then
  sudo git -C "$APP_DIR" fetch --all
  sudo git -C "$APP_DIR" reset --hard origin/main
else
  sudo rm -rf "$APP_DIR"
  sudo git clone "$REPO_URL" "$APP_DIR"
fi
sudo chown -R ubuntu:ubuntu "$APP_DIR"

echo "[3/6] Creating virtual environment..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "[4/6] Installing systemd service..."
sudo cp "$APP_DIR/deploy/messager.service" /etc/systemd/system/messager.service
sudo systemctl daemon-reload
sudo systemctl enable --now messager

echo "[5/6] Opening firewall..."
sudo ufw allow OpenSSH || true
sudo ufw allow 8080/tcp || true
sudo ufw --force enable || true

echo "[6/6] Done."
echo "App status:"
sudo systemctl --no-pager status messager | head -n 12
echo ""
echo "Now open: http://<YOUR_VM_PUBLIC_IP>:8080"
echo "If Oracle network rules block traffic, open inbound TCP 8080 in Oracle Console."
