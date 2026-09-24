# Panelbook 0.4.0

This release includes two downloads: `Panelbook-Portable-v0.4.0.zip` for Windows and `Panelbook-Server-v0.4.0.zip` for a Proxmox Linux VM. The Windows in-app updater downloads only the portable ZIP.

The server ZIP includes Docker Compose with a private-IP bind, non-root container, persistent database volume, secure cookies, and an NGINX HTTPS reverse proxy example for a separate machine. See `README-HOSTING.md` in the server ZIP for setup, firewall, first login, backup, and update steps.

Home sharing supports viewer access for reading, printing, and exporting, and editor access for changing panels. The owner manages shares. Hosted requests now require an HTTPS origin when secure cookies are enabled.

Windows versions 0.3.3 and newer can install 0.4.0 in the app. Versions 0.2.0 through 0.3.2 require the manual update described in README.md.
