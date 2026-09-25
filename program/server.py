"""Panelbook's portable and hosted HTTP server. Uses only the Python standard library."""

import argparse
import getpass
import hashlib
import hmac
import ipaddress
import json
import os
import re
import subprocess
import secrets
import sqlite3
import sys
import threading
import time
import webbrowser
import urllib.request
from contextlib import contextmanager
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


VERSION = "0.5.0.2"
ROOT = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
PROGRAM_LAYOUT = ROOT.name.lower() == "program"
APP_ROOT = ROOT.parent if PROGRAM_LAYOUT else ROOT
STATIC = {"/": ("panelbook.html", "text/html; charset=utf-8"),
          "/panelbook.html": ("panelbook.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8")}
SESSION_AGE = 7 * 24 * 60 * 60
MAX_BODY = 20 * 1024 * 1024
MAX_PUBLIC_BODY = 64 * 1024
PUBLIC_POSTS = ("/api/setup", "/api/setup/local", "/api/login", "/api/register")
REQUEST_TIMEOUT = 30
MAX_ID = 2**53 - 1
RELEASES_URL = "https://api.github.com/repos/chasemsutton/panelbook/releases?per_page=30"


def version_tuple(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?", value)
    return tuple(int(part or 0) for part in match.groups()) if match else None


def available_release():
    request = urllib.request.Request(RELEASES_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "Panelbook/" + VERSION})
    with urllib.request.urlopen(request, timeout=15) as response:
        releases = json.load(response)
    current = version_tuple(VERSION)
    for release in sorted(releases, key=lambda item: version_tuple(item.get("tag_name", "")) or (0, 0, 0, 0), reverse=True):
        version = version_tuple(release.get("tag_name", ""))
        if release.get("draft") or release.get("prerelease") or version is None or version <= current:
            continue
        name = "Panelbook-Portable-%s.zip" % release["tag_name"]
        asset = next((item for item in release.get("assets", []) if item.get("name") == name), None)
        if asset and asset.get("digest", "").startswith("sha256:"):
            return {"version": release["tag_name"], "url": asset["browser_download_url"], "digest": asset["digest"][7:]}
    return None


class ApiError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def password_hash(password, salt=None):
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
        raise ApiError(400, "Password must be 12 to 1024 characters.")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)
    return "pbkdf2_sha256$600000$%s$%s" % (salt.hex(), digest.hex())


def password_matches(password, stored):
    try:
        algorithm, rounds, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, AttributeError):
        return False


def valid_id(value):
    return type(value) is int and 0 < value <= MAX_ID


def initial_panel(panel_id):
    return {"id": panel_id, "name": "Main panel", "kind": "main", "parentPanelId": None,
            "parentCircuitId": None, "spaces": 24, "types": {}, "circuits": [],
            "nextCircuitId": 1, "points": [], "nextPointId": 1}


def validate_home(home):
    """Return a copy of home that holds only known, validated fields."""
    if not isinstance(home, dict) or not isinstance(home.get("name"), str) or not 1 <= len(home["name"].strip()) <= 80:
        raise ApiError(400, "Invalid home name.")
    panels = home.get("panels")
    if not isinstance(panels, list) or not 1 <= len(panels) <= 100:
        raise ApiError(400, "A home must have 1 to 100 panels.")
    clean_panels = []
    circuit_ids_by_panel = {}
    for panel in panels:
        if not isinstance(panel, dict) or not valid_id(panel.get("id")) or panel["id"] in circuit_ids_by_panel:
            raise ApiError(400, "Invalid or duplicate panel ID.")
        if panel.get("kind") not in ("main", "sub") or not isinstance(panel.get("name"), str) or len(panel["name"]) > 80:
            raise ApiError(400, "Invalid panel details.")
        spaces = panel.get("spaces")
        if type(spaces) is not int or spaces < 12 or spaces > 42 or spaces % 2:
            raise ApiError(400, "Invalid panel space count.")
        types = panel.get("types")
        if not isinstance(types, dict) or len(types) > spaces:
            raise ApiError(400, "Invalid breaker layout.")
        for position, breaker_type in types.items():
            if not position.isdecimal() or not 1 <= int(position) <= spaces or breaker_type not in ("single", "double", "tandem", "quad"):
                raise ApiError(400, "Invalid breaker type or position.")
        circuits = panel.get("circuits")
        points = panel.get("points")
        if not isinstance(circuits, list) or len(circuits) > 84 or not isinstance(points, list) or len(points) > 1000:
            raise ApiError(400, "Too many circuits or points.")
        next_circuit = panel.get("nextCircuitId")
        next_point = panel.get("nextPointId")
        if not valid_id(next_circuit) or not valid_id(next_point):
            raise ApiError(400, "Invalid circuit or point numbering.")
        circuit_ids, assignments, clean_circuits = set(), set(), []
        for circuit in circuits:
            if not isinstance(circuit, dict) or not valid_id(circuit.get("id")) or circuit["id"] >= next_circuit or circuit["id"] in circuit_ids:
                raise ApiError(400, "Invalid circuit ID.")
            circuit_ids.add(circuit["id"])
            assignment = circuit.get("assignment")
            if not isinstance(assignment, str) or len(assignment) > 12 or assignment in assignments and assignment:
                raise ApiError(400, "Invalid circuit assignment.")
            if assignment:
                assignments.add(assignment)
            voltage = circuit.get("voltage")
            if not isinstance(circuit.get("name"), str) or len(circuit["name"]) > 100 or type(voltage) is not int or voltage not in (120, 240) or circuit.get("labelMode") not in ("circuits", "points"):
                raise ApiError(400, "Invalid circuit details.")
            amps = circuit.get("amps")
            if amps is not None and (type(amps) is not int or not 1 <= amps <= 400):
                raise ApiError(400, "Invalid circuit rating.")
            if circuit.get("gauge") not in ("", "14", "12", "10", "8", "6", "4", "2", "1/0"):
                raise ApiError(400, "Invalid wire gauge.")
            clean_circuits.append({"id": circuit["id"], "name": circuit["name"], "assignment": assignment, "voltage": voltage,
                                   "amps": amps, "gauge": circuit["gauge"], "labelMode": circuit["labelMode"]})
        point_ids, clean_points = set(), []
        for point in points:
            if not isinstance(point, dict) or not valid_id(point.get("id")) or point["id"] >= next_point or point["id"] in point_ids:
                raise ApiError(400, "Invalid point ID.")
            point_ids.add(point["id"])
            circuit_id = point.get("circuitId")
            if circuit_id is not None and (not valid_id(circuit_id) or circuit_id not in circuit_ids):
                raise ApiError(400, "Point references a missing circuit.")
            if not isinstance(point.get("name"), str) or len(point["name"]) > 160 or not isinstance(point.get("location"), str) or len(point["location"]) > 500:
                raise ApiError(400, "Invalid point details.")
            clean_points.append({"id": point["id"], "circuitId": circuit_id, "name": point["name"], "location": point["location"]})
        circuit_ids_by_panel[panel["id"]] = circuit_ids
        clean_panels.append({"id": panel["id"], "name": panel["name"], "kind": panel["kind"],
                             "parentPanelId": panel.get("parentPanelId"), "parentCircuitId": panel.get("parentCircuitId"),
                             "spaces": spaces, "types": dict(types), "circuits": clean_circuits, "nextCircuitId": next_circuit,
                             "points": clean_points, "nextPointId": next_point})
    by_id = {panel["id"]: panel for panel in clean_panels}
    if not any(panel["kind"] == "main" for panel in clean_panels):
        raise ApiError(400, "Each home needs a main panel.")
    for panel in clean_panels:
        parent_id, circuit_id = panel["parentPanelId"], panel["parentCircuitId"]
        if panel["kind"] == "main":
            if parent_id is not None or circuit_id is not None:
                raise ApiError(400, "A main panel cannot have a feeder.")
            continue
        if not valid_id(parent_id) or parent_id not in by_id or parent_id == panel["id"] or circuit_id is not None and not valid_id(circuit_id):
            raise ApiError(400, "Invalid subpanel feeder.")
        if circuit_id is not None and circuit_id not in circuit_ids_by_panel[parent_id]:
            # The app shows a missing feeder as "feeder required". Store it the
            # same way so older data with a stale link can still be saved.
            panel["parentCircuitId"] = None
        seen = {panel["id"]}
        cursor = by_id[parent_id]
        while cursor:
            if cursor["id"] in seen:
                raise ApiError(400, "Circular subpanel link.")
            seen.add(cursor["id"])
            cursor = by_id.get(cursor["parentPanelId"])
    return {"name": home["name"].strip(), "panels": clean_panels}


def connect_db(path):
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


@contextmanager
def database(path):
    connection = connect_db(path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with database(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,
                is_super_admin INTEGER NOT NULL DEFAULT 0,
                is_local INTEGER NOT NULL DEFAULT 0,
                auto_close INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS homes (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, content TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS memberships (
                home_id INTEGER NOT NULL REFERENCES homes(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')),
                PRIMARY KEY(home_id,user_id)
            );
            CREATE TABLE IF NOT EXISTS setup_codes (
                id INTEGER PRIMARY KEY, code_hash TEXT NOT NULL UNIQUE,
                unlimited INTEGER NOT NULL CHECK(unlimited IN (0,1)),
                created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
            );
        """)
        if "is_super_admin" not in {row["name"] for row in db.execute("PRAGMA table_info(users)")}:
            db.execute("ALTER TABLE users ADD COLUMN is_super_admin INTEGER NOT NULL DEFAULT 0")
            first = db.execute("SELECT id FROM users ORDER BY is_admin DESC,id LIMIT 1").fetchone()
            if first:
                db.execute("UPDATE users SET is_admin=1,is_super_admin=1 WHERE id=?", (first["id"],))
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_super_admin ON users(is_super_admin) WHERE is_super_admin=1")
        if "is_local" not in {row["name"] for row in db.execute("PRAGMA table_info(users)")}:
            db.execute("ALTER TABLE users ADD COLUMN is_local INTEGER NOT NULL DEFAULT 0")
        if "auto_close" not in {row["name"] for row in db.execute("PRAGMA table_info(users)")}:
            db.execute("ALTER TABLE users ADD COLUMN auto_close INTEGER NOT NULL DEFAULT 0")
        if db.execute("PRAGMA user_version").fetchone()[0] < 1:
            # 0.5.0 left local workspaces running invisibly unless users found
            # the checkbox. Make the new default effective once on upgrade.
            db.execute("UPDATE users SET auto_close=1 WHERE is_local=1")
            db.execute("PRAGMA user_version=1")


def create_home(db, user_id, name="Home", panels=None):
    panels = panels or [initial_panel(secrets.randbelow(2**45) + 1)]
    clean = validate_home({"name": name, "panels": panels})
    cursor = db.execute("INSERT INTO homes(name,content) VALUES(?,?)", (clean["name"], json.dumps(clean, separators=(",", ":"))))
    home_id = cursor.lastrowid
    db.execute("INSERT INTO memberships(home_id,user_id,role) VALUES(?,?,'owner')", (home_id, user_id))
    return {"id": home_id, **clean, "revision": 1, "role": "owner"}


class PanelbookServer(ThreadingHTTPServer):
    daemon_threads = True
    presence_lease = 180
    presence_grace = 8

    def __init__(self, address, db_path, secure_cookies=False, local_mode=False):
        super().__init__(address, PanelbookHandler)
        self.db_path = db_path
        self.secure_cookies = secure_cookies
        self.local_mode = local_mode
        self.setup_token = secrets.token_urlsafe(18)
        self.login_failures = {}
        self.login_lock = threading.Lock()
        self.presence_lock = threading.Lock()
        self.presence_stop = threading.Event()
        self.presence_tabs = {}
        self.presence_seen = False
        self.presence_empty_since = None
        self.presence_thread = None
        with database(db_path) as db:
            row = db.execute("SELECT auto_close FROM users WHERE is_local=1").fetchone()
            self.auto_close_enabled = bool(row and row["auto_close"])

    def set_auto_close(self, enabled):
        with self.presence_lock:
            self.auto_close_enabled = enabled

    def record_presence(self, tab_id, active):
        with self.presence_lock:
            now = time.monotonic()
            if active:
                self.presence_tabs[tab_id] = now
            else:
                self.presence_tabs.pop(tab_id, None)
            self.presence_seen = True
            self.presence_empty_since = None if self.presence_tabs else now
            if self.presence_thread is None:
                self.presence_thread = threading.Thread(target=self.watch_presence, daemon=True)
                self.presence_thread.start()

    def watch_presence(self):
        while not self.presence_stop.wait(1):
            with self.presence_lock:
                now = time.monotonic()
                self.presence_tabs = {tab: seen for tab, seen in self.presence_tabs.items()
                                      if now - seen < self.presence_lease}
                if self.presence_tabs:
                    self.presence_empty_since = None
                elif self.presence_seen and self.presence_empty_since is None:
                    self.presence_empty_since = now
                should_close = (self.auto_close_enabled and self.presence_seen
                                and self.presence_empty_since is not None
                                and now - self.presence_empty_since >= self.presence_grace)
                if should_close:
                    self.auto_close_enabled = False
            if should_close:
                print("All local Panelbook tabs closed; stopping the server.", flush=True)
                self.shutdown()
                return

    def server_close(self):
        self.presence_stop.set()
        super().server_close()


class PanelbookHandler(BaseHTTPRequestHandler):
    server: PanelbookServer
    timeout = REQUEST_TIMEOUT

    def log_message(self, format, *args):
        print("%s - %s" % (self.address_string(), format % args), flush=True)

    def json_response(self, data, status=200, cookie=None):
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def request_json(self, limit=MAX_BODY):
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise ApiError(415, "Expected JSON.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > limit:
                raise ApiError(413, "Request is empty or too large.")
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "Invalid JSON.")
        if not isinstance(data, dict):
            raise ApiError(400, "Expected a JSON object.")
        return data

    def same_origin(self):
        origin = self.headers.get("Origin", "")
        try:
            parsed = urlsplit(origin)
            expected_scheme = "https" if self.server.secure_cookies else "http"
            return bool(origin) and parsed.netloc.lower() == self.headers.get("Host", "").lower() and parsed.scheme == expected_scheme
        except ValueError:
            return False

    def session(self, db):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie["panelbook_session"].value
        except (KeyError, ValueError):
            return None
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        user = db.execute("""SELECT s.token_hash,s.csrf,s.expires_at,u.id,u.username,u.is_admin,u.is_super_admin,u.is_local
                             FROM sessions s JOIN users u ON u.id=s.user_id
                             WHERE s.token_hash=? AND s.expires_at>?""", (digest, int(time.time()))).fetchone()
        if user is not None and user["is_local"] and not self.is_local_request():
            return None
        return user

    def is_local_request(self):
        if not self.server.local_mode:
            return False
        try:
            address = ipaddress.ip_address(self.client_address[0])
            host = urlsplit("http://" + self.headers.get("Host", "")).hostname
            return address.is_loopback and host in ("127.0.0.1", "localhost", "::1")
        except ValueError:
            return False

    def require_user(self, db, mutate=False):
        user = self.session(db)
        if user is None:
            raise ApiError(401, "Sign in to continue.")
        if mutate and not hmac.compare_digest(self.headers.get("X-Panelbook-CSRF", ""), user["csrf"]):
            raise ApiError(403, "Invalid request token. Reload the page and try again.")
        return user

    def require_role(self, db, home_id, user_id, allowed):
        membership = db.execute("SELECT role FROM memberships WHERE home_id=? AND user_id=?", (home_id, user_id)).fetchone()
        if membership is None or membership["role"] not in allowed:
            raise ApiError(403, "You do not have access to change this home.")
        return membership["role"]

    def session_cookie(self, token, clear=False):
        parts = ["panelbook_session=" + ("" if clear else token), "Path=/", "HttpOnly", "SameSite=Strict"]
        parts.append("Max-Age=0" if clear else "Max-Age=" + str(SESSION_AGE))
        if self.server.secure_cookies:
            parts.append("Secure")
        return "; ".join(parts)

    def create_session(self, db, user_id):
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        db.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
        db.execute("INSERT INTO sessions(token_hash,csrf,user_id,expires_at) VALUES(?,?,?,?)",
                   (hashlib.sha256(token.encode()).hexdigest(), csrf, user_id, int(time.time()) + SESSION_AGE))
        return token

    def dispatch(self, method):
        try:
            if method != "GET" and not self.same_origin():
                raise ApiError(403, "Request origin is not allowed.")
            path = urlsplit(self.path).path
            if method == "GET":
                self.get_route(path)
            elif method == "POST":
                self.post_route(path)
            elif method == "PUT":
                self.put_route(path)
            elif method == "DELETE":
                self.delete_route(path)
        except ApiError as error:
            self.json_response({"error": str(error)}, error.status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            print("Request failed:", repr(error), flush=True)
            self.json_response({"error": "The server could not complete the request."}, 500)

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def get_route(self, path):
        if path in STATIC:
            filename, content_type = STATIC[path]
            body = (ROOT / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'")
            self.end_headers()
            self.wfile.write(body)
            return
        with database(self.server.db_path) as db:
            if path == "/api/update/check":
                user = self.require_user(db)
                if not self.server.local_mode or not user["is_admin"] or os.name != "nt" or not getattr(sys, "frozen", False) or not PROGRAM_LAYOUT:
                    raise ApiError(403, "Automatic updates require the Windows portable app and an administrator account.")
                try:
                    release = available_release()
                except Exception as error:
                    raise ApiError(503, "Could not check GitHub releases: %s" % error)
                self.json_response({"release": None if release is None else {"version": release["version"]}})
                return
            if path == "/api/status":
                user = self.session(db)
                needs_setup = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
                cookie = None
                if user is None and self.is_local_request():
                    local_user = db.execute("SELECT id FROM users WHERE is_local=1").fetchone()
                    if local_user:
                        token = self.create_session(db, local_user["id"])
                        db.commit()
                        cookie = self.session_cookie(token)
                        user = db.execute("""SELECT s.token_hash,s.csrf,s.expires_at,u.id,u.username,u.is_admin,u.is_super_admin,u.is_local
                            FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?""",
                            (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
                self.json_response({"version": VERSION, "needsSetup": needs_setup, "localMode": self.server.local_mode,
                                    "canUseLocal": bool(needs_setup and self.is_local_request()),
                                    "autoClose": bool(user and user["is_local"] and self.server.auto_close_enabled),
                                    "canUpdate": bool(user and user["is_admin"] and self.server.local_mode and os.name == "nt" and getattr(sys, "frozen", False) and PROGRAM_LAYOUT),
                                    "user": None if user is None else {"id": user["id"], "username": user["username"], "isAdmin": bool(user["is_admin"]), "isSuperAdmin": bool(user["is_super_admin"]), "isLocal": bool(user["is_local"])},
                                    "csrf": None if user is None else user["csrf"]}, cookie=cookie)
                return
            user = self.require_user(db)
            if path == "/api/workspace":
                if not db.execute("SELECT 1 FROM memberships WHERE user_id=?", (user["id"],)).fetchone():
                    # A shared home can be deleted by its owner; give the account a fresh home.
                    create_home(db, user["id"])
                    db.commit()
                rows = db.execute("""SELECT h.id,h.name,h.content,h.revision,m.role FROM homes h
                                     JOIN memberships m ON m.home_id=h.id WHERE m.user_id=? ORDER BY h.id""", (user["id"],)).fetchall()
                homes = [{"id": row["id"], **json.loads(row["content"]), "revision": row["revision"], "role": row["role"]} for row in rows]
                self.json_response({"homes": homes})
                return
            if path == "/api/users":
                users = db.execute("SELECT id,username,is_admin,is_super_admin FROM users ORDER BY username COLLATE NOCASE").fetchall()
                self.json_response({"users": [{"id": row["id"], "username": row["username"], "isAdmin": bool(row["is_admin"]), "isSuperAdmin": bool(row["is_super_admin"])}
                                              for row in users]})
                return
            if path == "/api/setup-codes":
                if not user["is_admin"] or user["is_local"]:
                    raise ApiError(403, "Only an administrator can manage setup codes.")
                rows = db.execute("SELECT id,unlimited FROM setup_codes ORDER BY id DESC").fetchall()
                self.json_response({"codes": [{"id": row["id"], "unlimited": bool(row["unlimited"])} for row in rows]})
                return
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "homes" and parts[3] == "members":
                home_id = int(parts[2]) if parts[2].isdecimal() else 0
                self.require_role(db, home_id, user["id"], ("owner",))
                rows = db.execute("""SELECT u.id,u.username,m.role FROM memberships m JOIN users u ON u.id=m.user_id
                                     WHERE m.home_id=? ORDER BY u.username COLLATE NOCASE""", (home_id,)).fetchall()
                self.json_response({"members": [dict(row) for row in rows]})
                return
        raise ApiError(404, "Not found.")

    def post_route(self, path):
        public = path in PUBLIC_POSTS
        with database(self.server.db_path) as db:
            # Check the session before reading the body so only signed-in
            # users can send large requests.
            user = None if public else self.require_user(db, mutate=True)
            data = self.request_json(MAX_PUBLIC_BODY if public else MAX_BODY)
            if path == "/api/setup":
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                    raise ApiError(409, "Initial setup is complete.")
                if not hmac.compare_digest(str(data.get("setupToken", "")), self.server.setup_token):
                    raise ApiError(403, "Enter the setup code shown by the server.")
                username = self.valid_username(data.get("username"))
                cursor = db.execute("INSERT INTO users(username,password_hash,is_admin,is_super_admin) VALUES(?,?,1,1)",
                                    (username, password_hash(data.get("password"))))
                create_home(db, cursor.lastrowid)
                token = self.create_session(db, cursor.lastrowid)
                db.commit()
                self.server.setup_token = ""
                self.json_response({"ok": True}, 201, self.session_cookie(token))
                return
            if path == "/api/setup/local":
                if not self.is_local_request():
                    raise ApiError(403, "Local-only access is available only on this machine.")
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                    raise ApiError(409, "Initial setup is complete.")
                cursor = db.execute("INSERT INTO users(username,password_hash,is_admin,is_super_admin,is_local,auto_close) VALUES('Local','',1,1,1,1)")
                create_home(db, cursor.lastrowid)
                token = self.create_session(db, cursor.lastrowid)
                db.commit()
                self.server.setup_token = ""
                self.server.set_auto_close(True)
                self.json_response({"ok": True}, 201, self.session_cookie(token))
                return
            if path == "/api/login":
                username = str(data.get("username", ""))
                password = str(data.get("password", ""))
                key = (self.client_address[0], username.lower())
                with self.server.login_lock:
                    attempts = [at for at in self.server.login_failures.get(key, []) if at > time.time() - 600]
                    if len(attempts) >= 8:
                        raise ApiError(429, "Too many sign-in attempts. Try again later.")
                row = db.execute("SELECT id,password_hash FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
                valid = password_matches(password, row["password_hash"]) if row else False
                if not valid:
                    with self.server.login_lock:
                        self.server.login_failures[key] = attempts + [time.time()]
                    raise ApiError(401, "Invalid username or password.")
                with self.server.login_lock:
                    self.server.login_failures.pop(key, None)
                token = self.create_session(db, row["id"])
                db.commit()
                self.json_response({"ok": True}, cookie=self.session_cookie(token))
                return
            if path == "/api/register":
                code = data.get("setupCode")
                if not isinstance(code, str) or not 16 <= len(code) <= 256:
                    raise ApiError(403, "Invalid setup code.")
                username = self.valid_username(data.get("username"))
                db.execute("BEGIN IMMEDIATE")
                code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
                code_row = db.execute("SELECT id,unlimited FROM setup_codes WHERE code_hash=?", (code_hash,)).fetchone()
                if code_row is None:
                    raise ApiError(403, "Invalid setup code.")
                new_hash = password_hash(data.get("password"))
                try:
                    cursor = db.execute("INSERT INTO users(username,password_hash) VALUES(?,?)", (username, new_hash))
                except sqlite3.IntegrityError:
                    raise ApiError(409, "That username is already in use.")
                create_home(db, cursor.lastrowid)
                if not code_row["unlimited"]:
                    db.execute("DELETE FROM setup_codes WHERE id=?", (code_row["id"],))
                token = self.create_session(db, cursor.lastrowid)
                db.commit()
                self.json_response({"ok": True}, 201, self.session_cookie(token))
                return
            if public:
                raise ApiError(404, "Not found.")
            if path == "/api/account/convert":
                if not user["is_local"] or not self.is_local_request():
                    raise ApiError(403, "Only a local-only workspace can be converted here.")
                username = self.valid_username(data.get("username"))
                new_hash = password_hash(data.get("password"))
                try:
                    db.execute("UPDATE users SET username=?,password_hash=?,is_local=0,auto_close=0 WHERE id=?",
                               (username, new_hash, user["id"]))
                except sqlite3.IntegrityError:
                    raise ApiError(409, "That username is already in use.")
                db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user["id"], user["token_hash"]))
                db.commit()
                self.server.set_auto_close(False)
                self.json_response({"ok": True})
                return
            if path == "/api/local/auto-close":
                if not user["is_local"] or not self.is_local_request():
                    raise ApiError(403, "Automatic close is only available in a local-only workspace.")
                enabled = data.get("enabled")
                if type(enabled) is not bool:
                    raise ApiError(400, "Choose whether to close Panelbook with its tabs.")
                db.execute("UPDATE users SET auto_close=? WHERE id=?", (int(enabled), user["id"]))
                db.commit()
                self.server.set_auto_close(enabled)
                self.json_response({"autoClose": enabled})
                return
            if path == "/api/local/presence":
                if not user["is_local"] or not self.is_local_request():
                    raise ApiError(403, "Tab presence is only available in a local-only workspace.")
                tab_id, active = data.get("tabId"), data.get("active")
                if not isinstance(tab_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{16,64}", tab_id) or type(active) is not bool:
                    raise ApiError(400, "Invalid tab presence.")
                self.server.record_presence(tab_id, active)
                self.json_response({"autoClose": self.server.auto_close_enabled})
                return
            if path == "/api/account/password":
                if user["is_local"]:
                    raise ApiError(409, "Create a login before changing the password.")
                row = db.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
                if not password_matches(data.get("currentPassword"), row["password_hash"]):
                    raise ApiError(403, "Current password is incorrect.")
                new_hash = password_hash(data.get("newPassword"))
                db.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, user["id"]))
                db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user["id"], user["token_hash"]))
                db.commit()
                self.json_response({"ok": True})
                return
            if path == "/api/logout":
                db.execute("DELETE FROM sessions WHERE token_hash=?", (user["token_hash"],))
                db.commit()
                self.json_response({"ok": True}, cookie=self.session_cookie("", clear=True))
                return
            if path == "/api/homes":
                name = data.get("name", "")
                if not isinstance(name, str) or not name.strip() or len(name) > 80:
                    raise ApiError(400, "Enter a home name up to 80 characters.")
                home = create_home(db, user["id"], name.strip())
                db.commit()
                self.json_response({"home": home}, 201)
                return
            if path == "/api/users":
                if not user["is_admin"]:
                    raise ApiError(403, "Only an administrator can create users.")
                if user["is_local"]:
                    raise ApiError(409, "Create a login before adding users.")
                username = self.valid_username(data.get("username"))
                try:
                    cursor = db.execute("INSERT INTO users(username,password_hash) VALUES(?,?)", (username, password_hash(data.get("password"))))
                except sqlite3.IntegrityError:
                    raise ApiError(409, "That username is already in use.")
                create_home(db, cursor.lastrowid)
                db.commit()
                self.json_response({"user": {"id": cursor.lastrowid, "username": username}}, 201)
                return
            if path == "/api/setup-codes":
                if not user["is_admin"] or user["is_local"]:
                    raise ApiError(403, "Only an administrator can manage setup codes.")
                if type(data.get("unlimited")) is not bool:
                    raise ApiError(400, "Choose a one-time or unlimited-use code.")
                code = secrets.token_urlsafe(24)
                cursor = db.execute("INSERT INTO setup_codes(code_hash,unlimited,created_by) VALUES(?,?,?)",
                                    (hashlib.sha256(code.encode()).hexdigest(), int(data["unlimited"]), user["id"]))
                db.commit()
                self.json_response({"id": cursor.lastrowid, "code": code, "unlimited": data["unlimited"]}, 201)
                return
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "users"] and parts[3] == "admin":
                if not user["is_super_admin"]:
                    raise ApiError(403, "Only the super admin can assign administrators.")
                target = self.require_admin_target(db, user, parts[2])
                if type(data.get("isAdmin")) is not bool:
                    raise ApiError(400, "Choose whether this user is an administrator.")
                db.execute("UPDATE users SET is_admin=? WHERE id=?", (int(data["isAdmin"]), target["id"]))
                db.commit()
                self.json_response({"ok": True})
                return
            if len(parts) == 4 and parts[:2] == ["api", "users"] and parts[3] == "password":
                target = self.require_admin_target(db, user, parts[2])
                new_hash = password_hash(data.get("password"))
                db.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, target["id"]))
                db.execute("DELETE FROM sessions WHERE user_id=?", (target["id"],))
                db.commit()
                self.json_response({"ok": True})
                return
            if path == "/api/import":
                imported = self.import_legacy(db, user["id"], data)
                db.commit()
                self.json_response({"homes": imported}, 201)
                return
            if path == "/api/update/install":
                if not self.server.local_mode or not user["is_admin"] or os.name != "nt" or not getattr(sys, "frozen", False) or not PROGRAM_LAYOUT:
                    raise ApiError(403, "Automatic updates require the Windows portable app and an administrator account.")
                if not (ROOT / "update-portable.ps1").is_file():
                    raise ApiError(500, "The update helper is missing from the app folder.")
                try:
                    release = available_release()
                except Exception as error:
                    raise ApiError(503, "Could not check GitHub releases: %s" % error)
                if release is None or release["version"] != data.get("version"):
                    raise ApiError(409, "The chosen update is no longer available. Check again.")
                command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(ROOT / "update-portable.ps1"), "-AppFolder", str(APP_ROOT),
                           "-ServerPid", str(os.getpid()), "-DownloadUrl", release["url"],
                           "-ExpectedSha256", release["digest"], "-ExpectedVersion", release["version"],
                           "-HostName", self.server.server_address[0], "-Port", str(self.server.server_address[1]),
                           "-DataDir", str(self.server.db_path.parent)]
                if self.server.secure_cookies:
                    command.append("-SecureCookies")
                subprocess.Popen(command,
                                 creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"})
                db.commit()
                self.json_response({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
        raise ApiError(404, "Not found.")

    def put_route(self, path):
        parts = path.strip("/").split("/")
        with database(self.server.db_path) as db:
            user = self.require_user(db, mutate=True)
            data = self.request_json()
            if len(parts) == 3 and parts[:2] == ["api", "homes"]:
                home_id = int(parts[2]) if parts[2].isdecimal() else 0
                self.require_role(db, home_id, user["id"], ("owner", "editor"))
                clean = validate_home(data)
                revision = data.get("revision")
                if type(revision) is not int:
                    raise ApiError(400, "Missing home revision.")
                db.execute("BEGIN IMMEDIATE")
                result = db.execute("UPDATE homes SET name=?,content=?,revision=revision+1 WHERE id=? AND revision=?",
                                    (clean["name"], json.dumps(clean, separators=(",", ":")), home_id, revision))
                if result.rowcount != 1:
                    raise ApiError(409, "This home changed in another browser. Export your changes before reloading.")
                db.commit()
                self.json_response({"revision": revision + 1})
                return
            if len(parts) == 5 and parts[:2] == ["api", "homes"] and parts[3] == "members":
                home_id = int(parts[2]) if parts[2].isdecimal() else 0
                member_id = int(parts[4]) if parts[4].isdecimal() else 0
                self.require_role(db, home_id, user["id"], ("owner",))
                role = data.get("role")
                if role not in ("editor", "viewer"):
                    raise ApiError(400, "Choose editor or viewer access.")
                if not db.execute("SELECT 1 FROM users WHERE id=?", (member_id,)).fetchone():
                    raise ApiError(404, "User not found.")
                existing = db.execute("SELECT role FROM memberships WHERE home_id=? AND user_id=?", (home_id, member_id)).fetchone()
                if existing is not None and existing["role"] == "owner":
                    raise ApiError(400, "The owner cannot be changed.")
                db.execute("""INSERT INTO memberships(home_id,user_id,role) VALUES(?,?,?)
                              ON CONFLICT(home_id,user_id) DO UPDATE SET role=excluded.role""", (home_id, member_id, role))
                db.commit()
                self.json_response({"ok": True})
                return
        raise ApiError(404, "Not found.")

    def delete_route(self, path):
        parts = path.strip("/").split("/")
        with database(self.server.db_path) as db:
            user = self.require_user(db, mutate=True)
            if len(parts) == 3 and parts[:2] == ["api", "homes"]:
                home_id = int(parts[2]) if parts[2].isdecimal() else 0
                self.require_role(db, home_id, user["id"], ("owner",))
                self.require_other_home(db, user["id"], home_id)
                db.execute("DELETE FROM homes WHERE id=?", (home_id,))
                db.commit()
                self.json_response({"ok": True})
                return
            if len(parts) == 5 and parts[:2] == ["api", "homes"] and parts[3] == "members":
                home_id = int(parts[2]) if parts[2].isdecimal() else 0
                member_id = int(parts[4]) if parts[4].isdecimal() else 0
                if member_id == user["id"]:
                    # Any editor or viewer can leave a home shared with them.
                    self.require_role(db, home_id, user["id"], ("editor", "viewer"))
                    self.require_other_home(db, user["id"], home_id)
                else:
                    self.require_role(db, home_id, user["id"], ("owner",))
                    row = db.execute("SELECT role FROM memberships WHERE home_id=? AND user_id=?", (home_id, member_id)).fetchone()
                    if row is None or row["role"] == "owner":
                        raise ApiError(400, "The owner cannot be removed.")
                db.execute("DELETE FROM memberships WHERE home_id=? AND user_id=?", (home_id, member_id))
                db.commit()
                self.json_response({"ok": True})
                return
            if len(parts) == 3 and parts[:2] == ["api", "users"]:
                target = self.require_admin_target(db, user, parts[2])
                # Keep the deleted user's homes: the administrator becomes their owner.
                db.execute("""INSERT INTO memberships(home_id,user_id,role)
                              SELECT home_id,?,'owner' FROM memberships WHERE user_id=? AND role='owner'
                              ON CONFLICT(home_id,user_id) DO UPDATE SET role='owner'""", (user["id"], target["id"]))
                db.execute("DELETE FROM users WHERE id=?", (target["id"],))
                db.commit()
                self.json_response({"ok": True})
                return
            if len(parts) == 3 and parts[:2] == ["api", "setup-codes"]:
                if not user["is_admin"] or user["is_local"]:
                    raise ApiError(403, "Only an administrator can manage setup codes.")
                code_id = int(parts[2]) if parts[2].isdecimal() else 0
                if not db.execute("DELETE FROM setup_codes WHERE id=?", (code_id,)).rowcount:
                    raise ApiError(404, "Setup code not found.")
                db.commit()
                self.json_response({"ok": True})
                return
        raise ApiError(404, "Not found.")

    def require_admin_target(self, db, user, raw_id):
        if not user["is_admin"] or user["is_local"]:
            raise ApiError(403, "Only an administrator can manage users.")
        target_id = int(raw_id) if raw_id.isdecimal() else 0
        if target_id == user["id"]:
            raise ApiError(400, "Use Password to change your own login.")
        target = db.execute("SELECT id,is_admin,is_super_admin FROM users WHERE id=?", (target_id,)).fetchone()
        if target is None:
            raise ApiError(404, "User not found.")
        if target["is_super_admin"] or target["is_admin"] and not user["is_super_admin"]:
            raise ApiError(403, "Only the super admin can manage another administrator.")
        return target

    def require_other_home(self, db, user_id, home_id):
        if not db.execute("SELECT 1 FROM memberships WHERE user_id=? AND home_id<>?", (user_id, home_id)).fetchone():
            raise ApiError(409, "Add another home first; every account needs at least one.")

    @staticmethod
    def valid_username(value):
        if not isinstance(value, str) or not 3 <= len(value) <= 40 or not all(c.isalnum() or c in "._-" for c in value):
            raise ApiError(400, "Username must be 3 to 40 letters, numbers, dots, hyphens, or underscores.")
        return value

    def import_legacy(self, db, user_id, data):
        if data.get("version") != 4:
            raise ApiError(400, "Import requires a Panelbook version 4 JSON export.")
        scope = data.get("scope")
        if scope == "everything":
            workbook = data.get("workbook")
            if not isinstance(workbook, dict) or workbook.get("version") != 4:
                raise ApiError(400, "Invalid full export.")
            sources = workbook.get("homes")
        elif scope == "home":
            sources = [data.get("home")]
        else:
            raise ApiError(400, "Choose a home or everything export.")
        if not isinstance(sources, list) or not 1 <= len(sources) <= 100:
            raise ApiError(400, "Invalid exported homes.")
        imported = []
        db.execute("BEGIN IMMEDIATE")
        for source in sources:
            if not isinstance(source, dict):
                raise ApiError(400, "Invalid exported home.")
            panels = source.get("panels")
            if not isinstance(panels, list) or not panels:
                raise ApiError(400, "Invalid exported panels.")
            if any(not isinstance(panel, dict) or not valid_id(panel.get("id")) for panel in panels):
                raise ApiError(400, "Invalid panel ID in export.")
            id_map = {panel["id"]: secrets.randbelow(2**45) + 1 for panel in panels}
            if len(id_map) != len(panels):
                raise ApiError(400, "Duplicate panel IDs in export.")
            mapped = []
            for panel in panels:
                copy = dict(panel)
                copy["id"] = id_map[panel["id"]]
                copy["parentPanelId"] = None if panel.get("parentPanelId") is None else id_map.get(panel["parentPanelId"])
                mapped.append(copy)
            clean = validate_home({"name": source.get("name"), "panels": mapped})
            imported.append(create_home(db, user_id, clean["name"], clean["panels"]))
        return imported


def reset_password(db_path, username):
    """Set a new password from the console, for example when the only administrator is locked out."""
    with database(db_path) as db:
        user = db.execute("SELECT id,is_local FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
        if user is None:
            raise SystemExit("No user named %r exists." % username)
        if user["is_local"]:
            raise SystemExit("A local-only workspace has no password. Open it on this machine and choose Create login.")
    if sys.stdin.isatty():
        password = getpass.getpass("New password for %s: " % username)
        if getpass.getpass("Repeat the new password: ") != password:
            raise SystemExit("The passwords do not match.")
    else:
        password = sys.stdin.readline().rstrip("\r\n")
    try:
        new_hash = password_hash(password)
    except ApiError as error:
        raise SystemExit(str(error))
    with database(db_path) as db:
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, user["id"]))
        db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    print("Password changed for %s. Existing sign-ins for this user were ended." % username)


def main():
    parser = argparse.ArgumentParser(description="Panelbook local or hosted server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--secure-cookies", action="store_true", help="Use when served through HTTPS")
    parser.add_argument("--reset-password", metavar="USERNAME",
                        help="Set a new password for USERNAME, then exit without starting the server")
    args = parser.parse_args()
    public_scheme = os.environ.get("PANELBOOK_PUBLIC_SCHEME", "http").lower()
    if public_scheme not in ("http", "https"):
        parser.error("PANELBOOK_PUBLIC_SCHEME must be http or https")
    db_path = (args.data_dir or APP_ROOT / "data") / "panelbook.sqlite3"
    try:
        initialize_database(db_path)
    except (OSError, sqlite3.OperationalError) as error:
        user = " (uid %d)" % os.getuid() if hasattr(os, "getuid") else ""
        raise SystemExit("Could not open %s: %s. Its folder must be writable by the user running Panelbook%s."
                         % (db_path, error, user))
    if args.reset_password is not None:
        reset_password(db_path, args.reset_password)
        return
    local_mode = args.host in ("127.0.0.1", "localhost", "::1")
    server = PanelbookServer((args.host, args.port), db_path, args.secure_cookies or public_scheme == "https", local_mode)
    url = "http://127.0.0.1:%d/" % args.port
    print("Panelbook %s running at %s" % (VERSION, url), flush=True)
    with database(db_path) as db:
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            print("First account setup code: %s" % server.setup_token, flush=True)
            if local_mode and not args.no_browser:
                url += "#setup=" + server.setup_token
    if local_mode and not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
