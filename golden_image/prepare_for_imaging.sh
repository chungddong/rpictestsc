#!/bin/bash
# 골든 이미지 생성 전 Pi 정리 스크립트
# SD 카드를 이미지로 덤프하기 전에 이 스크립트를 실행합니다.
# 기기별 고유 데이터를 제거하고, 설치된 소프트웨어는 유지합니다.
#
# 용법: sudo bash prepare_for_imaging.sh

set -euo pipefail

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "골든 이미지 준비 스크립트"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 서비스 중지
echo "[1/6] 서비스 중지..."
sudo systemctl stop rasplab 2>/dev/null || true
sudo systemctl stop rasplab-device-info 2>/dev/null || true

# SSH 호스트 키 삭제 (첫 부팅 시 자동 재생성)
echo "[2/6] SSH 호스트 키 삭제..."
sudo rm -f /etc/ssh/ssh_host_*

# machine-id 초기화 (첫 부팅 시 재생성)
echo "[3/6] machine-id 초기화..."
sudo truncate -s 0 /etc/machine-id
sudo rm -f /var/lib/dbus/machine-id

# 로그 정리
echo "[4/6] 로그 및 임시 파일 정리..."
sudo journalctl --vacuum-time=1s 2>/dev/null || true
sudo truncate -s 0 /var/log/syslog 2>/dev/null || true
sudo truncate -s 0 /var/log/auth.log 2>/dev/null || true
sudo truncate -s 0 /var/log/dpkg.log 2>/dev/null || true
sudo rm -rf /var/log/ttlak/* 2>/dev/null || true
sudo rm -rf /tmp/*
sudo rm -f /root/.bash_history
sudo rm -f /home/pi/.bash_history
history -c 2>/dev/null || true

# firstboot 플래그 제거 (새 기기에서 다시 실행되도록)
echo "[5/6] firstboot 플래그 제거..."
sudo rm -f /var/lib/ttlak/success.flag

# apt 캐시 정리
echo "[6/6] apt 캐시 정리..."
sudo apt clean

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "준비 완료!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "다음 단계:"
echo "1. sudo shutdown -h now"
echo "2. SD 카드를 PC에 꽂고 이미지 덤프"
echo "   (Windows: dump_sd_windows.ps1 사용)"
echo ""

sudo shutdown -h now
