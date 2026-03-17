# 📡 멀티 디바이스 확장 - 구현 가이드

## 개요

Raspberry Pi를 "통합 개발 플랫폼"으로 전환하여:
- **Pi 본체**: Python 코드 원격 실행 ✅ (기존)
- **Arduino UNO R3**: C++ 펌웨어 컴파일 & 업로드 🆕
- 향후: ESP32, STM32 등 추가 가능

## 📁 새 파일 구조

```
pi/
├── setup.sh                    # PlatformIO 통합된 설치 스크립트 ✅
├── raspi_ble_daemon.py        # 멀티 디바이스 BLE 데몬 ✅
├── device_manager.py          # USB 시리얼 포트 감지/관리 ✅
├── platformio_bridge.py       # Arduino 컴파일/업로드 ✅
├── requirem...txt (기존)
└── ...(기존 파일)
```

## 🔧 설치 및 배포

### 1단계: Pi에 기존 setup.sh 실행
```bash
sudo bash setup.sh
# 또는 원라이너
curl -fsSL https://raw.githubusercontent.com/chungddong/rpictestsc/main/pi/setup.sh | sudo bash
```

**진행 단계:**
1. 시스템 패키지 (git, usbutils 포함)
2. 필수 파일 다운로드 (+device_manager.py, platformio_bridge.py)
3. Python venv + bless, platformio, pyserial 설치
4. **PlatformIO Arduino 패키지 자동 설치** ⚡
5. 디렉토리 생성: `/opt/rasplab/pio-projects`, `/opt/rasplab/device-db`
6. BlueZ 시작
7. systemd 서비스 등록 및 시작

### 2단계: Arduino 연결

USB 케이블로 Arduino UNO R3 연결하면 **자동 감지**됩니다.

**확인 명령어:**
```bash
# Pi SSH에서
python3 -c "
from device_manager import DeviceManager
dm = DeviceManager()
devices = dm.scan_devices()
for dev_id, dev in devices.items():
    print(f'{dev_id}: {dev.name} on {dev.port}')
"
```

예상 출력:
```
device_abc123: Arduino Uno R3 on /dev/ttyUSB0
```

## 🎯 BLE 프로토콜 확장

### Pi 본체 (기존)
```
[0x01] Code Chunk     → exec on Pi
[0x02] Code End       → run
[0x03] Stop           → halt
[0x04-0x06] Result    → notify app
```

### Arduino 장치 (신규)
```
[0x10] Get Device List
    요청: 16진 [10] [00] [00] []
    응답: JSON 배열
    ```json
    [
      {
        "id": "pi",
        "type": "platform",
        "name": "RaspLab Board"
      },
      {
        "id": "device_abc123",
        "type": "external",
        "name": "Arduino Uno R3",
        "port": "/dev/ttyUSB0",
        "board_type": "arduino:avr:uno",
        "serial_number": "95C345D50..."
      }
    ]
    ```

[0x11] Select Device
    요청: [11] [00] [01] [device_abc123]
    응답: "선택됨: Arduino Uno R3"

[0x12] Upload Arduino Code
    요청: [12] [seq] [total] [C++ code chunk...]
    응답: [04] 진행상황 → [05] 완료 또는 [06] 에러

[0x13] Progress (Pi → App)
    "[1/3] Compiling code..."
    "[2/3] Uploading firmware..."
    "[3/3] Success!"
```

## 💻 Pi 데몬 동작 원리

### DeviceManager (device_manager.py)

```python
dm = DeviceManager()
devices = dm.scan_devices()
# → 모든 USB 시리얼 포트 스캔
# → VID:PID로 Arduino 자동 판별
# → /opt/rasplab/device-db/devices.json 저장

device_list = dm.get_device_list()
# → BLE 응답용 JSON 형식
```

**지원 보드:**
```python
KNOWN_BOARDS = {
    (0x2341, 0x0043): "Arduino Uno R3",  # 일반적
    (0x2341, 0x8036): "Arduino Leonardo",
    (0x1a86, 0x7523): "Arduino (CH340)",
    # 추가 가능
}
```

### PlatformIOBridge (platformio_bridge.py)

```python
bridge = PlatformIOBridge()

# 1) 프로젝트 초기화 (처음 1회)
bridge.register_board("device_abc123", "uno")

# 2) 코드 컴파일 & 업로드
result = bridge.compile_and_upload(
    device_id="device_abc123",
    code_content="""
    #include <Arduino.h>
    void setup() { Serial.begin(9600); }
    void loop() { delay(1000); }
    """,
    port="/dev/ttyUSB0",
    board_type="arduino:avr:uno",
    progress_callback=lambda msg: print(msg)
)

if result['success']:
    print("✓ 업로드 완료")
else:
    print(f"✗ 오류: {result['upload'].error}")
```

**프로젝트 위치:**
```
/opt/rasplab/pio-projects/device_abc123/
├── platformio.ini          # 보드 설정
├── src/main.cpp            # 모든 코드
└── .pio/build/uno/         # 컴파일 결과
```

## 📱 Flutter 앱 변경 계획

### Step 1: 데이터 모델 추가
```dart
// lib/models/device.dart
enum DeviceType { raspberryPi, arduino, esp32 }

class Device {
  final String id;
  final String name;
  final DeviceType type;
  final String boardType;
}
```

### Step 2: 기기 선택 UI
```
[ 라즈베리파이 본체 ]  ← 클릭: Pi Python 채팅
[ 연결된 기기 ]
  ├─ Arduino Uno #1   ← 클릭: Arduino C++ 채팅
  └─ [새 기기 감지...]
```

### Step 3: BLE 메시지 전송
```dart
// device == 'pi'
sendBleMessage(0x01, code);  // Python 코드 실행

// device == Arduino
sendBleMessage(0x10, '');     // 장치 목록 요청
sendBleMessage(0x11, device_id);  // 선택
sendBleMessage(0x12, arduino_code);  // 업로드
```

### Step 4: Riverpod 상태 추가
```dart
final deviceListProvider = StreamProvider<List<Device>>((ref) {
  // BLE로부터 주기적 동기화
});

final selectedDeviceProvider = StateProvider<Device?>((ref) => null);

final uploadProgressProvider = StateProvider<String?>((ref) => null);
```

## 🧪 테스트 시나리오

### 테스트 1: 기기 감지
```bash
# Pi SSH에서
cd /opt/rasplab
python3 device_manager.py
# → Arduino Uno detected on /dev/ttyUSB0
```

### 테스트 2: LED 켜기 (Blink)
```cpp
// Flutter 앱에서 에디터에 작성
#include <Arduino.h>

void setup() {
  pinMode(13, OUTPUT);
}

void loop() {
  digitalWrite(13, HIGH);  // LED on
  delay(1000);
  digitalWrite(13, LOW);   // LED off
  delay(1000);
}
```
→ 앱에서 [업로드] 클릭
→ Pi 컴파일 & 업로드
→ Arduino에서 LED 깜빡임 확인

### 테스트 3: Serial 출력
```cpp
void setup() {
  Serial.begin(9600);
  Serial.println("Arduino Ready!");
}

void loop() {
  Serial.println("Hello from Arduino");
  delay(1000);
}
```
→ 업로드 후 앱에서 시리얼 출력 보기

## 📊 상세 흐름도

```
┌────────────────┐
│  Flutter App   │
├────────────────┤
│  기기 선택 UI   │
│  AI 대화        │
│  코드 에디터    │
└────────┬────────┘
         │ BLE 0x10-0x1F
         ▼
┌────────────────────────────────────┐
│  Raspberry Pi (RaspLab Daemon)    │
├────────────────────────────────────┤
│ [0x10] → device_manager.scan()    │
│ [0x11] → _selected_device = X     │
│ [0x12] → platformio_bridge.       │
│          compile_and_upload()     │
│                                   │
│  ├─ 1. Register project (初回)    │
│  ├─ 2. Update main.cpp            │
│  ├─ 3. platformio run (compile)   │
│  ├─ 4. platformio run -t upload   │
│  └─ 5. Notify progress → BLE      │
└────────┬────────────────────────────┘
         │ USB OTG
         ▼
┌────────────────┐
│  Arduino      │
│  USB Serial   │
│  /dev/ttyUSB0 │
└────────────────┘
```

## 🚀 다음 단계

1. **Flutter 앱 수정** (기기 선택 UI + BLE 메시지)
2. **Pi에 setup.sh 실행** (새 파일 자동 다운로드)
3. **Arduino 연결 테스트**
4. **LED Blink 업로드하며 검증**
5. **Python + Arduino 혼합 코드 테스트**

## ⚠️ 주의사항

### PlatformIO 초기 설치
- 첫 실행 시 보드 패키지 자동 다운로드 (100~200MB)
- setup.sh에서 `platformio platform install atmelavr` 미리 수행 → 배포 후 빠름

### Arduino 보드 판별
```python
# 미지의 VID:PID → "Unknown Device" + "unknown" board_type
# → Flutter에서 경고 메시지 표시 후 수동 선택 필요
# → 새로운 VID:PID는 device_manager.py에 추가
```

### 컴파일 시간
```
첫 번째 Arduino (보드 설치): ~30초
두 번째 이후 (캐시): ~5초
```

## 📝 파일 체크리스트

- [x] `setup.sh` - PlatformIO 통합
- [x] `device_manager.py` - 장치 감지
- [x] `platformio_bridge.py` - 컴파일/업로드
- [x] `raspi_ble_daemon.py` - BLE 멀티 디바이스
- [ ] Flutter 앱 수정 (진행 중)
- [ ] 통합 테스트

---

**📌 언제든 구현 진행하며 궁금한 점이 생기면 알려주세요!**
