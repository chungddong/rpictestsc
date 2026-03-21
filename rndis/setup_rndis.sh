#!/bin/bash
# USB RNDIS 가젯 네트워킹 설정 스크립트
# Pi Zero 2W에서 USB로 PC와 네트워크 통신을 가능하게 합니다.
# 용법: sudo bash setup_rndis.sh

set -euo pipefail

echo "[RNDIS] USB 가젯 네트워킹 설정 시작..."

# 1. dwc2 오버레이 활성화
CONFIG_FILE="/boot/firmware/config.txt"
if [ ! -f "$CONFIG_FILE" ]; then
    CONFIG_FILE="/boot/config.txt"
fi

if ! grep -q "^dtoverlay=dwc2" "$CONFIG_FILE" 2>/dev/null; then
    echo "dtoverlay=dwc2" | sudo tee -a "$CONFIG_FILE" > /dev/null
    echo "  -> dtoverlay=dwc2 추가 완료"
else
    echo "  -> dtoverlay=dwc2 이미 설정됨"
fi

# 2. 커널 모듈 등록
for mod in dwc2 g_ether; do
    if ! grep -q "^${mod}$" /etc/modules 2>/dev/null; then
        echo "$mod" | sudo tee -a /etc/modules > /dev/null
        echo "  -> ${mod} 모듈 추가 완료"
    else
        echo "  -> ${mod} 모듈 이미 등록됨"
    fi
done

# 3. systemd-networkd로 usb0 고정 IP 설정
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
sudo cp "$SCRIPT_DIR/usb0.network" /etc/systemd/network/usb0.network
echo "  -> usb0.network 설정 복사 완료"

sudo systemctl enable systemd-networkd
echo "  -> systemd-networkd 활성화 완료"

# 4. dhcpcd에서 usb0 제외 (충돌 방지)
DHCPCD_CONF="/etc/dhcpcd.conf"
if [ -f "$DHCPCD_CONF" ]; then
    if ! grep -q "^denyinterfaces usb0" "$DHCPCD_CONF" 2>/dev/null; then
        echo "denyinterfaces usb0" | sudo tee -a "$DHCPCD_CONF" > /dev/null
        echo "  -> dhcpcd에서 usb0 제외 완료"
    else
        echo "  -> dhcpcd usb0 제외 이미 설정됨"
    fi
fi

echo "[RNDIS] 설정 완료. 재부팅 후 USB 연결 시 192.168.7.2로 접근 가능합니다."
echo "  PC 측에서 RNDIS 어댑터에 192.168.7.1/24 IP를 설정해야 합니다."
