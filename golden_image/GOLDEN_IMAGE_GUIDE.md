# 골든 이미지 생성 가이드

## 개요

골든 이미지는 OS + RaspLab 소프트웨어가 모두 설치된 완성형 SD 카드 이미지입니다.
한 번만 수동으로 만들어두면, 이후 양산 시 이 이미지를 SD 카드에 굽기만 하면 됩니다.

## 준비물

- Raspberry Pi Zero 2W
- microSD 카드 (16GB 이상 권장)
- SD 카드 리더 (PC용)
- USB 케이블 (Pi ↔ PC)
- WiFi 연결 (초기 설치 시에만 필요)

## 1단계: Raspberry Pi OS 설치

1. [Raspberry Pi Imager](https://www.raspberrypi.com/software/) 다운로드 및 실행
2. OS 선택: **Raspberry Pi OS Lite (64-bit)** 권장
3. 설정 (톱니바퀴):
   - 호스트명: `rasplab`
   - SSH 활성화
   - WiFi 설정 (SSID/비밀번호)
   - 사용자: `pi` / 비밀번호 설정
4. SD 카드에 쓰기

## 2단계: Pi 부팅 및 소프트웨어 설치

```bash
# SSH 접속
ssh pi@rasplab.local

# 프로젝트 클론
git clone https://github.com/chungddong/rpictestsc.git /tmp/rpicapp
cd /tmp/rpicapp/pi

# 전체 설치 (RNDIS + Device Info 서버 포함)
sudo bash setup.sh
```

## 3단계: RNDIS 동작 확인

1. Pi를 USB로 PC에 연결
2. 재부팅: `sudo reboot`
3. PC에서 확인:
   - 장치 관리자에 "RNDIS" 또는 "Linux USB Ethernet" 어댑터 확인
   - 해당 어댑터에 IP 설정: `192.168.7.1`, 서브넷 `255.255.255.0`
   - `ping 192.168.7.2` 성공 확인
4. Device Info API 확인:
   ```
   curl http://192.168.7.2:5000/device-info
   ```

## 4단계: 이미지 덤프 준비

```bash
# Pi에서 실행 (SSH 접속 상태에서)
cd /tmp/rpicapp/pi/golden_image
sudo bash prepare_for_imaging.sh
# Pi가 자동으로 종료됩니다
```

## 5단계: SD 카드 이미지 덤프

1. Pi에서 SD 카드를 뺀다
2. SD 카드를 PC의 SD 리더에 넣는다
3. **관리자 권한** PowerShell에서:

```powershell
# 디스크 번호 확인
Get-Disk | Where-Object { $_.BusType -eq 'USB' -or $_.BusType -eq 'SD' }

# 덤프 실행 (디스크 번호를 확인 후 입력)
.\dump_sd_windows.ps1 -DiskNumber 3 -OutputPath .\ttlak-golden.img
```

## 6단계: 완성

`ttlak-golden.img` 파일이 생성됩니다. 이 파일을 `launcher/assets/os/` 에 배치하면
양산 시 사용할 수 있습니다.

## 양산 절차

1. Raspberry Pi Imager로 `ttlak-golden.img`를 새 SD 카드에 굽기
2. SD 카드를 Pi Zero 2W에 넣기
3. USB로 PC에 연결
4. `ttl serve` 실행 → 웹 대시보드에서 기기 정보 확인 + 등록

## 골든 이미지 업데이트

소프트웨어가 변경되면 골든 이미지를 다시 만들어야 합니다:
1. 기존 골든 이미지로 Pi 부팅
2. `git pull` + `setup.sh` 재실행
3. 4~5단계 반복
