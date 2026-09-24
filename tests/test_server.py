import http.cookiejar
import io
import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from program.server import PanelbookServer, available_release, initialize_database, version_tuple


class Client:
    def __init__(self, base):
        self.base = base
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.csrf = None

    def request(self, path, method="GET", body=None):
        headers = {}
        data = None
        if method != "GET":
            headers["Origin"] = self.base
            headers["Content-Type"] = "application/json"
            if self.csrf:
                headers["X-Panelbook-CSRF"] = self.csrf
            data = json.dumps(body or {}).encode()
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def status(self):
        code, result = self.request("/api/status")
        self.csrf = result.get("csrf")
        return code, result


class ServerTests(unittest.TestCase):
    def test_update_uses_single_portable_asset(self):
        releases = [
            {"tag_name": "v0.5.0.3", "assets": [{"name": "Panelbook-Server-v0.5.0.3.zip", "digest": "sha256:" + "a" * 64}]},
            {"tag_name": "v0.5.0.2", "assets": [{"name": "Panelbook-Portable-v0.5.0.2.zip", "digest": "sha256:" + "b" * 64,
                                                  "browser_download_url": "https://example.test/release.zip"}]},
        ]
        with patch("program.server.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(releases).encode())):
            release = available_release()
        self.assertEqual(release["version"], "v0.5.0.2")
        self.assertEqual(release["digest"], "b" * 64)
        self.assertLess(version_tuple("v0.5.0"), version_tuple("v0.5.0.1"))
        self.assertLess(version_tuple("v0.5.0.99"), version_tuple("v0.5.1"))

    @unittest.skipUnless(os.name == "nt", "Windows process flags are required")
    def test_update_endpoint_starts_hidden_helper(self):
        local = Client(self.base)
        local.status()
        code, _ = local.request("/api/setup/local", "POST", {})
        self.assertEqual(code, 201)
        local.status()
        release = {"version": "v0.5.0.2", "url": "https://example.test/release.zip", "digest": "a" * 64}
        with patch("program.server.available_release", return_value=release), \
             patch("program.server.subprocess.Popen") as popen, \
             patch("program.server.sys.frozen", True, create=True), \
             patch.object(self.server, "shutdown"):
            code, _ = local.request("/api/update/install", "POST", {"version": "v0.5.0.2"})
        self.assertEqual(code, 200)
        command = popen.call_args.args[0]
        self.assertEqual(command[:5], ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"])
        self.assertEqual(popen.call_args.kwargs["creationflags"],
                         subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertEqual(popen.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_secure_host_requires_https_origin(self):
        self.server.secure_cookies = True
        browser = Client(self.base)
        code, _ = browser.request("/api/setup", "POST", {
            "username": "owner", "password": "a long sample password", "setupToken": self.server.setup_token
        })
        self.assertEqual(code, 403)
        request = urllib.request.Request(self.base + "/api/setup", method="POST",
                                         data=json.dumps({"username": "owner", "password": "a long sample password",
                                                          "setupToken": self.server.setup_token}).encode(),
                                         headers={"Origin": self.base.replace("http:", "https:"),
                                                  "Content-Type": "application/json"})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 201)
            self.assertIn("Secure", response.headers["Set-Cookie"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "data" / "panelbook.sqlite3"
        initialize_database(self.db)
        self.server = PanelbookServer(("127.0.0.1", 0), self.db, local_mode=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def test_local_only_setup_reopen_and_convert(self):
        local = Client(self.base)
        _, initial = local.status()
        self.assertTrue(initial["canUseLocal"])
        request = urllib.request.Request(self.base + "/api/status", headers={"Host": "other.example"})
        with urllib.request.urlopen(request) as response:
            self.assertFalse(json.load(response)["canUseLocal"])
        code, _ = local.request("/api/setup/local", "POST", {})
        self.assertEqual(code, 201)
        _, local_status = local.status()
        self.assertTrue(local_status["user"]["isLocal"])
        self.assertTrue(local_status["user"]["isAdmin"])
        code, workspace = local.request("/api/workspace")
        self.assertEqual(code, 200)
        home = workspace["homes"][0]
        home["name"] = "Retained home"
        code, _ = local.request("/api/homes/%d" % home["id"], "PUT", home)
        self.assertEqual(code, 200)
        code, _ = local.request("/api/users", "POST", {"username": "guest", "password": "another long password"})
        self.assertEqual(code, 409)
        password_login = Client(self.base)
        code, _ = password_login.request("/api/login", "POST", {"username": "Local", "password": "any sample password"})
        self.assertEqual(code, 401)
        reopened = Client(self.base)
        _, reopened_status = reopened.status()
        self.assertTrue(reopened_status["user"]["isLocal"])
        code, _ = reopened.request("/api/workspace")
        self.assertEqual(code, 200)

        self.server.local_mode = False
        _, remote_status = reopened.status()
        self.assertIsNone(remote_status["user"])
        self.assertFalse(remote_status["canUseLocal"])
        code, _ = reopened.request("/api/workspace")
        self.assertEqual(code, 401)
        code, _ = local.request("/api/account/convert", "POST", {"username": "owner", "password": "a long sample password"})
        self.assertEqual(code, 401)
        self.server.local_mode = True

        local.status()
        code, _ = local.request("/api/account/convert", "POST", {"username": "owner", "password": "short"})
        self.assertEqual(code, 400)
        code, _ = local.request("/api/account/convert", "POST", {"username": "owner", "password": "a long sample password"})
        self.assertEqual(code, 200)
        _, converted = local.status()
        self.assertEqual(converted["user"]["username"], "owner")
        self.assertFalse(converted["user"]["isLocal"])
        _, stale = reopened.status()
        self.assertIsNone(stale["user"])
        code, _ = reopened.request("/api/login", "POST", {"username": "owner", "password": "a long sample password"})
        self.assertEqual(code, 200)
        reopened.status()
        code, converted_workspace = reopened.request("/api/workspace")
        self.assertEqual(code, 200)
        self.assertEqual(converted_workspace["homes"][0]["id"], home["id"])
        self.assertEqual(converted_workspace["homes"][0]["name"], "Retained home")
        code, _ = local.request("/api/users", "POST", {"username": "guest", "password": "another long password"})
        self.assertEqual(code, 201)

    def test_local_setup_requires_loopback_mode_and_existing_schema_migrates(self):
        self.server.local_mode = False
        remote = Client(self.base)
        _, status = remote.status()
        self.assertFalse(status["canUseLocal"])
        code, _ = remote.request("/api/setup/local", "POST", {})
        self.assertEqual(code, 403)
        old_db = Path(self.temp.name) / "old.sqlite3"
        with closing(sqlite3.connect(old_db)) as db:
            db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0)")
            db.execute("INSERT INTO users(username,password_hash,is_admin) VALUES('existing','hash',1)")
            db.commit()
        initialize_database(old_db)
        with closing(sqlite3.connect(old_db)) as db:
            self.assertEqual(db.execute("SELECT is_local FROM users WHERE username='existing'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT auto_close FROM users WHERE username='existing'").fetchone()[0], 0)

    def test_auto_close_waits_for_all_local_tabs_and_reload(self):
        local = Client(self.base)
        local.status()
        code, _ = local.request("/api/setup/local", "POST", {})
        self.assertEqual(code, 201)
        _, status = local.status()
        self.assertTrue(status["autoClose"])
        self.server.presence_grace = 2
        self.server.presence_lease = 5
        restarted = PanelbookServer(("127.0.0.1", 0), self.db, local_mode=True)
        self.assertTrue(restarted.auto_close_enabled)
        restarted.server_close()
        tab_a, tab_b, tab_c = "a" * 24, "b" * 24, "c" * 24
        for tab in (tab_a, tab_b):
            code, _ = local.request("/api/local/presence", "POST", {"tabId": tab, "active": True})
            self.assertEqual(code, 200)
        code, _ = local.request("/api/local/presence", "POST", {"tabId": tab_a, "active": False})
        self.assertEqual(code, 200)
        time.sleep(1.2)
        self.assertTrue(self.thread.is_alive())
        # A page reload closes the old tab before the replacement registers.
        code, _ = local.request("/api/local/presence", "POST", {"tabId": tab_b, "active": False})
        self.assertEqual(code, 200)
        time.sleep(1.5)
        self.assertTrue(self.thread.is_alive())
        code, _ = local.request("/api/local/presence", "POST", {"tabId": tab_c, "active": True})
        self.assertEqual(code, 200)
        time.sleep(2.2)
        self.assertTrue(self.thread.is_alive())
        code, _ = local.request("/api/local/presence", "POST", {"tabId": tab_c, "active": False})
        self.assertEqual(code, 200)
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())

    def test_existing_local_workspace_uses_new_default_once(self):
        old_db = Path(self.temp.name) / "local-050.sqlite3"
        initialize_database(old_db)
        with closing(sqlite3.connect(old_db)) as db:
            db.execute("INSERT INTO users(username,password_hash,is_admin,is_local,auto_close) VALUES('Local','',1,1,0)")
            db.execute("PRAGMA user_version=0")
            db.commit()
        initialize_database(old_db)
        with closing(sqlite3.connect(old_db)) as db:
            self.assertEqual(db.execute("SELECT auto_close FROM users WHERE is_local=1").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            db.execute("UPDATE users SET auto_close=0 WHERE is_local=1")
            db.commit()
        initialize_database(old_db)
        with closing(sqlite3.connect(old_db)) as db:
            self.assertEqual(db.execute("SELECT auto_close FROM users WHERE is_local=1").fetchone()[0], 0)

    def test_auto_close_can_be_disabled(self):
        local = Client(self.base)
        local.status()
        code, _ = local.request("/api/setup/local", "POST", {})
        self.assertEqual(code, 201)
        local.status()
        self.server.presence_grace = 0.5
        tab = "a" * 24
        self.assertTrue(local.status()[1]["autoClose"])
        local.request("/api/local/presence", "POST", {"tabId": tab, "active": True})
        code, result = local.request("/api/local/auto-close", "POST", {"enabled": False})
        self.assertEqual(code, 200)
        self.assertFalse(result["autoClose"])
        local.request("/api/local/presence", "POST", {"tabId": tab, "active": False})
        time.sleep(1.2)
        self.assertTrue(self.thread.is_alive())
        _, status = local.status()
        self.assertFalse(status["autoClose"])
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT auto_close FROM users WHERE is_local=1").fetchone()[0], 0)

    def test_auto_close_requires_local_identity(self):
        owner = Client(self.base)
        owner.status()
        code, _ = owner.request("/api/setup", "POST", {
            "username": "owner", "password": "a long sample password", "setupToken": self.server.setup_token
        })
        self.assertEqual(code, 201)
        owner.status()
        code, _ = owner.request("/api/local/auto-close", "POST", {"enabled": True})
        self.assertEqual(code, 403)
        code, _ = owner.request("/api/local/presence", "POST", {"tabId": "a" * 24, "active": True})
        self.assertEqual(code, 403)

    def test_setup_sharing_conflict_and_legacy_import(self):
        owner = Client(self.base)
        code, status = owner.status()
        self.assertEqual(code, 200)
        self.assertTrue(status["needsSetup"])
        code, _ = owner.request("/api/setup", "POST", {
            "username": "owner", "password": "a long sample password", "setupToken": self.server.setup_token
        })
        self.assertEqual(code, 201)
        _, status = owner.status()
        self.assertEqual(status["user"]["username"], "owner")
        code, workspace = owner.request("/api/workspace")
        self.assertEqual(code, 200)
        home = workspace["homes"][0]
        self.assertEqual(home["role"], "owner")
        home["name"] = "Shared house"
        code, saved = owner.request("/api/homes/%d" % home["id"], "PUT", home)
        self.assertEqual(code, 200)
        self.assertEqual(saved["revision"], 2)
        code, _ = owner.request("/api/homes/%d" % home["id"], "PUT", home)
        self.assertEqual(code, 409)

        code, created = owner.request("/api/users", "POST", {"username": "guest", "password": "another long password"})
        self.assertEqual(code, 201)
        guest_id = created["user"]["id"]
        code, _ = owner.request("/api/homes/%d/members/%d" % (home["id"], guest_id), "PUT", {"role": "viewer"})
        self.assertEqual(code, 200)
        guest = Client(self.base)
        code, _ = guest.request("/api/login", "POST", {"username": "guest", "password": "another long password"})
        self.assertEqual(code, 200)
        guest.status()
        code, guest_workspace = guest.request("/api/workspace")
        self.assertEqual(code, 200)
        shared = next(item for item in guest_workspace["homes"] if item["id"] == home["id"])
        self.assertEqual(shared["role"], "viewer")
        code, _ = guest.request("/api/homes/%d" % home["id"], "PUT", shared)
        self.assertEqual(code, 403)
        code, _ = owner.request("/api/homes/%d/members/%d" % (home["id"], guest_id), "PUT", {"role": "editor"})
        self.assertEqual(code, 200)
        shared["name"] = "Edited by guest"
        code, _ = guest.request("/api/homes/%d" % home["id"], "PUT", shared)
        self.assertEqual(code, 200)
        code, _ = guest.request("/api/homes/%d/members/%d" % (home["id"], guest_id), "PUT", {"role": "viewer"})
        self.assertEqual(code, 403)
        code, _ = owner.request("/api/homes/%d/members/%d" % (home["id"], guest_id), "DELETE", {})
        self.assertEqual(code, 200)
        code, guest_workspace = guest.request("/api/workspace")
        self.assertEqual(code, 200)
        self.assertNotIn(home["id"], [item["id"] for item in guest_workspace["homes"]])

        legacy = {"version": 4, "scope": "home", "home": {
            "id": 1, "name": "Imported 0.1.4 home", "panels": [{
                "id": 1, "name": "Main", "kind": "main", "parentPanelId": None,
                "parentCircuitId": None, "spaces": 24, "types": {}, "circuits": [],
                "nextCircuitId": 1, "points": [], "nextPointId": 1
            }]
        }}
        code, result = owner.request("/api/import", "POST", legacy)
        self.assertEqual(code, 201)
        self.assertEqual(result["homes"][0]["name"], "Imported 0.1.4 home")
        code, workspace = owner.request("/api/workspace")
        self.assertEqual(code, 200)
        self.assertEqual(len(workspace["homes"]), 2)
        self.assertEqual(workspace["homes"][0]["name"], "Edited by guest")
        code, result = owner.request("/api/import", "POST", {"version": 4, "scope": "everything", "workbook": {
            "version": 4, "homes": [legacy["home"]], "nextHomeId": 2, "nextPanelId": 2,
            "selectedHomeId": 1, "selectedPanelId": 1
        }})
        self.assertEqual(code, 201)
        self.assertEqual(len(result["homes"]), 1)
        code, _ = owner.request("/api/account/password", "POST", {
            "currentPassword": "a long sample password", "newPassword": "a newer sample password"
        })
        self.assertEqual(code, 200)
        old_login = Client(self.base)
        code, _ = old_login.request("/api/login", "POST", {"username": "owner", "password": "a long sample password"})
        self.assertEqual(code, 401)
        code, _ = old_login.request("/api/login", "POST", {"username": "owner", "password": "a newer sample password"})
        self.assertEqual(code, 200)
        code, _ = owner.request("/data/panelbook.sqlite3")
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
