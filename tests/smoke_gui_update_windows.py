"""Exercise a released 0.4.0 app with the repaired GUI update helper on Windows."""

import http.cookiejar
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_VERSION = "0.4.0"
SOURCE_URL = ("https://github.com/chasemsutton/panelbook/releases/download/"
              f"v{SOURCE_VERSION}/Panelbook-Portable-v{SOURCE_VERSION}.zip")


def free_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def kill(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    if os.name != "nt":
        raise SystemExit("This smoke test runs on Windows.")
    with tempfile.TemporaryDirectory(prefix="panelbook gui update ") as scratch_name:
        scratch = Path(scratch_name)
        archive = scratch / "source.zip"
        urllib.request.urlretrieve(SOURCE_URL, archive)
        app = scratch / "app"
        with ZipFile(archive) as payload:
            payload.extractall(app)
        shutil.copy2(ROOT / "program" / "update-portable.ps1",
                     app / "program" / "update-portable.ps1")
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

        def api(path, method="GET", body=None, csrf=None):
            headers = {}
            data = None
            if method != "GET":
                headers = {"Content-Type": "application/json", "Origin": base}
                if csrf:
                    headers["X-Panelbook-CSRF"] = csrf
                data = json.dumps(body or {}).encode()
            with opener.open(urllib.request.Request(base + path, data=data,
                                                     headers=headers, method=method), timeout=15) as response:
                return json.load(response)

        old = subprocess.Popen([str(app / "program" / "Panelbook.exe"), "--no-browser",
                                "--port", str(port)],
                               creationflags=subprocess.CREATE_NO_WINDOW,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        launched_pids = []
        try:
            for _ in range(60):
                try:
                    initial = api("/api/status")
                    break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.25)
            else:
                raise AssertionError("The 0.4.0 app did not start.")
            assert initial["version"] == SOURCE_VERSION, initial
            api("/api/setup/local", "POST")
            csrf = api("/api/status")["csrf"]
            release = api("/api/update/check")["release"]
            assert release and release["version"] != "v" + SOURCE_VERSION, release
            api("/api/update/install", "POST", {"version": release["version"]}, csrf)
            expected = release["version"].removeprefix("v")
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                time.sleep(1)
                try:
                    current = api("/api/status")
                    if current["version"] == expected:
                        print(f"GUI update passed: {SOURCE_VERSION} to {expected}")
                        return
                except (OSError, urllib.error.URLError):
                    pass
                log = app / "data" / "updater.log"
                if log.is_file() and "Update failed:" in log.read_text(encoding="utf-8", errors="replace"):
                    raise AssertionError(log.read_text(encoding="utf-8", errors="replace"))
            log = app / "data" / "updater.log"
            raise AssertionError(log.read_text(encoding="utf-8", errors="replace")
                                 if log.is_file() else "GUI update timed out without an updater log.")
        finally:
            log = app / "data" / "updater.log"
            if log.is_file():
                launched_pids = [int(pid) for pid in re.findall(r"Started process (\d+)",
                                                                   log.read_text(encoding="utf-8", errors="replace"))]
            for pid in launched_pids + [old.pid]:
                kill(pid)


if __name__ == "__main__":
    main()
