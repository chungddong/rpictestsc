# RaspLab — 라즈베리파이 BLE 데몬

> Python + bless로 구현한 BLE Peripheral 서버

## 🍓 특징

- **자동 설치**: `setup.sh`로 모든 셋업 자동화
- **systemd 등록**: 부팅 시 자동 시작
- **청크 분할 수신**: 500+ 바이트 코드 재조립
- **실시간 실행**: subprocess로 코드 즉시 실행
- **stdout 캡처**: 실행 결과 BLE Notify로 전송
- **무한루프 처리**: KeyboardInterrupt 지원

## 🚀 빠른 설치

### 자동 설치 (권장)

한 줄로 모든 설정이 완료됩니다:

```bash
curl -sSL https://raw.githubusercontent.com/username/rasplab/main/pi/setup.sh | sudo bash
```

**또는** 저장소에서 클론:

```bash
git clone https://github.com/username/rasplab.git /tmp/rasplab
cd /tmp/rasplab/pi
sudo bash setup.sh
```

### 설치 완료 확인

```bash
# 상태 확인
sudo systemctl status rasplab
# Active: active (running) ✓

# 실시간 로그
sudo journalctl -u rasplab -f

# BLE 기기명 확인 (폰 앱에서 검색하면 보임)
# RaspLab-XXXX
```

## 📋 파일 설명

| 파일 | 역할 |
|------|------|
| **raspi_ble_daemon.py** | 메인 BLE 데몬 (실행 엔진) |
| **setup.sh** | 자동 설치 스크립트 |
| **rasplab.service** | systemd 서비스 파일 |
| **generate_qr.py** | QR 코드 생성 (선택) |
| **requirements.txt** | Python 의존성 (참고용) |
| **SETUP.md** | 수동 설치 상세 가이드 |

## 🔧 서비스 관리

### 상태 확인

```bash
sudo systemctl status rasplab
```

### 시작/중지

```bash
# 시작
sudo systemctl start rasplab

# 중지
sudo systemctl stop rasplab

# 재시작
sudo systemctl restart rasplab
```

### 로그 보기

```bash
# 실시간 로그 (마지막 20줄)
sudo journalctl -u rasplab -f

# 오늘 로그만
sudo journalctl -u rasplab --since today

# 특정 오류 검색
sudo journalctl -u rasplab | grep ERROR
```

### 자동 시작 설정

```bash
# 활성화 (부팅 시 자동 시작)
sudo systemctl enable rasplab

# 비활성화 (수동으로만 시작)
sudo systemctl disable rasplab

# 상태 확인
sudo systemctl is-enabled rasplab
```

## 💾 설치 위치

```
/opt/rasplab/
├── raspi_ble_daemon.py      # 메인 코드
├── generate_qr.py           # QR 생성 도구
├── rasplab.service          # systemd 파일
├── venv/                    # Python 가상환경
│   ├── bin/
│   │   └── python3          # bless 설치된 Python
│   └── lib/
│       └── site-packages/   # bless, pillow 등
└── logs/ (생성됨)
```

## 🔌 프로토콜

### BLE Service

```
Service UUID: 0000fff0-0000-1000-8000-00805f9b34fb

fff1: Write (폰 → Pi)
  데이터: 코드 청크 (최대 507B)
  
fff2: Notify (Pi → 폰)
  데이터: 실행 결과 (stdout/stderr)
  
fff3: Write (폰 → Pi)
  데이터: 제어 명령 (중지 등)
```

### 패킷 형식

```
[TYPE(1B)][SEQ(2B)][TOTAL(2B)][PAYLOAD(507B)]

TYPE:
  0x01 = 코드 청크
  0x02 = 전송 완료 (실행 시작)
  0x03 = 중지 요청
  0x04 = 결과 청크
  0x05 = 실행 완료
  0x06 = 에러
```

### 예시

```
폰 from:
  [0x01][0001][0005][import time; from...]  # 청크 1/5
  [0x01][0002][0005][gpiozero import LED...]  # 청크 2/5
  ...
  [0x02][0000][0000][]                     # 실행 시작

Pi to:
  [0x04][0001][0001][LED starting...]      # 결과 1/1
  [0x05][0000][0000][]                     # 완료
```

## 🖥️ 시스템 요구사항

| 항목 | 사양 |
|------|------|
| **모델** | Pi 4B / Pi 5 / Pi Zero 2W |
| **OS** | Raspberry Pi OS Bookworm (64-bit) |
| **Python** | 3.11+ |
| **BLE** | 내장 지원 필수 |
| **인터넷** | 초기 설치 시만 필요 |

## 🐛 트러블슈팅

### BLE 기기가 안 보임

```bash
# 1. 서비스 상태 확인
sudo systemctl status rasplab

# 2. BlueZ 재시작
sudo systemctl restart bluetooth

# 3. HCI 확인
hciconfig -a
# hci0이 없으면 Pi BLE 불가능

# 4. 거리 확인 (2m 이내)

# 5. 앱에서 폰 블루투스 끄고 다시 켜기
```

### 설치 실패

```bash
# 수동 설치로 전환
cd /tmp/rasplab/pi
sudo bash setup.sh
# 실패 시 각 단계별로 실행

# 또는 SETUP.md 참고
```

### 코드 실행 오류

```bash
# 로그 확인
sudo journalctl -u rasplab -f

# 30초 타임아웃인지 확인
# timeout: 30 초

# Python 문법 오류면 앱에서 보임
```

### bless 설치 오류

```bash
# 개발 라이브러리 설치
sudo apt install python3-dev libdbus-glib-1-dev

# 재설치
sudo /opt/rasplab/venv/bin/pip install bless --no-build-isolation
```

## 📝 Configuration

**bless 설정** (raspi_ble_daemon.py):
```python
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CODE_WRITE_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
RESULT_READ_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"
CONTROL_UUID = "0000fff3-0000-1000-8000-00805f9b34fb"
```

**실행 타임아웃** (raspi_ble_daemon.py):
```python
timeout = 30  # 초, 초과하면 프로세스 kill
```

## 🚀 업그레이드

```bash
# 코드 업데이트 (GitHub에서)
cd /opt/rasplab
git pull origin main

# 서비스 재시작
sudo systemctl restart rasplab

# 버전 확인 (로그에서)
sudo journalctl -u rasplab -n 5
```

## 📊 모니터링

실시간 모니터링 스크립트:

```bash
#!/bin/bash
watch -n 1 'sudo journalctl -u rasplab -n 20'
```

## 🔐 보안 고려사항

- ⚠️ **같은 네트워크 환경 전제**: 공용 인터넷에 노출 금지
- ⚠️ **API 키 없음**: Pi는 Claude API 호출 불필요 (폰 앱이 처리)
- ⏳ **향후 개선**: PIN 페어링, 암호화 고려

## 📚 참고

- [bless 공식](https://github.com/kevinmcalister/bless)
- [BlueZ 문서](http://www.bluez.org/)
- [systemd 가이드](https://wiki.debian.org/systemd)

## 🆘 지원

로그 파일로 시작합니다:

```bash
# 최근 100줄
sudo journalctl -u rasplab -n 100

# 시간 범위로 조회
sudo journalctl -u rasplab --since "2024-03-17 10:00:00"
```
