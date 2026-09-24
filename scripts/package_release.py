"""Package the single Windows portable update format after building Panelbook.exe."""

from pathlib import Path
import shutil
import sys
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from program.server import VERSION


FILES = {
    "Panelbook.cmd": ROOT / "Panelbook.cmd",
    "README.md": ROOT / "README.md",
    "program/Panelbook.exe": ROOT / "dist" / "Panelbook.exe",
    "program/panelbook.html": ROOT / "program" / "panelbook.html",
    "program/app.js": ROOT / "program" / "app.js",
    "program/styles.css": ROOT / "program" / "styles.css",
    "program/update-portable.ps1": ROOT / "program" / "update-portable.ps1",
}


def main():
    missing = [name for name, path in FILES.items() if not path.is_file()]
    if missing:
        raise SystemExit("Missing release files: " + ", ".join(missing))
    destination = ROOT / "dist" / ("v" + VERSION)
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / ("Panelbook-Portable-v" + VERSION + ".zip")
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for name, path in FILES.items():
            output.write(path, name)
    with ZipFile(archive) as output:
        if output.testzip():
            raise SystemExit("The release ZIP failed verification.")
    shutil.copy2(ROOT / "RELEASE_NOTES.md", destination / "release-notes.md")
    print(archive)


if __name__ == "__main__":
    main()
