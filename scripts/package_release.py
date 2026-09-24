"""Package the Windows portable and Proxmox/Docker server releases."""

from pathlib import Path
import shutil
import sys
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from program.server import VERSION


PORTABLE_FILES = {
    "Panelbook.exe": ROOT / "dist" / "PanelbookLauncher.exe",
    "README.md": ROOT / "README.md",
    "program/Panelbook.cmd": ROOT / "program" / "Panelbook.cmd",
    "program/PanelbookServer.exe": ROOT / "dist" / "PanelbookServer.exe",
    "program/panelbook.html": ROOT / "program" / "panelbook.html",
    "program/app.js": ROOT / "program" / "app.js",
    "program/styles.css": ROOT / "program" / "styles.css",
    "program/update-portable.ps1": ROOT / "program" / "update-portable.ps1",
}

SERVER_FILES = {
    "README-HOSTING.md": ROOT / "README-HOSTING.md",
    "Dockerfile": ROOT / "Dockerfile",
    ".dockerignore": ROOT / ".dockerignore",
    "compose.yaml": ROOT / "compose.yaml",
    "compose.pull.yaml": ROOT / "compose.pull.yaml",
    ".env.example": ROOT / ".env.example",
    "nginx/panelbook-site.conf.example": ROOT / "nginx" / "panelbook-site.conf.example",
    "program/server.py": ROOT / "program" / "server.py",
    "program/panelbook.html": ROOT / "program" / "panelbook.html",
    "program/app.js": ROOT / "program" / "app.js",
    "program/styles.css": ROOT / "program" / "styles.css",
    "scripts/container_entrypoint.py": ROOT / "scripts" / "container_entrypoint.py",
}


def package(archive, files):
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for name, path in files.items():
            output.write(path, name)
    with ZipFile(archive) as output:
        if output.testzip():
            raise SystemExit("The release ZIP failed verification: " + str(archive))


def main():
    missing = [name for name, path in {**PORTABLE_FILES, **SERVER_FILES}.items() if not path.is_file()]
    if missing:
        raise SystemExit("Missing release files: " + ", ".join(missing))
    destination = ROOT / "dist" / ("v" + VERSION)
    destination.mkdir(parents=True, exist_ok=True)
    portable = destination / ("Panelbook-Portable-v" + VERSION + ".zip")
    server = destination / ("Panelbook-Server-v" + VERSION + ".zip")
    package(portable, PORTABLE_FILES)
    package(server, SERVER_FILES)
    shutil.copy2(ROOT / "RELEASE_NOTES.md", destination / "release-notes.md")
    print(portable)
    print(server)


if __name__ == "__main__":
    main()
