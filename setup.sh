#!/bin/bash

# RaspLab 라즈베리파이 자동 설치 스크립트
# 용법: sudo bash setup.sh
# 또는: sudo bash -c "curl -sSL https://raw.githubusercontent.com/username/rasplab/main/pi/setup.sh | bash"

set -euo pipefail  # 오류 발생 시 즉시 종료

REPO_RAW_BASE="${REPO_RAW_BASE:-https://raw.githubusercontent.com/chungddong/rpictestsc/main}"
REQUIRED_FILES=(
  "raspi_ble_daemon.py"
  "rasplab.service"
  "generate_qr.py"
  "requirements.txt"
  "device_manager.py"
  "platformio_bridge.py"
)

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 RaspLab 라즈베리파이 자동 설치"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ─── 1단계: 시스템 패키지 설치 ────────────────────────────────────────
echo ""
echo "[1/6] 시스템 패키지 업데이트 및 설치..."
sudo apt update
sudo apt install -y python3-pip python3-dbus bluez bluetooth libdbus-1-dev \
                   python3-gpiozero python3-lgpio libdbus-glib-1-dev rfkill qrencode \
                   git usbutils

echo "✓ 시스템 패키지 설치 완료"

# ─── 2단계: 필수 파일 준비 ────────────────────────────────────────────
echo ""
echo "[2/6] 필수 파일 준비..."

sudo mkdir -p /opt/rasplab

copy_local_files() {
  local copied=0
  for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "./${file}" ]; then
      sudo cp "./${file}" "/opt/rasplab/${file}"
      copied=$((copied + 1))
    fi
  done
  if [ "$copied" -gt 0 ]; then
    echo "  → 로컬 파일 ${copied}개 복사 완료"
    return 0
  fi
  return 1
}

download_required_files() {
  echo "  → GitHub raw에서 파일 다운로드 중..."
  for file in "${REQUIRED_FILES[@]}"; do
    if curl -fsSL "${REPO_RAW_BASE}/${file}" -o "/tmp/${file}"; then
      sudo cp "/tmp/${file}" "/opt/rasplab/${file}"
      continue
    fi

    if curl -fsSL "${REPO_RAW_BASE}/pi/${file}" -o "/tmp/${file}"; then
      sudo cp "/tmp/${file}" "/opt/rasplab/${file}"
      continue
    fi

    echo "  ✗ ${file} 다운로드 실패"
    echo "    REPO_RAW_BASE=${REPO_RAW_BASE}"
    exit 1
  done
  echo "  → GitHub raw 다운로드 완료"
}

if copy_local_files; then
  :
else
  download_required_files
fi

# ─── 3단계: Python 가상환경 생성 및 의존성 설치 ────────────────────────
echo ""
echo "[3/6] Python 가상환경 및 의존성 설치..."

if [ ! -d "/opt/rasplab/venv" ]; then
  sudo python3 -m venv /opt/rasplab/venv --system-site-packages
  echo "  → 가상환경 생성 완료"
fi

# bless, platformio, pyserial 등 설치
sudo /opt/rasplab/venv/bin/pip install --upgrade pip setuptools wheel
sudo /opt/rasplab/venv/bin/pip install bless "qrcode[pil]" pillow platformio pyserial

echo "✓ Python 가상환경 및 의존성 설치 완료"

# ─── PlatformIO 초기화 ─────────────────────────────────────────────────
echo ""
echo "  → PlatformIO 초기화 중..."

# platformio CLI 홈 디렉토리 설정
sudo mkdir -p /opt/rasplab/.platformio
sudo /opt/rasplab/venv/bin/platformio system info > /dev/null 2>&1 || true

# Arduino Uno R3 보드 자동 설치
echo "  → Arduino Uno R3 패키지 설치 중..."
sudo /opt/rasplab/venv/bin/platformio platform install atmelavr || true

echo "✓ PlatformIO 초기화 완료"

# ─── 4단계: 장치 관리 디렉토리 생성 ────────────────────────────────────
echo ""
echo "[4/6] 장치 관리 디렉토리 생성..."

sudo mkdir -p /opt/rasplab/pio-projects
sudo mkdir -p /opt/rasplab/device-db
echo "✓ 디렉토리 생성 완료"

# ─── 5단계: BlueZ 서비스 시작 ────────────────────────────────────────
echo ""
echo "[5/6] BlueZ 서비스 시작..."

sudo rfkill unblock bluetooth || true
sudo systemctl restart bluetooth
sleep 2

# HCI 활성화
if command -v hciconfig &> /dev/null; then
  BLE_DEVICE=$(hciconfig | grep hci | head -1 | awk '{print $1}')
  if [ -n "$BLE_DEVICE" ]; then
    if sudo hciconfig "$BLE_DEVICE" up; then
      echo "  → $BLE_DEVICE 활성화"
    else
      echo "  ⚠ $BLE_DEVICE 활성화 실패 (RF-kill 가능성). 계속 진행합니다."
    fi
  fi
fi

echo "✓ BlueZ 준비 완료"

# ─── 6단계: systemd 서비스 등록 ────────────────────────────────────────
echo ""
echo "[6/6] systemd 서비스 등록..."

# rasplab.service를 매번 정합한 내용으로 강제 갱신
cat > /tmp/rasplab.service << 'EOF'
[Unit]
Description=RaspLab BLE Daemon
After=bluetooth.target network.target
Wants=bluetooth.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/rasplab
ExecStartPre=/bin/sleep 2
ExecStart=/opt/rasplab/venv/bin/python3 /opt/rasplab/raspi_ble_daemon.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
sudo cp /tmp/rasplab.service /etc/systemd/system/rasplab.service
echo "  → 서비스 파일 갱신 완료"

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

# 설치 완료 후 터미널 QR 자동 출력
if [ -f "/sys/class/bluetooth/hci0/address" ]; then
  BLE_MAC=$(cat /sys/class/bluetooth/hci0/address)
  QR_DATA="rasplab://${BLE_MAC}"
  echo ""
  echo "[QR] 연결 데이터: ${QR_DATA}"
  if command -v qrencode &> /dev/null; then
    echo "[QR] 아래 코드를 앱에서 스캔하세요:"
    qrencode -t ANSIUTF8 -s 1 "${QR_DATA}" || true
  else
    echo "[QR] qrencode 미설치로 텍스트만 출력합니다."
  fi
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
echo "3. PlatformIO Arduino 프로젝트 생성:"
echo "   sudo /opt/rasplab/venv/bin/platformio project init -b uno"
echo ""
echo "4. QR 코드 생성 (선택):"
echo "   sudo /opt/rasplab/venv/bin/python3 /opt/rasplab/generate_qr.py"
echo ""
echo "5. 폰 앱에서 BLE 검색 후 RaspLab-XXXX 연결"
echo ""
echo "[주의]"
echo "- Arduino를 USB로 연결하면 자동 감지됩니다"
echo "- PlatformIO가 준비될 때까지 최대 2분이 소요될 수 있습니다"
echo ""
