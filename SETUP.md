# RaspLab — 라즈베리파이 셋업 가이드

## 🚀 빠른 설치 (자동)

GitHub에서 클론하고 한 줄로 모든 설정을 자동화합니다:

```bash
git clone https://github.com/username/rasplab.git /tmp/rasplab
cd /tmp/rasplab/pi
sudo bash setup.sh
```

**또는** 직접 스크립트 다운로드:

```bash
curl -sSL https://raw.githubusercontent.com/username/rasplab/main/pi/setup.sh | sudo bash
```

이 방법은 아래의 1-5단계를 모두 자동으로 처리합니다.

---

## 📋 수동 설치 (단계별)

복잡한 설정이 필요하거나 커스터마이징이 필요한 경우 아래를 따르세요.

## 필요 환경

| 항목 | 사양 |
|------|------|
| 모델 | Raspberry Pi 4B 또는 5 |
| OS | Raspberry Pi OS Bookworm (64-bit) |
| Python | 3.11 이상 |
| Bluetooth | 내장 BLE 지원 (Pi 4/5 기본 탑재) |

---

## 1단계 — 파일 복사

라즈베리파이에서 터미널을 열거나 SSH로 접속한 후:

```bash
# 방법 A: GitHub에서 클론
git clone https://github.com/username/rasplab.git /tmp/rasplab
sudo mkdir -p /opt/rasplab
sudo cp /tmp/rasplab/pi/* /opt/rasplab/

# 방법 B: USB에서 복사
# (USB를 Pi에 연결한 후)
sudo cp /mnt/usb/pi/* /opt/rasplab/

# 방법 C: PC에서 scp 전송
# (PC에서 실행)
scp pi/*.py pi/rasplab.service pi/requirements.txt pi@raspberrypi.local:/opt/rasplab/
```

---

## 2단계 — 시스템 패키지 설치

```bash
# BlueZ 및 D-Bus 개발 라이브러리
sudo apt update
sudo apt install -y python3-pip python3-dbus bluez bluetooth libdbus-1-dev \
                   python3-gpiozero python3-lgpio

# BlueZ가 실행 중인지 확인
sudo systemctl status bluetooth
# Active: active (running) 이어야 합니다
```

---

## 3단계 — Python 라이브러리 설치

```bash
cd /opt/rasplab

# bless: BLE Peripheral 라이브러리
sudo pip3 install bless

# QR 코드 생성 (선택)
sudo pip3 install "qrcode[pil]" pillow
```

> **주의:** `sudo pip3`으로 설치해야 systemd 서비스(root 권한)에서 import 가능합니다.

---

## 4단계 — 테스트 실행

```bash
cd /opt/rasplab
sudo python3 raspi_ble_daemon.py
```

정상 출력 예시:
```
[12:00:00] INFO BLE 기기명: RaspLab-A3F2
[12:00:01] INFO BLE 광고 시작: RaspLab-A3F2
[12:00:01] INFO 앱 연결 대기 중...
```

이 상태에서 **폰 앱 → 기기 검색**을 하면 `RaspLab-A3F2`가 목록에 나타납니다.

`Ctrl+C`로 중지.

---

## 5단계 — systemd 자동 시작 등록

```bash
# 서비스 파일 복사
sudo cp /opt/rasplab/rasplab.service /etc/systemd/system/

# 서비스 활성화
sudo systemctl daemon-reload
sudo systemctl enable rasplab
sudo systemctl start rasplab

# 상태 확인
sudo systemctl status rasplab
```

이후 Pi 전원을 켤 때마다 BLE 데몬이 자동으로 시작됩니다.

---

## 6단계 — QR 코드 생성 (선택)

QR 코드를 출력해두면 앱의 **QR 스캔 탭**으로 자동 연결할 수 있습니다.

```bash
cd /opt/rasplab
python3 generate_qr.py
```

출력:
```
[*] BLE MAC 주소: DC:A6:32:XX:XX:XX
[*] QR 데이터:    rasplab://DC:A6:32:XX:XX:XX
[✓] QR 이미지 저장: /tmp/rasplab_qr.png
```

`/tmp/rasplab_qr.png`를 이미지 뷰어로 열거나 인쇄합니다.

---

## 서비스 관리 명령어

```bash
# 로그 실시간 확인
sudo journalctl -u rasplab -f

# 재시작
sudo systemctl restart rasplab

# 중지
sudo systemctl stop rasplab

# 자동 시작 해제
sudo systemctl disable rasplab
```

---

## 트러블슈팅

### `bless` 설치 오류

```bash
sudo apt install -y python3-dev libdbus-glib-1-dev
sudo pip3 install bless --no-build-isolation
```

### BLE 광고가 안 됨

```bash
# BlueZ 재시작
sudo systemctl restart bluetooth

# 컨트롤러 확인
hciconfig -a
# hci0 이 보여야 함, DOWN 상태면:
sudo hciconfig hci0 up
```

### `Operation not permitted` 오류

```bash
# 반드시 sudo (root)로 실행 필요
sudo python3 raspi_ble_daemon.py
```

또는 systemd 서비스로 실행 시 `User=root`가 설정되어 있으면 자동으로 root 권한이 부여됩니다.

### 앱에서 기기가 검색되지 않음

1. Pi와 폰이 2m 이내에 있는지 확인
2. 폰 블루투스가 켜져 있는지 확인
3. 이전에 연결했던 기기면 폰 설정에서 Pi 기기 삭제 후 재시도
4. Pi에서 서비스 상태 확인: `sudo systemctl status rasplab`

### 코드 실행 후 결과가 오지 않음

실행 시간이 30초를 초과하면 자동 종료됩니다. 무한루프 코드는 반드시 `time.sleep()`과 `KeyboardInterrupt` 처리를 포함해야 합니다.

---

## 디렉토리 구조

```
/opt/rasplab/
├── raspi_ble_daemon.py   # BLE 데몬 (메인)
├── generate_qr.py        # QR 코드 생성
└── requirements.txt      # 의존 라이브러리 목록
```

---

## 통신 프로토콜 요약

```
패킷: [TYPE(1B)] [SEQ(2B)] [TOTAL(2B)] [PAYLOAD(최대 507B)]

폰 → Pi (CODE_WRITE, fff1):
  0x01: 코드 청크 전송
  0x02: 전송 완료 → 실행 시작

폰 → Pi (CONTROL, fff3):
  0x03: 실행 중지

Pi → 폰 (RESULT_READ, fff2 Notify):
  0x04: 실행 결과 청크
  0x05: 결과 전송 완료
  0x06: 에러
```
