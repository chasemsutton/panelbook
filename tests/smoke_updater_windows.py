"""Run after packaging to exercise the Windows updater with a local release ZIP."""

import functools
import hashlib
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from program.server import VERSION

ZIP = ROOT / "dist" / f"v{VERSION}" / f"Panelbook-Portable-v{VERSION}.zip"
HELPER = ROOT / "program" / "update-portable.ps1"


def free_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def status(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=2) as response:
        return json.load(response)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main():
    if os.name != "nt":
        raise SystemExit("This smoke test runs on Windows.")
    if not ZIP.is_file():
        raise SystemExit(f"Build and package {ZIP} first.")
    with tempfile.TemporaryDirectory(prefix="panelbook updater test ") as scratch_name:
        scratch = Path(scratch_name)
        app = scratch / "app"
        data = app / "data with spaces"
        data.mkdir(parents=True)
        (data / "marker.txt").write_text("keep this data", encoding="utf-8")
        with ZipFile(ZIP) as archive:
            archive.extractall(app)
        payload = scratch / "payload.zip"
        shutil.copy2(ZIP, payload)
        port = free_port()
        http_server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(scratch))
        )
        thread = threading.Thread(target=http_server.serve_forever, daemon=True)
        thread.start()
        old = None
        new_pid = None
        try:
            old = subprocess.Popen(
                [str(app / "program" / "Panelbook.exe"), "--no-browser", "--port", str(port),
                 "--data-dir", str(data)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            for _ in range(60):
                try:
                    if status(port)["version"] == VERSION:
                        break
                except Exception:
                    time.sleep(0.25)
            else:
                raise AssertionError("The initial app did not start.")
            helper = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HELPER),
                 "-AppFolder", str(app), "-ServerPid", str(old.pid),
                 "-DownloadUrl", f"http://127.0.0.1:{http_server.server_port}/payload.zip",
                 "-ExpectedSha256", hashlib.sha256(payload.read_bytes()).hexdigest(),
                 "-ExpectedVersion", "v" + VERSION, "-HostName", "127.0.0.1",
                 "-Port", str(port), "-DataDir", str(data)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            time.sleep(1)
            subprocess.run(["taskkill", "/PID", str(old.pid), "/T", "/F"],
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            old.wait(timeout=10)
            stdout, stderr = helper.communicate(timeout=90)
            log = (data / "updater.log").read_text(encoding="utf-8")
            found = re.search(r"Started process (\d+)", log)
            if found:
                new_pid = int(found.group(1))
            assert helper.returncode == 0, (stdout, stderr, log)
            assert f"Panelbook v{VERSION} is ready." in log, (stdout, stderr, log)
            assert status(port)["version"] == VERSION
            assert (data / "marker.txt").read_text(encoding="utf-8") == "keep this data"
            print("Windows updater smoke test passed; app restarted and data survived.")
        finally:
            if old and old.poll() is None:
                subprocess.run(["taskkill", "/PID", str(old.pid), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if new_pid:
                subprocess.run(["taskkill", "/PID", str(new_pid), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            http_server.shutdown()
            http_server.server_close()


if __name__ == "__main__":
    main()
