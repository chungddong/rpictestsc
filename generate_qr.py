#!/usr/bin/env python3
"""
RaspLab QR 코드 생성기
──────────────────────
이 스크립트를 실행하면 BLE MAC 주소를 인코딩한 QR 이미지를 생성합니다.
생성된 QR 이미지를 프린트하거나 화면에 띄워두면
Flutter 앱의 QR 스캔 탭으로 자동 연결할 수 있습니다.

사용법:
  python3 generate_qr.py

필요 라이브러리:
  pip install qrcode[pil] pillow
"""

import subprocess
import sys

try:
    import qrcode
    from PIL import Image
except ImportError:
    print('[!] 라이브러리가 없습니다. 설치 중...')
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'qrcode[pil]', 'pillow'])
    import qrcode
    from PIL import Image


def get_bluetooth_mac() -> str:
    """bluetoothctl 또는 /sys에서 BLE MAC 주소 읽기"""
    # 방법 1: hciconfig
    try:
        result = subprocess.run(
            ['hciconfig', 'hci0'],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith('BD Address:'):
                return line.split()[2].upper()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 방법 2: /sys/class/bluetooth
    import os
    for path in ['/sys/class/bluetooth/hci0/address']:
        try:
            with open(path, 'r') as f:
                return f.read().strip().upper()
        except OSError:
            pass

    raise RuntimeError('Bluetooth MAC 주소를 찾을 수 없습니다. bluetoothctl이 설치되어 있는지 확인하세요.')


def main():
    mac = get_bluetooth_mac()
    # Flutter 앱 QrService가 파싱하는 형식: rasplab://MAC_ADDRESS
    qr_data = f'rasplab://{mac}'

    print(f'[*] BLE MAC 주소: {mac}')
    print(f'[*] QR 데이터:    {qr_data}')

    # QR 생성
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)

    img = qr.make_image(fill_color='black', back_color='white')

    output_path = '/tmp/rasplab_qr.png'
    img.save(output_path)
    print(f'[✓] QR 이미지 저장: {output_path}')

    # 터미널에 ASCII QR 출력 (선택)
    try:
        qr.print_ascii(invert=True)
    except Exception:
        pass

    # GUI가 있으면 이미지 열기 시도
    try:
        import subprocess
        subprocess.Popen(['display', output_path])
    except FileNotFoundError:
        print(f'[i] 이미지 뷰어가 없습니다. {output_path} 를 직접 열어보세요.')


if __name__ == '__main__':
    main()
