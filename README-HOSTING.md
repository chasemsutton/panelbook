# Host Panelbook 0.5.0 on Proxmox

This package runs Panelbook in Docker Compose inside a Linux VM. It is intended for an NGINX reverse proxy on a separate machine and an HTTPS domain. The Windows portable app is a separate download. Both use the same database format.

## 1. Prepare the VM and network

Create a small Debian or Ubuntu VM in Proxmox with a stable private IP. Install Docker Engine and the Docker Compose plugin using [Docker's installation instructions](https://docs.docker.com/engine/install/). Extract this ZIP into a persistent directory on the VM, such as `/opt/panelbook`.

Copy `.env.example` to `.env` and set `PANELBOOK_BIND_IP` to the VM's private IP. The Compose file publishes only TCP 8765 on that address. On the VM or Proxmox firewall, allow inbound TCP 8765 **only from the NGINX machine's private IP**. Do not forward port 8765 from your router. The HTTP connection from NGINX to Panelbook should stay on a trusted private network or VPN.

The included `compose.yaml` is ready to use after setting `.env`. Its contents are:

```yaml
name: panelbook

services:
  panelbook:
    build: .
    init: true
    restart: unless-stopped
    read_only: true
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp:rw,nosuid,noexec,size=64m
    volumes:
      - panelbook_data:/data
    ports:
      - "${PANELBOOK_BIND_IP:?Set PANELBOOK_BIND_IP in .env}:8765:8765"
volumes:
  panelbook_data:
    name: panelbook_data
```

## 2. Start Panelbook

From the extracted directory, run:

```sh
cp .env.example .env
# Edit .env to use this VM's private IP before continuing.
docker compose up -d --build
docker compose ps
```

The container runs as a non-root user with a read-only filesystem; only its named `panelbook_data` volume is writable. Compose keeps this volume across container rebuilds. The server uses secure, HTTP-only session cookies and disables the Windows in-app updater and local-only login on this hosted address.

## 3. Configure NGINX and HTTPS

On the separate NGINX machine, start from `nginx/panelbook-site.conf.example`. Replace `panelbook.example.com`, both TLS certificate paths, and `192.168.1.50` with your real domain, certificate, and Panelbook VM private IP. Use a certificate already managed by your NGINX setup or obtain one before enabling the site. The config redirects HTTP to HTTPS and forwards the original `Host` header, which Panelbook uses to check request origin. Test and reload NGINX:

```sh
sudo nginx -t
sudo systemctl reload nginx
```

Open `https://your-domain/`. Panelbook must be served at the domain root path, not under a subpath. Check that the page is HTTPS before creating the first account.

## 4. Create accounts and share homes

Get the one-time first-account setup code from `docker compose logs panelbook`. Enter it on the HTTPS setup page to create the administrator login. Keep the code and logs private. In **Users**, create a login for each person. The owner of a home can use **Share home** to grant **Viewer** access (read, print, and export) or **Editor** access (change panels). Only the owner can change or remove a share. A new user also receives a private home. Users can change their own passwords from **Password**.

Do not choose **Continue locally without a login** for the hosted installation; that option is only available on a Windows app opened from its own machine.

## Move an existing Windows workspace to the VM

If the Windows workspace uses **Continue locally without a login**, first open it on Windows and choose **Create login**. A local-only account cannot sign in to the hosted server. Close the Windows server completely, then copy its `data/panelbook.sqlite3` to a directory named `old-data` beside `compose.yaml` on the VM. If `data/panelbook.sqlite3-wal` and `data/panelbook.sqlite3-shm` exist after shutdown, copy those too. Make `old-data` readable by the container user, and keep the original Windows folder as a backup.

Stop the hosted server, copy the database with SQLite's backup API, and restart it:

```sh
docker compose stop panelbook
docker compose run --rm --no-deps -v "$PWD/old-data:/import:ro" panelbook python -c "import sqlite3; source=sqlite3.connect('file:/import/panelbook.sqlite3?mode=ro', uri=True); target=sqlite3.connect('/data/panelbook.sqlite3'); source.backup(target); target.close(); source.close()"
docker compose start panelbook
```

Sign in with the login created on Windows. The home and sharing data are preserved. Remove `old-data` from the VM after verifying the migration and keeping a separate backup.

## Back up and update

The SQLite database lives in the Docker volume named `panelbook_data`. Stop the server before copying a filesystem backup so the SQLite database and its write-ahead log are consistent:

```sh
docker compose stop panelbook
docker run --rm -v panelbook_data:/data:ro -v "$PWD":/backup alpine tar -czf /backup/panelbook-data-backup.tgz -C /data .
docker compose start panelbook
```

Keep a backup outside the VM as well. To update, save a backup, extract the new server ZIP over the existing app files (keep `.env`), and run `docker compose up -d --build`. The named volume and accounts stay in place. Check `docker compose ps` and `docker compose logs --tail=50 panelbook` after updating. Do not run `docker compose down -v`, which removes the database volume.
