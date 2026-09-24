"""Run after packaging to exercise the Windows updater with a local release ZIP."""

import argparse
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-zip", type=Path, default=ZIP, help="Installed version to update")
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("This smoke test runs on Windows.")
    if not ZIP.is_file():
        raise SystemExit(f"Build and package {ZIP} first.")
    if not args.from_zip.is_file():
        raise SystemExit(f"The installed release is missing: {args.from_zip}")
    source_version = re.search(r"Panelbook-Portable-v(\d+\.\d+\.\d+(?:\.\d+)?)\.zip$", args.from_zip.name)
    if not source_version:
        raise SystemExit("--from-zip must name a versioned Panelbook portable release")
    with tempfile.TemporaryDirectory(prefix="panelbook updater test ") as scratch_name:
        scratch = Path(scratch_name)
        app = scratch / "app"
        data = app / "data with spaces"
        data.mkdir(parents=True)
        (data / "marker.txt").write_text("keep this data", encoding="utf-8")
        with ZipFile(args.from_zip) as archive:
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
                [str(app / "program" / "PanelbookServer.exe"), "--no-browser", "--port", str(port),
                 "--data-dir", str(data)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            for _ in range(60):
                try:
                    initial_version = status(port)["version"]
                    if initial_version:
                        break
                except Exception:
                    time.sleep(0.25)
            else:
                raise AssertionError("The initial app did not start.")
            assert initial_version == source_version.group(1), (
                f"{args.from_zip.name} runs version {initial_version}, expected {source_version.group(1)}"
            )
            helper = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(app / "program" / "update-portable.ps1"),
                 "-AppFolder", str(app), "-ServerPid", str(old.pid),
                 "-DownloadUrl", f"http://127.0.0.1:{http_server.server_port}/payload.zip",
                 "-ExpectedSha256", hashlib.sha256(payload.read_bytes()).hexdigest(),
                 "-ExpectedVersion", "v" + VERSION, "-HostName", "127.0.0.1",
                 "-Port", str(port), "-DataDir", str(data)],
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(1)
            subprocess.run(["taskkill", "/PID", str(old.pid), "/T", "/F"],
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            old.wait(timeout=10)
            helper.wait(timeout=90)
            log_path = data / "updater.log"
            assert log_path.exists(), f"Updater helper exited {helper.returncode} without creating {log_path}"
            log = log_path.read_text(encoding="utf-8")
            found = re.search(r"Started process (\d+)", log)
            if found:
                new_pid = int(found.group(1))
            assert helper.returncode == 0, log
            assert f"Panelbook v{VERSION} is ready." in log, log
            updated = status(port)
            assert updated["version"] == VERSION
            assert updated["canUseLocal"]
            base = f"http://127.0.0.1:{port}"
            request = urllib.request.Request(base + "/api/setup/local", data=b"{}", method="POST",
                                             headers={"Origin": base, "Content-Type": "application/json"})
            with urllib.request.urlopen(request) as response:
                assert response.status == 201
            local_status = status(port)
            assert local_status["user"]["isLocal"]
            assert local_status["autoClose"]
            assert (data / "marker.txt").read_text(encoding="utf-8") == "keep this data"
            print(f"Windows updater smoke test passed: {initial_version} to {VERSION}; local setup and data survived.")
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
