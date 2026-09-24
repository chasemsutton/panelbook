# Panelbook 0.3.3

Panelbook stores electrical panel directories in a local SQLite database and opens its interface in a browser. The same app can run on a Windows computer or a home server. Version 0.3.3 fixes automatic updates on Windows. The minimized launcher and optional automatic shutdown for local-only workspaces remain available.

## Windows portable app

1. Download `Panelbook-Portable-v0.3.3.zip` from the [0.3.3 release](https://github.com/chasemsutton/panelbook/releases/tag/v0.3.3) and extract it to a folder you can keep.
2. Double-click **`Panelbook.cmd`** at the top level. It starts the local server in a minimized console window and opens `http://127.0.0.1:8765/` in your usual browser.
3. Choose **Continue locally without a login** to use Panelbook only from this machine, or create a login for accounts and sharing. When creating a login, the setup code is filled automatically if the launcher opens the page. Otherwise, copy it from the Panelbook console.

The folder layout is:

```text
Panelbook.cmd          ← run this
README.md
program/
  Panelbook.exe
  panelbook.html
  app.js
  styles.css
  update-portable.ps1
data/                  ← created on first launch
  panelbook.sqlite3
```

Homes are stored in `data/panelbook.sqlite3` beside the launcher. Keep `data/` when moving the app and back it up regularly. A local-only workspace opens automatically at the local address and is unavailable from other machines. Choose **Create login** in the app to add a username and password later; your homes and panels stay in place. Panelbook works offline after installation; checking for updates needs GitHub access.

In a local-only workspace, select **Close server when all tabs close** to stop Panelbook after the last browser tab closes. The setting is off by default and persists across launches. A short delay lets page reloads reconnect; if the browser exits without sending a close event, the server stops after its tab heartbeat expires (about three minutes). The setting is removed when you create a login.

The local administrator's **Check for updates** button downloads a newer portable release, checks its SHA-256 digest, replaces app files, and restarts Panelbook. The open browser tab reloads when the new server is ready. It preserves the database in `data/`. If copying or startup fails, the helper restores and restarts the previous app, and writes details to `data/updater.log`. Hosted installations are updated by redeploying the server.

**Manual update from 0.2.0 through 0.3.2:** These versions have unreliable or broken updater launch paths. Close Panelbook, extract the 0.3.3 ZIP into a new folder, then copy your existing `data/` folder beside the new `Panelbook.cmd`. Run the new launcher. Keep the original folder as a backup until you confirm your homes and accounts appear. Starting with 0.3.3, use **Check for updates** for future releases.

`Panelbook.cmd` also runs the source version if Python 3.11 or newer is installed and `program/Panelbook.exe` is absent. In that mode, start it with `python program/server.py` or the launcher; app updates are done with Git or a new source archive.

## Importing 0.1.4 data

In 0.1.4, choose **Export JSON → Everything** in the browser where your old data appears. Then open 0.3.3 and choose **Import JSON**. It accepts version 4 exports of an individual panel, a home, or everything. Imported homes are added to the workspace; existing homes remain available. A panel export can be added or used to replace a panel.

If you cannot open the old app, open its original `panelbook.html` at the same path in the same browser to recover its browser storage. Opening the new HTML file with `file://` offers **Export data from this browser** when version 4 data is available for that file's origin. Export before moving or deleting the old files. The 0.3.3 server does not automatically read browser storage.

## Accounts and sharing

The first login is an administrator. Use **Users** to add accounts, then **Share home** to give a user editor or viewer access. Local-only workspaces can use these features after choosing **Create login**. Users can change their passwords with **Password**. An editor can change a shared home's panels; a viewer can read, print, and export them. The owner controls sharing. Each account also starts with its own home. Changes from a different browser can cause a save conflict; export your edits and reload before continuing.

## Home server

Run `docker compose up -d --build` from the source checkout, or run `python program/server.py --host 0.0.0.0 --port 8765 --data-dir /path/to/data --no-browser --secure-cookies` with Python 3.11+. The Compose file publishes only to the server's loopback address at port 8765. Put an HTTPS reverse proxy in front of it for remote access and preserve the incoming `Host` header. The server prints the first-account setup code in its logs (`docker compose logs panelbook`). Keep the `/data` volume or your configured data directory when redeploying. Back up the database with SQLite's backup API or stop the server before copying the database file.

The app has account passwords, session cookies, roles, and CSRF protection. For access from outside your home network, use HTTPS and your usual network access controls. Do not publish the bare HTTP port to the internet.

## Working with panels

Choose a home, add main panels, and link subpanels through an assigned 240 V feeder circuit with an amp rating. Click a breaker position to choose single, double, tandem, or quad type. Add circuits with breaker assignments, names, ratings, and wire gauges. Add outlets or switches as numbered points linked to circuits. **Print / PDF** produces a directory; **Export JSON** makes a portable backup.

Panel layout and wire warnings are documentation aids. Check the actual panel labeling and applicable electrical rules with a qualified electrician before making installation decisions.

## Development

The server uses Python's standard library, SQLite, and static HTML/CSS/JavaScript. Run `python -m unittest discover -s tests -v` for its integration tests. To build the Windows portable executable, install PyInstaller and run `python -m PyInstaller --onefile --console --name Panelbook program/server.py`, then `python scripts/package_release.py`. The packager puts `Panelbook.cmd` and this README at the ZIP root and the executable, HTML, JavaScript, CSS, and updater script in `program/`. Publish only `Panelbook-Portable-vX.Y.Z.zip`; never package `data/`. On Windows, run `python tests/smoke_updater_windows.py` and `python tests/smoke_launcher_windows.py` after packaging to verify the updater and launcher.
