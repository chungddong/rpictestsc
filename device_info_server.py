#!/usr/bin/env python3
"""Pi 기기 정보 HTTP API 서버 (stdlib만 사용, 의존성 없음)

USB RNDIS로 연결된 PC에서 기기 정보를 조회할 수 있게 합니다.
- GET /device-info  →  기기 시리얼, BLE MAC, 호스트명 등 JSON
- GET /health       →  "ok"
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import socket
import subprocess

HOST = "0.0.0.0"
PORT = 5000


def _read_file(path: str) -> str:
    try:
        with open(path, "r") as f:
            return f.read().strip().strip("\x00")
    except (FileNotFoundError, PermissionError):
        return ""


def _get_serial() -> str:
    serial = _read_file("/sys/firmware/devicetree/base/serial-number")
    if serial:
        return serial
    # fallback: /proc/cpuinfo
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("Serial"):
                    return line.split(":")[-1].strip()
    except (FileNotFoundError, PermissionError):
        pass
    return "unknown"


def _get_ble_mac() -> str:
    mac = _read_file("/sys/class/bluetooth/hci0/address")
    return mac.upper() if mac else "unknown"


def _get_usb0_ip() -> str:
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", "usb0"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                return line.split()[1].split("/")[0]
    except Exception:
        pass
    return "192.168.7.2"


def get_device_info() -> dict:
    ble_mac = _get_ble_mac()
    mac_suffix = ble_mac.replace(":", "")[-4:] if ble_mac != "unknown" else "0000"
    return {
        "serial": _get_serial(),
        "ble_mac": ble_mac,
        "ble_name": f"RaspLab-{mac_suffix}",
        "hostname": socket.gethostname(),
        "ip_address": _get_usb0_ip(),
    }


class DeviceInfoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/device-info":
            data = get_device_info()
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        # 간단한 로그
        print(f"[device-info] {args[0]}")


def main():
    server = HTTPServer((HOST, PORT), DeviceInfoHandler)
    print(f"[device-info] listening on {HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[device-info] shutting down")
    server.server_close()


if __name__ == "__main__":
    main()
