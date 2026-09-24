"""Verify the packaged Windows CMD launcher starts Panelbook minimized."""

import ctypes
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


def launcher_pid(port):
    listener = powershell(f'Get-NetTCPConnection -LocalPort {port} -State Listen | '
                          'Select-Object -First 1 -ExpandProperty OwningProcess')
    pid = int(listener)
    for _ in range(5):
        process = process_info(pid)
        if not process:
            break
        if process["Name"].lower() == "cmd.exe":
            return pid
        pid = process["ParentProcessId"]
    raise AssertionError("Could not find the launcher console process.")


class Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class WindowPlacement(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint), ("flags", ctypes.c_uint),
                ("showCmd", ctypes.c_uint), ("min", Point), ("max", Point), ("normal", Rect)]


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
        first = subprocess.Popen(["cmd.exe", "/c", str(app / "Panelbook.cmd"),
                                  "--no-browser", "--port", str(port)],
                                 creationflags=subprocess.CREATE_NEW_CONSOLE,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        console_pid = None
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
                raise AssertionError("Panelbook did not start from Panelbook.cmd.")
            console_pid = launcher_pid(port)
            handle = int(powershell(f'(Get-Process -Id {console_pid}).MainWindowHandle'))
            if handle:
                placement = WindowPlacement()
                placement.length = ctypes.sizeof(placement)
                if not ctypes.windll.user32.GetWindowPlacement(handle, ctypes.byref(placement)):
                    raise AssertionError("Could not inspect the launcher window.")
                assert placement.showCmd in (2, 6, 7), f"Console was not minimized: {placement.showCmd}"
                print("Windows CMD launcher smoke test passed; console is minimized.")
            else:
                print("Windows CMD launcher started; window state is unavailable in this console host.")
        finally:
            if console_pid:
                subprocess.run(["taskkill", "/PID", str(console_pid), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if first.poll() is None:
                subprocess.run(["taskkill", "/PID", str(first.pid), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            time.sleep(1)


if __name__ == "__main__":
    main()
