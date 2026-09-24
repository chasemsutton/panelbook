# Host Panelbook 0.5.0.1 on Proxmox

Panelbook runs in Docker Compose inside a Linux VM. The one-file `compose.pull.yaml` pulls a prebuilt image from GitHub Container Registry, including the app and its runtime; it works in Arcane without uploading a Dockerfile or `program/` folder. `compose.yaml` remains available for building the image from source. Both setups use the same database format and an NGINX reverse proxy with HTTPS.

## Arcane: deploy from one Compose file

In Arcane, create a project named `panelbook` and paste the contents of [`compose.pull.yaml`](compose.pull.yaml) as its Compose configuration. Set `PANELBOOK_BIND_IP` in Arcane's environment editor if you want to bind TCP 8765 to a particular VM interface; without it, Docker listens on all IPv4 interfaces. Choose **Deploy**. Arcane pulls `ghcr.io/chasemsutton/panelbook:latest`; no Dockerfile, source files, or separate image host are needed. Keep the `panelbook_data` volume when redeploying. To update later, redeploy the project. Compose pulls the current `latest` image each time; running containers do not update themselves. For a fixed version, replace `latest` with the release number and remove `pull_policy: always`.

Allow TCP 8765 only from your NGINX machine with the VM or Proxmox firewall. Access Panelbook through the HTTPS domain on NGINX, including from the LAN. The direct VM HTTP address does not support hosted login because the app uses `Secure` cookies. The NGINX configuration and LAN DNS steps are below.

## Build from source with Docker Compose

## 1. Prepare the VM and network

Create a small Debian or Ubuntu VM in Proxmox with a stable private IP. Install Docker Engine and the Docker Compose plugin using [Docker's installation instructions](https://docs.docker.com/engine/install/). Extract this ZIP into a persistent directory on the VM, such as `/opt/panelbook`.

Copy `.env.example` to `.env` and set `PANELBOOK_BIND_IP` to the VM's private IP. This chooses which VM address Docker listens on; it does **not** restrict which client IPs can connect. Use `0.0.0.0` if Docker needs to listen on all IPv4 interfaces, and use firewall rules to restrict source IPs or LAN subnets. The recommended setup allows inbound TCP 8765 **only from the NGINX machine's private IP**. Do not forward port 8765 from your router. The HTTP connection from NGINX to Panelbook should stay on a trusted private network or VPN. Docker-published ports can bypass UFW rules, so use the Proxmox firewall or Docker's [`DOCKER-USER` filtering](https://docs.docker.com/engine/network/packet-filtering-firewalls/) when limiting access to this port.

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

### Use Panelbook from your LAN

LAN clients can use the **same HTTPS address** as remote clients. In your LAN DNS or router's DNS override, resolve `panelbook.example.com` to the NGINX machine's private IP; keep public DNS pointed at its public entry point. Allow your LAN subnet (for example, `192.168.1.0/24`) to reach the NGINX machine on TCP 443. Keep TCP 8765 on the Panelbook VM limited to the NGINX machine. This makes LAN browser traffic stay on the LAN while NGINX still provides HTTPS and the same certificate. Use the domain name in the browser, not the VM's IP address.

Direct `http://VM-IP:8765/` is not a login endpoint in this configuration. The hosted server requires HTTPS origins and sets `Secure` session cookies; browsers do not send those cookies over ordinary HTTP. A bind address such as `0.0.0.0` cannot change that. If the NGINX machine itself has multiple network interfaces, configure its firewall to allow the desired LAN subnet or all intended clients on TCP 443.

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
