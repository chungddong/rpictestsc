#!/bin/bash

# RaspLab 라즈베리파이 자동 설치 스크립트
# 용법: sudo bash setup.sh
# 또는: sudo bash -c "curl -sSL https://raw.githubusercontent.com/username/rasplab/main/pi/setup.sh | bash"

set -e  # 오류 발생 시 즉시 종료

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 RaspLab 라즈베리파이 자동 설치"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ─── 1단계: 시스템 패키지 설치 ────────────────────────────────────────
echo ""
echo "[1/5] 시스템 패키지 업데이트 및 설치..."
sudo apt update
sudo apt install -y python3-pip python3-dbus bluez bluetooth libdbus-1-dev \
                   python3-gpiozero python3-lgpio libdbus-glib-1-dev

echo "✓ 시스템 패키지 설치 완료"

# ─── 2단계: 파일 복사 (git clone 또는 직접 경로) ────────────────────────────
echo ""
echo "[2/5] 파일 복사..."

if [ ! -d "/opt/rasplab" ]; then
  echo "  → 저장소에서 복사 중..."
  if command -v git &> /dev/null; then
    # Git으로 복제
    cd /tmp
    git clone https://github.com/username/rasplab.git rasplab-temp
    sudo mkdir -p /opt/rasplab
    sudo cp -r rasplab-temp/pi/* /opt/rasplab/
    rm -rf rasplab-temp
  else
    # 또는 현재 디렉토리에서 복사 (로컬 설치 시)
    sudo mkdir -p /opt/rasplab
    sudo cp ./* /opt/rasplab/
  fi
  echo "  → 파일 복사 완료"
else
  echo "  → /opt/rasplab 이미 존재 (스킵)"
fi

# ─── 3단계: Python 가상환경 생성 및 bless 설치 ────────────────────────
echo ""
echo "[3/5] Python 가상환경 및 bless 설치..."

if [ ! -d "/opt/rasplab/venv" ]; then
  sudo python3 -m venv /opt/rasplab/venv --system-site-packages
  echo "  → 가상환경 생성 완료"
fi

# bless 설치
sudo /opt/rasplab/venv/bin/pip install --upgrade pip setuptools wheel
sudo /opt/rasplab/venv/bin/pip install bless "qrcode[pil]" pillow

echo "✓ Python 가상환경 및 bless 설치 완료"

# ─── 4단계: BlueZ 서비스 시작 ────────────────────────────────────────
echo ""
echo "[4/5] BlueZ 서비스 시작..."

sudo systemctl restart bluetooth
sleep 2

# HCI 활성화
if command -v hciconfig &> /dev/null; then
  BLE_DEVICE=$(hciconfig | grep hci | head -1 | awk '{print $1}')
  if [ -n "$BLE_DEVICE" ]; then
    sudo hciconfig $BLE_DEVICE up || true
    echo "  → $BLE_DEVICE 활성화"
  fi
fi

echo "✓ BlueZ 준비 완료"

# ─── 5단계: systemd 서비스 등록 ────────────────────────────────────────
echo ""
echo "[5/5] systemd 서비스 등록..."

# rasplab.service 파일 확인 및 복사
if [ ! -f "/opt/rasplab/rasplab.service" ]; then
  echo "  ⚠ rasplab.service 파일이 없습니다. 수동으로 생성해주세요."
  cat > /tmp/rasplab.service << 'EOF'
[Unit]
Description=RaspLab BLE Daemon
After=bluetooth.target
Wants=bluetooth.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/rasplab
ExecStart=/opt/rasplab/venv/bin/python3 /opt/rasplab/raspi_ble_daemon.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
  sudo cp /tmp/rasplab.service /etc/systemd/system/
  echo "  → 서비스 파일 생성 완료 (/tmp/rasplab.service 참고)"
else
  sudo cp /opt/rasplab/rasplab.service /etc/systemd/system/
  echo "  → 서비스 파일 복사 완료"
fi

sudo systemctl daemon-reload
sudo systemctl enable rasplab
sudo systemctl start rasplab

# 서비스 상태 확인
sleep 2
if sudo systemctl is-active --quiet rasplab; then
  echo "✓ systemd 서비스 등록 및 시작 완료"
else
  echo "⚠ 서비스 시작 실패. 로그 확인:"
  echo "   sudo journalctl -u rasplab -n 20"
fi

# ─── 완료 ────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ RaspLab 설치 완료!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "[다음 단계]"
echo "1. BLE 데몬 상태 확인:"
echo "   sudo systemctl status rasplab"
echo ""
echo "2. 실시간 로그 확인:"
echo "   sudo journalctl -u rasplab -f"
echo ""
echo "3. QR 코드 생성 (선택):"
echo "   sudo /opt/rasplab/venv/bin/python3 /opt/rasplab/generate_qr.py"
echo ""
echo "4. 폰 앱에서 BLE 검색 후 RaspLab-XXXX 연결"
echo ""
