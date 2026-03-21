#!/usr/bin/env bash
set -euo pipefail

LOG_DIR=/var/log/ttlak
STATE_DIR=/var/lib/ttlak
mkdir -p "$LOG_DIR" "$STATE_DIR"
exec > >(tee -a "$LOG_DIR/firstboot.log") 2>&1

BOOT_CFG=/boot/firmware/ttlak.env
if [ -f /boot/ttlak.env ]; then
  BOOT_CFG=/boot/ttlak.env
fi

REPO_URL="https://github.com/chungddong/rpictestsc.git"
REPO_REF="main"
INSTALL_DIR="/opt/rasplab-src"

if [ -f "$BOOT_CFG" ]; then
  # shellcheck disable=SC1090
  source "$BOOT_CFG"
fi

echo "[firstboot] repo=$REPO_URL ref=$REPO_REF"

if [ -f "$STATE_DIR/success.flag" ]; then
  echo "[firstboot] already provisioned"
  exit 0
fi

apt-get update
apt-get install -y git curl python3-venv

if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" fetch --all --tags
  git -C "$INSTALL_DIR" checkout "$REPO_REF"
  git -C "$INSTALL_DIR" pull --ff-only || true
else
  git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$INSTALL_DIR"
fi

if [ -f "$INSTALL_DIR/pi/setup.sh" ]; then
  bash "$INSTALL_DIR/pi/setup.sh"
fi

echo "[firstboot] smoke test"
python3 - <<'PY'
print("ttlak firstboot smoke ok")
PY

touch "$STATE_DIR/success.flag"
echo "[firstboot] completed"
