import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from server import PanelbookServer, initialize_database


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
        self.assertEqual(workspace["homes"][0]["name"], "Shared house")
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
