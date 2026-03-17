#!/usr/bin/env python3
"""
RaspLab PlatformIO Bridge
Arduino/ESP32 코드를 컴파일하고 펌웨어를 업로드합니다.
"""

import os
import json
import logging
import subprocess
import tempfile
from typing import Dict, Optional, Callable
from pathlib import Path
from dataclasses import dataclass
import shutil

logger = logging.getLogger(__name__)


@dataclass
class CompileResult:
    """컴파일 결과"""
    success: bool
    output: str
    error: str = ""
    duration: float = 0.0


@dataclass
class UploadResult:
    """업로드 결과"""
    success: bool
    output: str
    error: str = ""
    duration: float = 0.0


class PlatformIOBridge:
    """PlatformIO CLI 래퍼"""
    
    def __init__(
        self,
        pio_env: str = "/opt/rasplab/venv/bin",
        projects_dir: str = "/opt/rasplab/pio-projects",
        env_vars: Optional[Dict] = None
    ):
        """
        Args:
            pio_env: platformio 실행 파일 경로 (venv bin)
            projects_dir: PlatformIO 프로젝트 저장 디렉토리
            env_vars: 추가 환경 변수
        """
        self.pio_bin = os.path.join(pio_env, "platformio")
        self.python_bin = os.path.join(pio_env, "python")
        self.projects_dir = projects_dir
        
        self.env = os.environ.copy()
        if env_vars:
            self.env.update(env_vars)
        
        os.makedirs(projects_dir, exist_ok=True)

    def _normalize_board_id(self, board_type: str) -> str:
        """device_manager board_type 값을 PlatformIO board ID로 변환"""
        if not board_type:
            return "uno"

        value = board_type.strip().lower()

        # arduino:avr:uno -> uno
        if ":" in value:
            parts = [p for p in value.split(":") if p]
            if parts:
                return parts[-1]

        return value

    def _ensure_project_structure(self, project_dir: str, board_id: str) -> bool:
        """프로젝트 필수 파일/디렉토리 보정"""
        try:
            os.makedirs(project_dir, exist_ok=True)

            src_dir = os.path.join(project_dir, "src")
            os.makedirs(src_dir, exist_ok=True)

            ini_path = os.path.join(project_dir, "platformio.ini")
            if not os.path.exists(ini_path):
                with open(ini_path, "w", encoding="utf-8") as f:
                    f.write(
                        "[env:%s]\n"
                        "platform = atmelavr\n"
                        "board = %s\n"
                        "framework = arduino\n" % (board_id, board_id)
                    )

            main_cpp_path = os.path.join(src_dir, "main.cpp")
            if not os.path.exists(main_cpp_path):
                with open(main_cpp_path, 'w', encoding='utf-8') as f:
                    f.write(self._get_default_skeleton(board_id))

            return True
        except Exception as e:
            logger.error(f"프로젝트 구조 보정 실패: {e}")
            return False
    
    def register_board(self, device_id: str, board_type: str) -> bool:
        """
        새로운 Arduino 보드 프로젝트 생성
        
        Args:
            device_id: 장치 고유 ID (예: device_abc123)
            board_type: PlatformIO 보드 타입 (예: uno, esp32doit-devkit-v1)
        
        Returns:
            성공 여부
        """
        project_dir = os.path.join(self.projects_dir, device_id)
        board_id = self._normalize_board_id(board_type)
        
        if os.path.exists(project_dir):
            if self._ensure_project_structure(project_dir, board_id):
                logger.info(f"프로젝트 이미 존재: {device_id}")
                return True
            logger.warning(f"기존 프로젝트 보정 실패, 재생성 시도: {device_id}")
            shutil.rmtree(project_dir, ignore_errors=True)
        
        try:
            os.makedirs(project_dir, exist_ok=True)
            
            # PlatformIO 프로젝트 초기화
            cmd = [
                self.pio_bin, "project", "init",
                "--board", board_id,
                "-d", project_dir
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                logger.error(f"프로젝트 생성 실패: {result.stderr}")
                return False
            
            # 기본 main.cpp 생성
            src_dir = os.path.join(project_dir, "src")
            os.makedirs(src_dir, exist_ok=True)
            
            main_cpp_path = os.path.join(src_dir, "main.cpp")
            with open(main_cpp_path, 'w', encoding='utf-8') as f:
                f.write(self._get_default_skeleton(board_id))
            
            logger.info(f"프로젝트 생성 완료: {device_id}")
            return True
            
        except Exception as e:
            logger.error(f"프로젝트 등록 실패: {e}")
            return False
    
    def _get_default_skeleton(self, board_type: str) -> str:
        """보드 타입별 기본 코드 생성"""
        if "esp32" in board_type.lower():
            return """#include <Arduino.h>

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\\n==== ESP32 Ready ====");
  Serial.println("Use platformio device monitor to see output");
}

void loop() {
  delay(1000);
  Serial.println("Waiting for code upload...");
}
"""
        else:  # Arduino (AVR)
            return """#include <Arduino.h>

void setup() {
  Serial.begin(9600);
  delay(1000);
  Serial.println("Arduino Ready");
}

void loop() {
  delay(1000);
  Serial.println("Waiting for code upload...");
}
"""
    
    def compile_and_upload(
        self,
        device_id: str,
        code_content: str,
        port: str,
        board_type: str,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict:
        """
        Arduino 코드를 컴파일하고 업로드
        
        Args:
            device_id: 장치 ID
            code_content: Arduino C++ 코드
            port: 시리얼 포트 (예: /dev/ttyUSB0)
            board_type: 보드 타입
            progress_callback: 진행상황 콜백함수
        
        Returns:
            {
                'compile': CompileResult,
                'upload': UploadResult,
                'success': bool
            }
        """
        result = {
            'compile': None,
            'upload': None,
            'success': False
        }
        
        # 1단계: 프로젝트 등록 (없으면 생성)
        if not self.register_board(device_id, board_type):
            return {
                'success': False,
                'error': f'프로젝트 생성 실패: {device_id}',
                'compile': CompileResult(False, '', 'Failed to register project'),
                'upload': None
            }
        
        project_dir = os.path.join(self.projects_dir, device_id)
        
        # 2단계: main.cpp 업데이트
        if not self._update_source_code(project_dir, code_content):
            return {
                'success': False,
                'error': '코드 업데이트 실패',
                'compile': CompileResult(False, '', 'Failed to update source code'),
                'upload': None
            }
        
        # 3단계: 컴파일
        if progress_callback:
            progress_callback("[1/3] Compiling code...")
        
        compile_result = self._compile(project_dir)
        result['compile'] = compile_result
        
        if not compile_result.success:
            return {
                'success': False,
                'error': compile_result.error,
                'compile': compile_result,
                'upload': None
            }
        
        # 4단계: 업로드
        if progress_callback:
            progress_callback("[2/3] Uploading firmware...")
        
        upload_result = self._upload(project_dir, port)
        result['upload'] = upload_result
        result['success'] = upload_result.success
        
        if progress_callback:
            status = "Success!" if upload_result.success else "Failed"
            progress_callback(f"[3/3] {status}")
        
        return result
    
    def _update_source_code(self, project_dir: str, code_content: str) -> bool:
        """main.cpp 업데이트"""
        try:
            os.makedirs(os.path.join(project_dir, "src"), exist_ok=True)
            main_cpp_path = os.path.join(project_dir, "src", "main.cpp")
            with open(main_cpp_path, 'w', encoding='utf-8') as f:
                f.write(code_content)
            return True
        except Exception as e:
            logger.error(f"소스 코드 업데이트 실패: {e}")
            return False
    
    def _compile(self, project_dir: str) -> CompileResult:
        """PlatformIO 컴파일"""
        import time
        start = time.time()
        
        try:
            cmd = [self.pio_bin, "run", "-d", project_dir]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5분 타임아웃
            )
            
            duration = time.time() - start
            
            if result.returncode == 0:
                return CompileResult(True, result.stdout, "", duration)
            else:
                return CompileResult(False, result.stdout, result.stderr, duration)
        
        except subprocess.TimeoutExpired:
            return CompileResult(
                False, "", "Compilation timeout (5 minutes)", time.time() - start
            )
        except Exception as e:
            return CompileResult(False, "", str(e), time.time() - start)
    
    def _upload(self, project_dir: str, port: str) -> UploadResult:
        """PlatformIO 업로드"""
        import time
        start = time.time()
        
        try:
            cmd = [
                self.pio_bin, "run",
                "-t", "upload",
                "--upload-port", port,
                "-d", project_dir
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5분 타임아웃
            )
            
            duration = time.time() - start
            
            if result.returncode == 0:
                return UploadResult(True, result.stdout, "", duration)
            else:
                return UploadResult(False, result.stdout, result.stderr, duration)
        
        except subprocess.TimeoutExpired:
            return UploadResult(
                False, "", "Upload timeout (5 minutes)", time.time() - start
            )
        except Exception as e:
            return UploadResult(False, "", str(e), time.time() - start)
    
    def read_serial_output(
        self,
        port: str,
        baudrate: int = 9600,
        timeout: int = 5
    ) -> Optional[str]:
        """
        시리얼 포트에서 출력 읽기 (보드에서의 Serial.print())
        
        Args:
            port: 시리얼 포트
            baudrate: 보드레이트
            timeout: 읽기 타임아웃 (초)
        
        Returns:
            수신한 데이터 (또는 None if 실패)
        """
        try:
            import serial
            
            with serial.Serial(port, baudrate, timeout=timeout) as ser:
                output = ser.read(4096).decode('utf-8', errors='ignore')
                return output if output else None
        
        except Exception as e:
            logger.error(f"시리얼 읽기 실패 ({port}): {e}")
            return None


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='[%(asctime)s] %(levelname)s: %(message)s'
    )
    
    bridge = PlatformIOBridge()
    
    # 테스트 코드
    test_code = """
#include <Arduino.h>

void setup() {
  Serial.begin(9600);
  Serial.println("Hello from Arduino!");
}

void loop() {
  Serial.println("Loop...");
  delay(1000);
}
"""
    
    print("테스트: device_test1 프로젝트 생성")
    bridge.register_board("device_test1", "uno")
    print("✓ 프로젝트 생성 완료")
    print("\n주의: 실제 업로드 테스트는 Arduino 연결 시에만 수행하세요")
