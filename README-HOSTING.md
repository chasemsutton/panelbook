# Host Panelbook 0.5.0.2 on Proxmox

Panelbook runs in Docker Compose inside a Linux VM. The default `compose.yaml` pulls a prebuilt image from GitHub Container Registry, including the app and its runtime; it works in Arcane without uploading a Dockerfile or `program/` folder. `compose.build.yaml` builds the image from source. The older `compose.pull.yaml` remains available for existing projects and is equivalent to `compose.yaml`. All three use the same `panelbook-data` volume. Use `http://VM-IP:8765/` on a trusted LAN, or set up an HTTPS reverse proxy.

## Arcane: deploy from one Compose file

In Arcane, create a project named `panelbook` and paste the contents of [`compose.yaml`](compose.yaml) as its Compose configuration. Set `PANELBOOK_BIND_IP` in Arcane's environment editor if you want to bind TCP 8765 to a particular VM interface; without it, Docker listens on all IPv4 interfaces. Leave `PANELBOOK_PUBLIC_SCHEME` unset for direct HTTP access on your LAN, or set it to `https` when using an HTTPS reverse proxy. Choose **Deploy**. Arcane pulls `ghcr.io/chasemsutton/panelbook:latest`; no Dockerfile, source files, or separate image host are needed. Panelbook runs as a non-root user (UID 10001) and never starts as root. Arcane shows only one running service. The database is stored in the Docker named volume `panelbook-data`, which Docker creates on the first deploy and keeps across redeploys and image updates; `/data` is its path inside the container. If you deployed an earlier build that stored data in `/var/panelbook/data`, follow [Move data from /var/panelbook/data](#move-data-from-varpanelbookdata) before redeploying. To update later, redeploy the project. Compose pulls the current `latest` image each time; running containers do not update themselves. For a fixed version, replace `latest` with a published image tag and remove `pull_policy: always`.

For direct LAN access, open `http://VM-IP:8765/` and allow TCP 8765 only from the intended LAN clients in the VM or Proxmox firewall. HTTP sends passwords and session cookies without encryption, so use this only on a network you trust. If you need access over the internet or an untrusted network, use the HTTPS reverse proxy described below and set `PANELBOOK_PUBLIC_SCHEME=https` in Arcane.

For the default command-line deployment, put `compose.yaml` in a directory on the VM and run `docker compose up -d`. Compose pulls the prebuilt image; no Dockerfile or source files are needed. To update it later, run `docker compose pull panelbook` followed by `docker compose up -d panelbook`. The `panelbook-data` volume remains in place.

## Build from source with Docker Compose

### 1. Prepare the VM and network

Create a small Debian or Ubuntu VM in Proxmox with a stable private IP. Install Docker Engine and the Docker Compose plugin using [Docker's installation instructions](https://docs.docker.com/engine/install/). Extract this ZIP into a persistent directory on the VM, such as `/opt/panelbook`.

Copy `.env.example` to `.env` and set `PANELBOOK_BIND_IP` to the VM's private IP. This chooses which VM address Docker listens on; it does **not** restrict which client IPs can connect. Use `0.0.0.0` if Docker needs to listen on all IPv4 interfaces, and use firewall rules to restrict source IPs or LAN subnets. Leave `PANELBOOK_PUBLIC_SCHEME=http` for direct LAN access. Set it to `https` when using the reverse proxy below. Do not forward port 8765 from your router. Docker-published ports can bypass UFW rules, so use the Proxmox firewall or Docker's [`DOCKER-USER` filtering](https://docs.docker.com/engine/network/packet-filtering-firewalls/) when limiting access to this port.

The included `compose.build.yaml` is ready to use after setting `.env`. Its contents are:

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
    environment:
      - PANELBOOK_PUBLIC_SCHEME
    volumes:
      - panelbook-data:/data
    ports:
      - "${PANELBOOK_BIND_IP:?Set PANELBOOK_BIND_IP in .env}:8765:8765"

volumes:
  panelbook-data:
    name: panelbook-data
```

### 2. Start Panelbook

From the extracted directory, run:

```sh
cp .env.example .env
# Edit .env to use this VM's private IP before continuing.
docker compose -f compose.build.yaml up -d --build
docker compose -f compose.build.yaml ps
```

Panelbook runs as a non-root user with a read-only filesystem; only the `panelbook-data` volume is writable. Docker keeps the volume across rebuilds and `docker compose down`. Do not run `docker compose down -v`, which deletes it. The server uses HTTP-only session cookies, adds the `Secure` attribute in HTTPS mode, and disables the Windows in-app updater and local-only login on this hosted address.

## Configure NGINX and HTTPS

Set `PANELBOOK_PUBLIC_SCHEME=https` in the Compose environment before using this configuration. On the separate NGINX machine, start from `nginx/panelbook-site.conf.example`. Replace `panelbook.example.com`, both TLS certificate paths, and `192.168.1.50` with your real domain, certificate, and Panelbook VM private IP. Use a certificate already managed by your NGINX setup or obtain one before enabling the site. The config redirects HTTP to HTTPS and forwards the original `Host` header, which Panelbook uses to check request origin. Test and reload NGINX:

```sh
sudo nginx -t
sudo systemctl reload nginx
```

Open `https://your-domain/`. Panelbook must be served at the domain root path, not under a subpath. Check that the page is HTTPS before creating the first account.

### Use Panelbook from your LAN

LAN clients can use the **same HTTPS address** as remote clients. In your LAN DNS or router's DNS override, resolve `panelbook.example.com` to the NGINX machine's private IP; keep public DNS pointed at its public entry point. Allow your LAN subnet (for example, `192.168.1.0/24`) to reach the NGINX machine on TCP 443. Keep TCP 8765 on the Panelbook VM limited to the NGINX machine. This makes LAN browser traffic stay on the LAN while NGINX still provides HTTPS and the same certificate. Use the domain name in the browser, not the VM's IP address.

When `PANELBOOK_PUBLIC_SCHEME=https`, use the HTTPS domain for login. The direct `http://VM-IP:8765/` address will reject account actions in this mode. If the NGINX machine itself has multiple network interfaces, configure its firewall to allow the desired LAN subnet or all intended clients on TCP 443.

## Create accounts and share homes

Get the one-time first-account setup code from the container logs (`docker compose logs panelbook`, or the container's logs in Arcane). Enter it on the setup page at your chosen HTTP or HTTPS URL to create the super admin login. Keep the code and logs private. The super admin can open **Admin settings** to create users, assign or remove ordinary admins, and make setup codes. Any admin can create and delete standard users, reset their passwords, and make or revoke setup codes. A one-time code is consumed by the first successful registration; an unlimited-use code works until an admin revokes it. Give a code to someone so they can choose **Create account with setup code** on the sign-in page and set their own password. Codes are shown only once when created. The super admin account cannot be deleted or demoted in the app; ordinary admins cannot manage other admins. The owner of a home can use **Share home** to grant **Viewer** access (read, print, and export) or **Editor** access (change panels). Only the owner can change or remove a share. A new user also receives a private home. Users can change their own passwords from **Password**. A deleted user's homes move to the admin who deleted them. A home's owner can delete it with **Delete home**, and someone it is shared with can use **Leave home**. Every account keeps at least one home.

### Upgrade an existing installation to super admin

Keep the existing `panelbook-data` volume and deploy a version of Panelbook with this feature. On first startup, the database migration automatically makes the earliest existing administrator the super admin. Their username, password, homes, and sessions remain in place. Sign in with that account and open **Admin settings**; no fresh setup code or database reset is needed.

For the pull-based Compose project, update the image and recreate only the service:

```sh
docker compose pull panelbook
docker compose up -d panelbook
```

In Arcane, pull the updated image and redeploy the project with its existing `panelbook-data` volume. For a source-built project, use `docker compose -f compose.build.yaml up -d --build panelbook`. Existing projects using `compose.pull.yaml` can keep using it. Do not delete the volume or run `docker compose down -v`. If an old database has no administrator, the migration promotes its oldest account; check the **Admin settings** label after upgrading.

### Reset a forgotten password

An administrator can reset a standard user's password in **Admin settings**; the super admin can also reset an ordinary admin's password. If the super admin is locked out, run this on the VM and enter the new password when prompted. Existing sign-ins for that user end:

```sh
docker exec -it panelbook-panelbook-1 python program/server.py --data-dir /data --reset-password USERNAME
```

`panelbook-panelbook-1` is the container name for a project named `panelbook`; `docker ps` shows it if yours differs.

Do not choose **Continue locally without a login** for the hosted installation; that option is only available on a Windows app opened from its own machine.

## Move an existing Windows workspace to the VM

If the Windows workspace uses **Continue locally without a login**, first open it on Windows and choose **Create login**. A local-only account cannot sign in to the hosted server. Close the Windows server completely, then copy its `data/panelbook.sqlite3` to a directory named `old-data` on the VM. If `data/panelbook.sqlite3-wal` and `data/panelbook.sqlite3-shm` exist after shutdown, copy those too. Keep the original Windows folder as a backup.

Stop the hosted server (in Arcane, stop the project), copy the database into the volume with SQLite's backup API, and start it again. `old-data` is a scratch copy: SQLite may need to write to it while reading, so give the container user ownership of it:

```sh
docker compose stop panelbook
sudo chown -R 10001:10001 old-data
docker run --rm -v panelbook-data:/data -v "$PWD/old-data:/import" ghcr.io/chasemsutton/panelbook:latest python -c "import sqlite3; source=sqlite3.connect('/import/panelbook.sqlite3'); target=sqlite3.connect('/data/panelbook.sqlite3'); source.backup(target); target.close(); source.close()"
docker compose start panelbook
```

Sign in with the login created on Windows. The home and sharing data are preserved. Remove `old-data` from the VM after verifying the migration and keeping a separate backup.

## Back up and update

The SQLite database lives in the `panelbook-data` volume. Stop the server (in Arcane, stop the project) before copying a backup so the SQLite database and its write-ahead log are consistent:

```sh
docker compose stop panelbook
docker run --rm -v panelbook-data:/data:ro -v "$PWD:/backup" alpine tar -czf /backup/panelbook-data-backup.tgz -C /data .
docker compose start panelbook
```

To restore that backup, stop the server and run:

```sh
docker run --rm -v panelbook-data:/data -v "$PWD:/backup:ro" alpine sh -c 'rm -f /data/panelbook.sqlite3* && tar -xzf /backup/panelbook-data-backup.tgz -C /data && chown -R 10001:10001 /data'
```

Keep a backup outside the VM as well. To update a source build, save a backup, extract the new server ZIP over the existing app files (keep `.env`), and run `docker compose -f compose.build.yaml up -d --build`. The volume and accounts stay in place. For an Arcane deployment, redeploy the project to pull the latest image. Check the container status and logs after updating.

## Move data from /var/panelbook/data

Earlier builds stored the database in `/var/panelbook/data` on the VM and started as root to set its permissions. The current image runs as UID 10001 and cannot write that directory, so it exits with `Could not open /data/panelbook.sqlite3` until the data is moved into the named volume.

1. Stop and remove the old container: `docker compose down` from the project directory, or stop the project in Arcane.
2. If the new version already started once, it created an empty `panelbook-data` volume. Remove it with `docker volume rm panelbook-data` so it cannot mix with your real database. Skip this if the command reports that the volume does not exist.
3. Copy the data and give it to the container user:

   ```sh
   docker run --rm -v /var/panelbook/data:/from:ro -v panelbook-data:/to alpine sh -c 'cp -a /from/. /to/ && chown -R 10001:10001 /to'
   ```

4. Use the current `compose.yaml` for the prebuilt image and run `docker compose up -d`, or use `compose.build.yaml` for a source build and run `docker compose -f compose.build.yaml up -d --build`. Existing Arcane projects can keep their `compose.pull.yaml` configuration.

Sign in and check your homes. Keep `/var/panelbook/data` as a backup until you are satisfied, then remove it with `sudo rm -r /var/panelbook/data`.
