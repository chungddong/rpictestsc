#!/usr/bin/env python3
"""
RaspLab BLE Daemon (멀티 디바이스 지원)
────────────────────────────────────────────────────────────────────────

Raspberry Pi 본체 Python 코드 실행 + 연결된 Arduino/ESP32 펌웨어 관리

Flutter 앱과 BLE로 통신하며:
  [0x01-0x09] Pi Python 코드 실행 관련
  [0x10-0x1F] Arduino/ESP32 외부 장치 관련

사용법:
  sudo python3 raspi_ble_daemon.py

필요 라이브러리:
  pip install bless platformio pyserial

패킷 프로토콜:

  [Pi 코드 실행] (0x01-0x06)
  ──────────────────────────
  0x01 = 코드 청크 수신
  0x02 = 코드 전송 완료 → 실행 시작
  0x03 = 실행 중지 요청
  0x04 = 결과 청크 (Pi → 앱)
  0x05 = 실행 완료 (Pi → 앱)
  0x06 = 에러 (Pi → 앱)

  [외부 장치 제어] (0x10-0x1F)
  ───────────────────────────
  0x10 = 장치 목록 요청
    요청: [0x10] [0x00] [0x00] (payload 없음)
    응답: [0x10] [seq] [total] [JSON 장치 목록]

  0x11 = 디바이스 선택
    [0x11] [seq] [total] [device_id] 
    
  0x12 = Arduino 코드 업로드 (컴파일 + 업로드)
    [0x12] [seq] [total] [C++ 코드]
    응답: [0x13] 컴파일/업로드 진행상황

  0x13 = 진행상황 (Pi → 앱)
    [0x13] [status_code] [message]

  0x14 = 시리얼 출력 읽기
    [0x14] [device_id] [timeout_sec]
    응답: [serial output]
"""

import asyncio
import logging
import struct
import subprocess
import threading
import uuid
import os
import sys
import json
from typing import Optional

from bless import BlessServer, BlessGATTCharacteristic, GATTCharacteristicProperties, GATTAttributePermissions

# 현재 디렉토리에서 모듈 import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from device_manager import DeviceManager
from platformio_bridge import PlatformIOBridge

# ── 로깅 설정 ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('rasplab')

# ── BLE UUID 상수 (Flutter 앱과 동일) ─────────────────────────
SERVICE_UUID     = '0000fff0-0000-1000-8000-00805f9b34fb'
CODE_WRITE_UUID  = '0000fff1-0000-1000-8000-00805f9b34fb'
RESULT_READ_UUID = '0000fff2-0000-1000-8000-00805f9b34fb'
CONTROL_UUID     = '0000fff3-0000-1000-8000-00805f9b34fb'
STATUS_UUID      = '0000fff4-0000-1000-8000-00805f9b34fb'

# ── 패킷 타입 ──────────────────────────────────────────────────
# Pi Python 실행 (0x01-0x09)
PKT_CODE_CHUNK    = 0x01
PKT_CODE_END      = 0x02
PKT_STOP          = 0x03
PKT_RESULT_CHUNK  = 0x04
PKT_RESULT_END    = 0x05
PKT_ERROR         = 0x06

# 외부 장치 제어 (0x10-0x1F)
PKT_DEVICE_LIST    = 0x10
PKT_SELECT_DEVICE  = 0x11
PKT_ARDUINO_UPLOAD = 0x12
PKT_PROGRESS       = 0x13
PKT_SERIAL_READ    = 0x14

# ── 설정 ───────────────────────────────────────────────────────
BLE_PAYLOAD_SIZE     = 507      # 청크당 최대 페이로드 바이트
EXECUTION_TIMEOUT    = 30       # 코드 실행 타임아웃 (초)
DEVICE_NAME_PREFIX   = 'RaspLab'

# 전역 상태
_current_process: Optional[subprocess.Popen] = None
_process_lock = threading.Lock()
_server: Optional[BlessServer] = None

# 코드 수신 버퍼
_code_chunks: dict[int, bytes] = {}
_code_total_chunks: int = 0

# 장치 관리
_device_manager: Optional[DeviceManager] = None
_platformio_bridge: Optional[PlatformIOBridge] = None
_selected_device: Optional[str] = None  # 현재 선택된 장치 ID

# Arduino 코드 업로드 버퍼
_arduino_code_chunks: dict[int, bytes] = {}
_arduino_code_total: int = 0


# ── 유틸 함수 ──────────────────────────────────────────────────
def parse_packet(data: bytes) -> tuple[int, int, int, bytes]:
    """[TYPE(1)][SEQ(2)][TOTAL(2)][PAYLOAD] → (type, seq, total, payload)"""
    if len(data) < 5:
        raise ValueError(f'패킷이 너무 짧음: {len(data)}B')
    ptype = data[0]
    seq   = struct.unpack('>H', data[1:3])[0]
    total = struct.unpack('>H', data[3:5])[0]
    payload = data[5:]
    return ptype, seq, total, payload


def build_packet(ptype: int, seq: int, total: int, payload: bytes) -> bytes:
    """(type, seq, total, payload) → [TYPE(1)][SEQ(2)][TOTAL(2)][PAYLOAD]"""
    return bytes([ptype]) + struct.pack('>H', seq) + struct.pack('>H', total) + payload


def split_chunks(data: bytes, chunk_size: int = BLE_PAYLOAD_SIZE) -> list[bytes]:
    """데이터를 청크로 분할"""
    if len(data) == 0:
        return [b'']
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]


# ── BLE Notify 전송 ────────────────────────────────────────────
async def notify_result(server: BlessServer, data: bytes):
    """결과 데이터를 청크로 나눠 Notify로 전송"""
    if not server:
        return
    
    chunks = split_chunks(data)
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        packet = build_packet(PKT_RESULT_CHUNK, i + 1, total, chunk)
        server.get_characteristic(RESULT_READ_UUID).value = bytearray(packet)
        server.update_value(SERVICE_UUID, RESULT_READ_UUID)
        await asyncio.sleep(0.02)

    # 전송 완료 신호
    end_packet = build_packet(PKT_RESULT_END, 0, 0, b'')
    server.get_characteristic(RESULT_READ_UUID).value = bytearray(end_packet)
    server.update_value(SERVICE_UUID, RESULT_READ_UUID)


async def notify_error(server: BlessServer, message: str):
    """에러 패킷 전송"""
    if not server:
        return
    
    packet = build_packet(PKT_ERROR, 0, 0, message.encode('utf-8'))
    server.get_characteristic(RESULT_READ_UUID).value = bytearray(packet)
    server.update_value(SERVICE_UUID, RESULT_READ_UUID)


async def notify_progress(server: BlessServer, message: str):
    """진행상황 메시지 전송"""
    if not server:
        return
    
    packet = build_packet(PKT_PROGRESS, 0, 0, message.encode('utf-8'))
    server.get_characteristic(STATUS_UUID).value = bytearray(packet)
    server.update_value(SERVICE_UUID, STATUS_UUID)


# ── Pi Python 코드 실행 ────────────────────────────────────────
async def execute_code(server: BlessServer, code: str):
    """Pi에서 Python 코드 실행"""
    global _current_process

    tmp_path = '/tmp/rasplab_code.py'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        f.write(code)

    log.info(f'Pi 코드 실행 시작 ({len(code)}자)')
    log.debug(f'코드 내용:\n{code}')

    try:
        with _process_lock:
            proc = subprocess.Popen(
                [sys.executable, tmp_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
            )
            _current_process = proc

        output_lines = []
        loop = asyncio.get_event_loop()

        def read_output():
            """별도 스레드에서 출력 읽기"""
            for line in iter(proc.stdout.readline, ''):
                output_lines.append(line)

        reader_thread = threading.Thread(target=read_output, daemon=True)
        reader_thread.start()

        # 타임아웃 대기
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, proc.wait),
                timeout=EXECUTION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            proc.kill()
            output_lines.append(f'\n[TIMEOUT] {EXECUTION_TIMEOUT}초 초과로 강제 종료')
            log.warning('실행 타임아웃')

        reader_thread.join(timeout=2)

        output = ''.join(output_lines).strip()
        returncode = proc.returncode if proc.returncode is not None else -1

        if returncode == 0:
            result = output if output else '(출력 없음)'
            log.info(f'Pi 코드 실행 성공')
        elif returncode == -9:
            result = output + '\n[중지됨]' if output else '[중지됨]'
            log.info('Pi 코드 실행 중지됨')
        else:
            result = output if output else f'(returncode={returncode})'
            log.error(f'Pi 코드 실행 실패 (returncode={returncode})')

        await notify_result(server, result.encode('utf-8'))

    except Exception as e:
        err = f'Pi 실행 오류: {e}'
        log.error(err)
        await notify_error(server, err)
    finally:
        with _process_lock:
            _current_process = None
        try:
            os.remove(tmp_path)
        except OSError:
            pass


# ── Arduino 코드 컴파일 & 업로드 ──────────────────────────────
async def compile_and_upload_arduino(server: BlessServer, arduino_code: str):
    """선택된 Arduino 보드에 코드 컴파일 & 업로드"""
    global _selected_device
    
    if not _selected_device or not _platformio_bridge:
        await notify_error(server, "기기가 선택되지 않았습니다")
        return
    
    device = _device_manager.get_device(_selected_device)
    if not device:
        await notify_error(server, f"기기 정보 없음: {_selected_device}")
        return
    
    log.info(f'Arduino 코드 업로드 시작: {device.name} ({device.port})')
    
    def progress_callback(msg: str):
        """진행상황 콜백"""
        asyncio.create_task(notify_progress(server, msg))
    
    try:
        result = _platformio_bridge.compile_and_upload(
            device_id=_selected_device,
            code_content=arduino_code,
            port=device.port,
            board_type=device.board_type,
            progress_callback=progress_callback
        )
        
        if result['success']:
            output_msg = f"✓ 업로드 완료!\n\n{result['upload'].output}"
            log.info("Arduino 코드 업로드 성공")
        else:
            error_info = result['upload'].error if result['upload'] else "Unknown error"
            output_msg = f"✗ 업로드 실패\n\n{error_info}"
            log.error(f"Arduino 코드 업로드 실패: {error_info}")
        
        await notify_result(server, output_msg.encode('utf-8'))
    
    except Exception as e:
        err = f'Arduino 업로드 오류: {e}'
        log.error(err)
        await notify_error(server, err)


# ── BLE Write 핸들러 (메인) ────────────────────────────────────
def on_write(characteristic: BlessGATTCharacteristic, value: bytearray, **kwargs):
    """폰 → Pi: 모든 명령 수신"""
    global _code_chunks, _code_total_chunks, _selected_device
    global _arduino_code_chunks, _arduino_code_total

    data = bytes(value)
    char_uuid = str(characteristic.uuid).lower().replace('-', '')

    try:
        ptype, seq, total, payload = parse_packet(data)
    except ValueError as e:
        log.error(f'패킷 파싱 오류: {e}')
        return

    # ────────────────────────────────────────────────────────────
    # Pi Python 코드 실행 (0x01-0x06)
    # ────────────────────────────────────────────────────────────
    if 'fff1' in char_uuid:
        if ptype == PKT_CODE_CHUNK:
            _code_chunks[seq] = payload
            _code_total_chunks = total
            log.debug(f'코드 청크 {seq}/{total} 수신 ({len(payload)}B)')

        elif ptype == PKT_CODE_END:
            if len(_code_chunks) < _code_total_chunks:
                missing = set(range(1, _code_total_chunks + 1)) - set(_code_chunks.keys())
                log.error(f'청크 누락: {missing}')
                asyncio.create_task(notify_error(_server, f'청크 누락: {missing}'))
                return

            code_bytes = b''.join(_code_chunks[i] for i in sorted(_code_chunks.keys()))
            code = code_bytes.decode('utf-8')
            _code_chunks.clear()
            _code_total_chunks = 0

            log.info(f'Pi 코드 수신 완료 ({len(code)}자), 실행 시작')
            asyncio.create_task(execute_code(_server, code))

    # ────────────────────────────────────────────────────────────
    # /10-0x1F: 외부 장치 제어
    # ────────────────────────────────────────────────────────────
    
    elif ptype == PKT_DEVICE_LIST:
        # 0x10: 장치 목록 요청
        if not _device_manager:
            asyncio.create_task(notify_error(_server, "Device Manager 초기화 안됨"))
            return
        
        device_list = _device_manager.get_device_list()
        json_data = json.dumps(device_list, ensure_ascii=False).encode('utf-8')
        log.info(f'장치 목록 전송: {len(device_list)}개')
        asyncio.create_task(notify_result(_server, json_data))
    
    elif ptype == PKT_SELECT_DEVICE:
        # 0x11: 디바이스 선택
        device_id = payload.decode('utf-8').strip()
        _selected_device = device_id
        device = _device_manager.get_device(device_id) if device_id != 'pi' else None
        if device_id == 'pi':
            device_name = "RaspLab Board (Pi)"
        else:
            device_name = device.name if device else f"Unknown ({device_id})"
        
        log.info(f'디바이스 선택: {device_name}')
        asyncio.create_task(notify_result(_server, f"선택됨: {device_name}".encode('utf-8')))
    
    elif ptype == PKT_ARDUINO_UPLOAD:
        # 0x12: Arduino 코드 업로드
        _arduino_code_chunks[seq] = payload
        _arduino_code_total = total
        log.debug(f'Arduino 코드 청크 {seq}/{total} 수신 ({len(payload)}B)')
        
        if seq == total:  # 마지막 청크 수신
            try:
                code_bytes = b''.join(
                    _arduino_code_chunks[i] for i in sorted(_arduino_code_chunks.keys())
                )
                arduino_code = code_bytes.decode('utf-8')
                _arduino_code_chunks.clear()
                _arduino_code_total = 0
                
                log.info(f'Arduino 코드 수신 완료 ({len(arduino_code)}자)')
                asyncio.create_task(compile_and_upload_arduino(_server, arduino_code))
            except Exception as e:
                log.error(f'Arduino 코드 처리 오류: {e}')
                asyncio.create_task(notify_error(_server, f'Arduino 코드 처리 오류: {e}'))

    # ────────────────────────────────────────────────────────────
    # CONTROL (fff3): 중지 명령
    # ────────────────────────────────────────────────────────────
    elif 'fff3' in char_uuid and ptype == 0x03:
        # PKT_STOP
        with _process_lock:
            if _current_process and _current_process.poll() is None:
                _current_process.kill()
                log.info('Pi 프로세스 중지 요청')
            else:
                log.info('중지 요청: 실행 중인 프로세스 없음')


# ── BLE 서버 초기화 ───────────────────────────────────────────
async def run_server():
    global _server, _device_manager, _platformio_bridge

    # 기기 이름 생성
    try:
        with open('/sys/class/net/eth0/address', 'r') as f:
            mac = f.read().strip().replace(':', '').upper()[-4:]
    except OSError:
        import random
        mac = ''.join(random.choices('0123456789ABCDEF', k=4))
    
    device_name = f"{DEVICE_NAME_PREFIX}-{mac}"
    log.info(f'BLE 기기명: {device_name}')

    # 장치 매니저 & PlatformIO 초기화
    try:
        _device_manager = DeviceManager()
        log.info('Device Manager 초기화 완료')
        
        _platformio_bridge = PlatformIOBridge()
        log.info('PlatformIO Bridge 초기화 완료')
    except Exception as e:
        log.error(f'초기화 오류: {e}')
        return

    loop = asyncio.get_event_loop()
    trigger = asyncio.Event()

    server = BlessServer(name=device_name, loop=loop)
    server.write_request_func = on_write
    _server = server

    # ── GATT 서비스 정의 ────────────────────────────────────
    await server.add_new_service(SERVICE_UUID)

    # CODE_WRITE (fff1): Write
    await server.add_new_characteristic(
        SERVICE_UUID,
        CODE_WRITE_UUID,
        GATTCharacteristicProperties.write | GATTCharacteristicProperties.write_without_response,
        None,
        GATTAttributePermissions.writeable,
    )

    # RESULT_READ (fff2): Notify
    await server.add_new_characteristic(
        SERVICE_UUID,
        RESULT_READ_UUID,
        GATTCharacteristicProperties.notify,
        None,
        GATTAttributePermissions.readable,
    )

    # CONTROL (fff3): Write
    await server.add_new_characteristic(
        SERVICE_UUID,
        CONTROL_UUID,
        GATTCharacteristicProperties.write | GATTCharacteristicProperties.write_without_response,
        None,
        GATTAttributePermissions.writeable,
    )

    # STATUS (fff4): Notify
    await server.add_new_characteristic(
        SERVICE_UUID,
        STATUS_UUID,
        GATTCharacteristicProperties.notify,
        None,
        GATTAttributePermissions.readable,
    )

    await server.start()
    log.info(f'BLE 광고 시작: {device_name}')
    log.info('앱 연결 대기 중...')

    trigger.clear()
    try:
        await trigger.wait()
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
        log.info('BLE 서버 종료')


# ── 진입점 ─────────────────────────────────────────────────────
if __name__ == '__main__':
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        log.info('KeyboardInterrupt — 종료')
