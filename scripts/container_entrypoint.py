"""Prepare the data bind mount, then run Panelbook without root privileges."""

import os
from pathlib import Path
import pwd
import sys


def prepare_data(path: Path, uid: int, gid: int) -> None:
    for directory, subdirectories, files in os.walk(path, followlinks=False):
        os.chown(directory, uid, gid)
        for name in subdirectories + files:
            os.chown(os.path.join(directory, name), uid, gid, follow_symlinks=False)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("A server command is required.")
    user = pwd.getpwnam("panelbook")
    if os.geteuid() == 0:
        try:
            prepare_data(Path("/data"), user.pw_uid, user.pw_gid)
            os.setgroups([])
            os.setgid(user.pw_gid)
            os.setuid(user.pw_uid)
        except OSError as error:
            raise SystemExit(f"Could not prepare /data for Panelbook: {error}") from error
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
