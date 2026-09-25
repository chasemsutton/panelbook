# Panelbook 0.5.0.5

Panelbook stores electrical panel directories in a local SQLite database and opens its interface in a browser. Version 0.5.0.5 adds column-selectable search above circuits and outlets / switches. Registration is open by default; the super admin can require setup codes. Separate Windows portable and Proxmox server packages include account sharing with viewer or editor access.

## Windows portable app

1. Download `Panelbook-Portable-v0.5.0.5.zip` from the [0.5.0.5 release](https://github.com/chasemsutton/panelbook/releases/tag/v0.5.0.5) and extract it to a folder you can keep.
2. Double-click **`Panelbook.exe`** at the top level. It starts the local server without a console window and opens `http://127.0.0.1:8765/` in your usual browser. Pin `Panelbook.exe` to the taskbar if you want a one-click launcher. Clicking it again while the server is running opens the page in your browser.
3. Choose **Continue locally without a login** to use Panelbook only from this machine, or create a login for accounts and sharing. When creating a login, the setup code is filled automatically when the launcher opens the page.

The folder layout is:

```text
Panelbook.exe          ← run this; icon is built in
README.md
program/
  Panelbook.cmd        ← fallback for source/development use
  PanelbookServer.exe
  panelbook.html
  app.js
  styles.css
  update-portable.ps1
data/                  ← created on first launch
  panelbook.sqlite3
```

Homes are stored in `data/panelbook.sqlite3` beside the launcher. Keep `data/` when moving the app and back it up regularly. A local-only workspace opens automatically at the local address and is unavailable from other machines. Choose **Create login** in the app to add a username and password later; your homes and panels stay in place. Panelbook works offline after installation; checking for updates needs GitHub access.

In a local-only workspace, **Close server when all tabs close** is on by default. A short delay lets page reloads reconnect; if the browser exits without sending a close event, the server stops after its tab heartbeat expires (about three minutes). You can turn the setting off, and that choice persists across launches. On the first launch after upgrading an existing local workspace, 0.5.0.1 turns the setting on once; later choices persist. The setting is removed when you create a login.

The local administrator's **Check for updates** button downloads a newer portable release, checks its SHA-256 digest, replaces app files, and restarts Panelbook. The open browser tab reloads when the new server is ready. It preserves the database in `data/`. If copying or startup fails, the helper restores and restarts the previous app, and writes details to `data/updater.log`. Hosted installations are updated by redeploying the server.

**Moving from 0.4.x:** Version 0.5 changed the Windows executable layout. Extract 0.5.0.5 to a new folder and run the top-level `Panelbook.exe`. The old GUI updater is not used for this move. Export your homes as JSON in the old version and import them in 0.5.0.5 if you want to move data. Keep your old folder until you have checked the import.

**Moving from 0.5.0 to 0.5.0.1:** The 0.5.0 updater only recognizes three-part version tags, so it cannot discover `0.5.0.1`. Close Panelbook, extract the new portable ZIP, and copy your `data/` folder into the new folder. Run the new top-level `Panelbook.exe`. Future four-part version updates can use the GUI button.

`program/Panelbook.cmd` also runs the source version if Python 3.11 or newer is installed and `program/PanelbookServer.exe` is absent. In that mode, start it with `python program/server.py` or the CMD fallback; app updates are done with Git or a new source archive. The portable launcher writes server output to `data/server.stdout.log` and errors to `data/server.stderr.log`.

## Importing 0.1.4 data

In 0.1.4, choose **Export JSON → Everything** in the browser where your old data appears. Then open 0.5.0.5 and choose **Import JSON**. It accepts version 4 exports of an individual panel, a home, or everything. Imported homes are added to the workspace; existing homes remain available. A panel export can be added or used to replace a panel.

If you cannot open the old app, open its original `panelbook.html` at the same path in the same browser to recover its browser storage. Opening the new HTML file with `file://` offers **Export data from this browser** when version 4 data is available for that file's origin. Export before moving or deleting the old files. The 0.5.0.5 server does not automatically read browser storage.

## Accounts and sharing

The first login is the super admin. In **Admin settings**, they can assign or remove ordinary admins. Admins can create and delete standard users, reset their passwords, and make one-time or unlimited-use setup codes. New users can choose **Create account** on the sign-in page and set their own password without a code by default. The super admin can turn on **Require a setup code for new accounts** in **Admin settings**. One-time codes are consumed after successful registration; unlimited-use codes work until revoked. Local-only workspaces can use these features after choosing **Create login**. Use **Share home** to give a user editor or viewer access. Users can change their passwords with **Password**. Search circuits or outlets / switches in the current panel using the field above each table; choose **All fields** or a specific column. A home's owner can delete it with **Delete home**, and a user it is shared with can choose **Leave home**. An editor can change a shared home's panels; a viewer can read, print, and export them. The owner controls sharing. Each account also starts with its own home. Changes from a different browser can cause a save conflict; export your edits and reload before continuing.

If the administrator forgets their password, open a Command Prompt in the `program` folder and run `PanelbookServer.exe --reset-password USERNAME`, then enter a new password. For the hosted server, see [Reset a forgotten password](README-HOSTING.md#reset-a-forgotten-password).

## Home server

For Arcane, paste `compose.yaml` into a project; it pulls the hosted image without a Dockerfile. The older `compose.pull.yaml` works the same way. For a source build, use `compose.build.yaml` and download `Panelbook-Server-v0.5.0.5.zip` from the [0.5.0.5 release](https://github.com/chasemsutton/panelbook/releases/tag/v0.5.0.5). Follow [README-HOSTING.md](README-HOSTING.md) for Proxmox, Docker Compose, LAN HTTP or HTTPS proxy access, firewall access, backups, and updates. The database lives in the Docker named volume `panelbook-data` on the VM.

The app has account passwords, session cookies, roles, and CSRF protection. HTTPS mode adds the `Secure` cookie attribute. For access from outside your home network, use HTTPS and restrict direct access to the backend port to your NGINX machine.

## Working with panels

Choose a home, add main panels, and link subpanels through an assigned 240 V feeder circuit with an amp rating. Click a breaker position to choose single, double, tandem, or quad type. Add circuits with breaker assignments, names, ratings, and wire gauges. Add outlets or switches as numbered points linked to circuits. **Print / PDF** produces a directory; **Export JSON** makes a portable backup.

Panel layout and wire warnings are documentation aids. Check the actual panel labeling and applicable electrical rules with a qualified electrician before making installation decisions.

## Development

The server uses Python's standard library, SQLite, and static HTML/CSS/JavaScript. Run `python -m unittest discover -s tests -v` for its integration tests. The Windows build runs in GitHub Actions: PyInstaller builds `PanelbookServer.exe`, Microsoft C builds the launcher with `scripts/panelbook.ico`, and `python scripts/package_release.py` creates separate portable and server ZIPs without `data/`. The Windows CI smoke tests exercise the launcher, automatic close, and updater.
