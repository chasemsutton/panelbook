"""Verify the packaged Windows launcher starts and auto-closes the hidden server."""

import http.cookiejar
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]


def powershell(command):
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()


def process_info(pid):
    output = powershell(f'Get-CimInstance Win32_Process -Filter "ProcessId={pid}" | '
                        'Select-Object ProcessId,ParentProcessId,Name | ConvertTo-Json -Compress')
    return json.loads(output) if output else None


def server_pid(port):
    listener = powershell(f'Get-NetTCPConnection -LocalPort {port} -State Listen | '
                          'Select-Object -First 1 -ExpandProperty OwningProcess')
    return int(listener)


def main():
    if os.name != "nt":
        raise SystemExit("This smoke test runs on Windows.")
    from sys import path
    path.insert(0, str(ROOT))
    from program.server import VERSION

    archive = ROOT / "dist" / f"v{VERSION}" / f"Panelbook-Portable-v{VERSION}.zip"
    if not archive.is_file():
        raise SystemExit(f"Build and package {archive} first.")
    with tempfile.TemporaryDirectory(prefix="panelbook launcher test ") as scratch_name:
        scratch = Path(scratch_name)
        app = scratch / "app"
        with ZipFile(archive) as payload:
            payload.extractall(app)
        with socket.socket() as connection:
            connection.bind(("127.0.0.1", 0))
            port = connection.getsockname()[1]
        first = subprocess.Popen([str(app / "Panelbook.exe"),
                                  "--no-browser", "--port", str(port)],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        running_pid = None
        try:
            first.wait(timeout=8)
            for _ in range(80):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1) as response:
                        assert json.load(response)["version"] == VERSION
                    break
                except Exception:
                    time.sleep(0.25)
            else:
                raise AssertionError("Panelbook did not start from the top-level launcher.")
            running_pid = server_pid(port)
            process = process_info(running_pid)
            assert process["Name"].lower() == "panelbookserver.exe", process
            handle = int(powershell(f'(Get-Process -Id {running_pid}).MainWindowHandle'))
            assert handle == 0, f"Server has a visible window: {handle}"
            print("Windows EXE launcher started the server without a console window.")
            base = f"http://127.0.0.1:{port}"
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

            def request(path, payload):
                data = json.dumps(payload).encode()
                headers = {"Origin": base, "Content-Type": "application/json"}
                if csrf:
                    headers["X-Panelbook-CSRF"] = csrf
                with opener.open(urllib.request.Request(base + path, data=data, headers=headers)) as response:
                    return json.load(response)

            csrf = None
            request("/api/setup/local", {})
            with opener.open(base + "/api/status") as response:
                csrf = json.load(response)["csrf"]
            request("/api/local/auto-close", {"enabled": True})
            request("/api/local/presence", {"tabId": "a" * 24, "active": True})
            request("/api/local/presence", {"tabId": "a" * 24, "active": False})
            for _ in range(20):
                if process_info(running_pid) is None:
                    break
                time.sleep(0.5)
            else:
                raise AssertionError("Server stayed open after the last tab closed.")
            print("Windows server exited after the last tab closed.")
        finally:
            if running_pid:
                subprocess.run(["taskkill", "/PID", str(running_pid), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if first.poll() is None:
                subprocess.run(["taskkill", "/PID", str(first.pid), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            time.sleep(1)


if __name__ == "__main__":
    main()
