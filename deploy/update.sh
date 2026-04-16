#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/messager"

cd "$APP_DIR"
git fetch --all
git reset --hard origin/main
.venv/bin/pip install -r requirements.txt
sudo systemctl restart messager
sudo systemctl --no-pager status messager | head -n 12
