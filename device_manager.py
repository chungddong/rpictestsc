#!/usr/bin/env python3
"""
RaspLab Device Manager
USB 시리얼 포트를 통해 연결된 Arduino/ESP32 등의 장치를 감지하고 관리합니다.
"""

import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from serial.tools.list_ports import comports
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class ConnectedDevice:
    """연결된 외부 장치 정보"""
    id: str                      # 고유 ID (포트명 기반)
    port: str                    # COM3, /dev/ttyUSB0
    name: str                    # Arduino Uno, ESP32 등
    vendor_id: Optional[int]     # USB VID
    product_id: Optional[int]    # USB PID
    serial_number: Optional[str]
    board_type: str              # arduino:avr:uno, esp32:esp32:esp32
    connected_at: str            # ISO 8601 timestamp
    
    def to_dict(self):
        return asdict(self)


class DeviceManager:
    """USB 시리얼 포트 감지 및 장치 관리"""
    
    # USB VID:PID (Arduino, ESP32 등)
    KNOWN_BOARDS = {
        (0x2341, 0x0043): {"name": "Arduino Uno R3", "type": "arduino:avr:uno"},
        (0x2341, 0x0001): {"name": "Arduino Uno", "type": "arduino:avr:uno"},
        (0x2341, 0x8036): {"name": "Arduino Leonardo", "type": "arduino:avr:leonardo"},
        (0x2341, 0x0042): {"name": "Arduino Mega", "type": "arduino:avr:mega"},
        (0x10c4, 0xea60): {"name": "ESP32 (CP2102)", "type": "esp32:esp32:esp32"},
        (0x1a86, 0x7523): {"name": "Arduino (CH340)", "type": "arduino:avr:nano"},
        (0x0403, 0x6001): {"name": "Arduino (FT232)", "type": "arduino:avr:nano"},
    }
    
    def __init__(self, db_path: str = "/opt/rasplab/device-db/devices.json"):
        """
        Args:
            db_path: 장치 정보를 저장할 JSON 파일 경로
        """
        self.db_path = db_path
        self.devices: Dict[str, ConnectedDevice] = {}
        self._load_db()
    
    def _load_db(self):
        """저장된 장치 정보 로드"""
        try:
            with open(self.db_path, 'r') as f:
                data = json.load(f)
                for device_id, device_info in data.items():
                    self.devices[device_id] = ConnectedDevice(**device_info)
            logger.info(f"Device DB 로드: {len(self.devices)}개 장치")
        except (FileNotFoundError, json.JSONDecodeError):
            logger.info("Device DB 파일 없음, 새로 생성합니다")
            self.devices = {}
    
    def _save_db(self):
        """장치 정보 저장"""
        try:
            import os
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            with open(self.db_path, 'w') as f:
                json.dump(
                    {k: v.to_dict() for k, v in self.devices.items()},
                    f, indent=2
                )
        except Exception as e:
            logger.error(f"Device DB 저장 실패: {e}")
    
    def _identify_board(self, port_info) -> tuple[str, str]:
        """
        USB VID:PID로 보드 타입 판별
        
        Returns:
            (name, board_type) 또는 ("Unknown Device", "unknown")
        """
        vid = port_info.vid
        pid = port_info.pid
        
        if (vid, pid) in self.KNOWN_BOARDS:
            board_info = self.KNOWN_BOARDS[(vid, pid)]
            return board_info["name"], board_info["type"]
        
        # Fallback: description으로 추측
        if port_info.description:
            if "Arduino" in port_info.description:
                return "Arduino (Compatible)", "arduino:avr:nano"
            if "ESP32" in port_info.description:
                return "ESP32", "esp32:esp32:esp32"
        
        return "Unknown Device", "unknown"
    
    def scan_devices(self) -> Dict[str, ConnectedDevice]:
        """
        현재 연결된 모든 USB 시리얼 장치 스캔
        
        Returns:
            {device_id: ConnectedDevice}
        """
        current_ports = {}
        
        for port_info in comports():
            if not port_info.serial_number:
                continue  # 시리얼 번호 없으면 스킵
            
            device_id = self._generate_device_id(port_info)
            name, board_type = self._identify_board(port_info)
            
            device = ConnectedDevice(
                id=device_id,
                port=port_info.device,
                name=name,
                vendor_id=port_info.vid,
                product_id=port_info.pid,
                serial_number=port_info.serial_number,
                board_type=board_type,
                connected_at=datetime.now().isoformat()
            )
            
            current_ports[device_id] = device
            
            # 새로운 장치 감지
            if device_id not in self.devices:
                logger.info(f"[New Device] {device.name} on {device.port}")
                self.devices[device_id] = device
        
        # 제거된 장치 감지
        removed_ids = set(self.devices.keys()) - set(current_ports.keys())
        for device_id in removed_ids:
            logger.info(f"[Device Removed] {self.devices[device_id].name} ({self.devices[device_id].port})")
            del self.devices[device_id]
        
        self._save_db()
        return self.devices
    
    def get_device_list(self) -> List[Dict]:
        """
        현재 연결된 장치 목록 반환 (BLE 응답 용)
        
        Returns:
            [
                {'id': 'pi', 'type': 'platform', 'name': 'RaspLab Board'},
                {'id': 'device_1', 'type': 'arduino:avr:uno', 'name': 'Arduino Uno #1'},
                ...
            ]
        """
        self.scan_devices()
        
        result = [
            {
                'id': 'pi',
                'type': 'platform',
                'name': 'RaspLab Board',
                'board_type': 'raspberry_pi_zero_2w'
            }
        ]
        
        for device in self.devices.values():
            result.append({
                'id': device.id,
                'type': 'external',
                'name': device.name,
                'port': device.port,
                'board_type': device.board_type,
                'serial_number': device.serial_number
            })
        
        return result
    
    def get_device(self, device_id: str) -> Optional[ConnectedDevice]:
        """특정 장치 정보 조회"""
        self.scan_devices()
        return self.devices.get(device_id)
    
    def _generate_device_id(self, port_info) -> str:
        """
        포트 정보로부터 고유 device_id 생성
        시리얼 번호 기반 (재부팅해도 같은 device 인식)
        """
        if port_info.serial_number:
            return f"device_{hashlib.md5(port_info.serial_number.encode()).hexdigest()[:8]}"
        else:
            return f"device_{hashlib.md5(port_info.device.encode()).hexdigest()[:8]}"


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='[%(asctime)s] %(levelname)s: %(message)s'
    )
    
    dm = DeviceManager()
    devices = dm.scan_devices()
    
    print("\n📡 연결된 장치:")
    for device_id, device in devices.items():
        print(f"  {device_id}: {device.name} ({device.port}) - {device.board_type}")
    
    print("\n📋 BLE 응답 형식:")
    import json
    print(json.dumps(dm.get_device_list(), indent=2, ensure_ascii=False))
