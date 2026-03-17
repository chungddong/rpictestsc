#!/usr/bin/env python3
"""
RaspLab BLE Daemon
──────────────────
Flutter 앱(폰)과 BLE로 통신하며:
  1. 앱에서 Python 코드를 수신 (청크 재조립)
  2. 수신된 코드를 subprocess로 실행
  3. stdout/stderr를 BLE Notify로 앱에 반환

사용법:
  sudo python3 raspi_ble_daemon.py

필요 라이브러리:
  pip install bless

패킷 프로토콜:
  [TYPE(1B)] [SEQ(2B, big-endian)] [TOTAL(2B, big-endian)] [PAYLOAD(~507B)]

  TYPE:
    0x01 = 코드 청크 수신
    0x02 = 코드 전송 완료 → 실행 시작
    0x03 = 실행 중지 요청
    0x04 = 결과 청크 (Pi → 앱)
    0x05 = 실행 완료 (Pi → 앱)
    0x06 = 에러 (Pi → 앱)
"""

import asyncio
import logging
import struct
import subprocess
import threading
import uuid
import os
import sys

from bless import BlessServer, BlessGATTCharacteristic, GATTCharacteristicProperties, GATTAttributePermissions

# ── 로깅 설정 ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('rasplab')

# ── BLE UUID 상수 (Flutter 앱과 동일) ─────────────────────────────────────────
SERVICE_UUID     = '0000fff0-0000-1000-8000-00805f9b34fb'
CODE_WRITE_UUID  = '0000fff1-0000-1000-8000-00805f9b34fb'
RESULT_READ_UUID = '0000fff2-0000-1000-8000-00805f9b34fb'
CONTROL_UUID     = '0000fff3-0000-1000-8000-00805f9b34fb'
STATUS_UUID      = '0000fff4-0000-1000-8000-00805f9b34fb'

# ── 패킷 타입 ──────────────────────────────────────────────────────────────────
PKT_CODE_CHUNK  = 0x01
PKT_CODE_END    = 0x02
PKT_STOP        = 0x03
PKT_RESULT_CHUNK = 0x04
PKT_RESULT_END  = 0x05
PKT_ERROR       = 0x06

# ── 설정 ───────────────────────────────────────────────────────────────────────
BLE_PAYLOAD_SIZE     = 507      # 청크당 최대 페이로드 바이트
EXECUTION_TIMEOUT    = 30       # 코드 실행 타임아웃 (초)
DEVICE_NAME_PREFIX   = 'RaspLab'

# 실행 중인 프로세스 참조 (중지 버튼 처리용)
_current_process: subprocess.Popen | None = None
_process_lock = threading.Lock()

# BLE 서버 전역 참조
_server: BlessServer | None = None

# 코드 수신 버퍼: {seq: payload_bytes}
_code_chunks: dict[int, bytes] = {}
_code_total_chunks: int = 0


# ── 패킷 파싱 ──────────────────────────────────────────────────────────────────
def parse_packet(data: bytes) -> tuple[int, int, int, bytes]:
    """[TYPE(1)][SEQ(2)][TOTAL(2)][PAYLOAD] → (type, seq, total, payload)"""
    if len(data) < 5:
        raise ValueError(f'패킷이 너무 짧음: {len(data)}B')
    ptype = data[0]
    seq   = struct.unpack('>H', data[1:3])[0]
    total = struct.unpack('>H', data[3:5])[0]
    payload = data[5:]
    return ptype, seq, total, payload


# ── 패킷 조립 ──────────────────────────────────────────────────────────────────
def build_packet(ptype: int, seq: int, total: int, payload: bytes) -> bytes:
    """(type, seq, total, payload) → [TYPE(1)][SEQ(2)][TOTAL(2)][PAYLOAD]"""
    return bytes([ptype]) + struct.pack('>H', seq) + struct.pack('>H', total) + payload


# ── 청크 분할 ──────────────────────────────────────────────────────────────────
def split_chunks(data: bytes, chunk_size: int = BLE_PAYLOAD_SIZE) -> list[bytes]:
    return [data[i:i + chunk_size] for i in range(0, max(len(data), 1), chunk_size)]


# ── BLE Notify 전송 ────────────────────────────────────────────────────────────
async def notify_result(server: BlessServer, data: bytes):
    """결과 데이터를 청크로 나눠 RESULT_READ Notify로 전송"""
    chunks = split_chunks(data)
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        packet = build_packet(PKT_RESULT_CHUNK, i + 1, total, chunk)
        server.get_characteristic(RESULT_READ_UUID).value = bytearray(packet)
        server.update_value(SERVICE_UUID, RESULT_READ_UUID)
        await asyncio.sleep(0.02)   # 20ms 간격 (BLE 버퍼 보호)

    # 전송 완료 신호
    end_packet = build_packet(PKT_RESULT_END, 0, 0, b'')
    server.get_characteristic(RESULT_READ_UUID).value = bytearray(end_packet)
    server.update_value(SERVICE_UUID, RESULT_READ_UUID)


async def notify_error(server: BlessServer, message: str):
    """에러 패킷 전송"""
    packet = build_packet(PKT_ERROR, 0, 0, message.encode('utf-8'))
    server.get_characteristic(RESULT_READ_UUID).value = bytearray(packet)
    server.update_value(SERVICE_UUID, RESULT_READ_UUID)


# ── 코드 실행 ──────────────────────────────────────────────────────────────────
async def execute_code(server: BlessServer, code: str):
    """
    임시 파일에 코드를 저장한 뒤 subprocess로 실행.
    stdout/stderr를 실시간으로 BLE Notify 전송.
    """
    global _current_process

    tmp_path = '/tmp/rasplab_code.py'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        f.write(code)

    log.info(f'코드 실행 시작 ({len(code)}자)')
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
            log.info(f'실행 성공 (returncode=0)')
            log.info(f'출력 내용: {repr(output)}')
        elif returncode == -9:
            result = output + '\n[중지됨]' if output else '[중지됨]'
            log.info('실행 중지됨')
        else:
            result = output if output else f'(returncode={returncode})'
            log.error(f'실행 실패 (returncode={returncode})')
            log.error(f'에러 출력: {repr(output)}')

        await notify_result(server, result.encode('utf-8'))

    except Exception as e:
        err = f'실행 오류: {e}'
        log.error(err)
        await notify_error(server, err)
    finally:
        with _process_lock:
            _current_process = None
        # 임시 파일 삭제
        try:
            os.remove(tmp_path)
        except OSError:
            pass


# ── BLE Write 핸들러 ───────────────────────────────────────────────────────────
def on_write(characteristic: BlessGATTCharacteristic, value: bytearray, **kwargs):
    """폰 → Pi: 코드 청크 또는 제어 명령 수신"""
    global _code_chunks, _code_total_chunks

    data = bytes(value)
    char_uuid = str(characteristic.uuid).lower().replace('-', '')

    try:
        ptype, seq, total, payload = parse_packet(data)
    except ValueError as e:
        log.error(f'패킷 파싱 오류: {e}')
        return

    # short UUID로 매칭 (fff1, fff2, fff3)
    # ── CODE_WRITE (fff1): 코드 청크 수신 ──────────────────────────────────
    if 'fff1' in char_uuid:
        if ptype == PKT_CODE_CHUNK:
            _code_chunks[seq] = payload
            _code_total_chunks = total
            log.debug(f'코드 청크 {seq}/{total} 수신 ({len(payload)}B)')

        elif ptype == PKT_CODE_END:
            # 모든 청크 재조립
            if len(_code_chunks) < _code_total_chunks:
                missing = set(range(1, _code_total_chunks + 1)) - set(_code_chunks.keys())
                log.error(f'청크 누락: {missing}')
                asyncio.create_task(notify_error(_server, f'청크 누락: {missing}'))
                return

            # seq 순서대로 조립
            code_bytes = b''.join(
                _code_chunks[i] for i in sorted(_code_chunks.keys())
            )
            code = code_bytes.decode('utf-8')
            _code_chunks.clear()
            _code_total_chunks = 0

            log.info(f'코드 수신 완료 ({len(code)}자), 실행 시작')
            asyncio.create_task(execute_code(_server, code))

    # ── CONTROL (fff3): 중지 명령 ───────────────────────────────────────────
    elif 'fff3' in char_uuid:
        if ptype == PKT_STOP:
            with _process_lock:
                if _current_process and _current_process.poll() is None:
                    _current_process.kill()
                    log.info('실행 중지 요청 — 프로세스 kill')
                else:
                    log.info('중지 요청: 실행 중인 프로세스 없음')


# ── BLE 서버 초기화 ────────────────────────────────────────────────────────────
async def run_server():
    global _server

    # 기기 이름에 MAC 뒷자리 추가
    try:
        with open('/sys/class/net/eth0/address', 'r') as f:
            mac = f.read().strip().replace(':', '').upper()[-4:]
    except OSError:
        import random
        mac = ''.join(random.choices('0123456789ABCDEF', k=4))
    
    device_name = f"{DEVICE_NAME_PREFIX}-{mac}"
    log.info(f'BLE 기기명: {device_name}')

    loop = asyncio.get_event_loop()
    trigger = asyncio.Event()

    server = BlessServer(name=device_name, loop=loop)
    server.read_request_func  = None
    server.write_request_func = on_write
    _server = server

    # ── GATT 서비스 정의 ────────────────────────────────────────────────────
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
        await trigger.wait()   # Ctrl+C 전까지 대기
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
        log.info('BLE 서버 종료')


# ── 진입점 ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        log.info('KeyboardInterrupt — 종료')
