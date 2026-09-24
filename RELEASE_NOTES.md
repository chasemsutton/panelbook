# Panelbook 0.3.0

This is a breaking Windows update. Version 0.2.0 expects the old flat ZIP, and 0.2.1 still uses the unreliable restart path. Close the old app, extract `Panelbook-Portable-v0.3.0.zip` into a new folder, and move your existing `data/` folder beside the new `Panelbook.cmd`. Keep a backup of `data/` until you confirm your accounts and homes appear.

Future portable updates use one ZIP layout. The updater now waits for the old executable to release its file lock, checks that the new server starts, and reloads the existing browser tab. If installation or startup fails, it restores the previous files and records details in `data/updater.log`.
