# Panelbook 0.4.2

The Windows GUI updater now starts the replacement app with a fresh PyInstaller runtime. Earlier helpers inherited a temporary extraction folder from the old app, causing `python311.dll` load failures after shutdown. The helper also records startup errors, waits for the old server to release its port, retries transient startup failures, and verifies rollback.

The page header now displays the version reported by the running server instead of the stale `v0.3.2` text. After an in-app update, the server runs in the background without opening a blank console window.

The portable and hosted release packages are `Panelbook-Portable-v0.4.2.zip` and `Panelbook-Server-v0.4.2.zip`. Existing 0.3.3 through 0.4.1 installations need one manual update or a replacement `program/update-portable.ps1` from this release before their GUI updater can use the fix. See `README.md` for the steps.
