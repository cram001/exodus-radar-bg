#!/usr/bin/env python3
# Exodus Radar - Copyright 2026 Sailing Exodus (https://sailingexodus.net)
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Free to use on your own boat and for any non-commercial purpose. Want to use it in something you sell? Just ask: https://sailingexodus.net
"""
Radar web server: serves the browser version of the radar screen (web/radar.html) and the small API behind it.

Why it exists: a web page cannot write the anchor-watch file, and the page and the radar server (mayara, port 6502) are on
different ports. This serves the page and is the one narrow door for the radar controls and the anchor watch.

Safety, because there is no login: it is for your boat network only. Never forward port 8480 (or mayara's 6502) to the internet.
It sends no "allow any website" (CORS) headers, and every change (PUT/POST) must carry an X-Radar-Web header that other
websites cannot send, so a web page you happen to visit cannot quietly change your radar or your anchor watch.

Deliberately limited, like boat-settings-api (which is kept to alarm and wifi settings and is NOT touched by this):

  GET  /radar                      -> list of radars (mayara)
  GET  /radar/<id>/capabilities    -> what the radar supports (incl. the colour legend)
  GET  /radar/<id>/controls        -> current values
  GET  /radar/<id>/controls/<name> -> one value
  PUT  /radar/<id>/controls/<name> -> {"value":..,"auto":..,"enabled":..}  one control change, forwarded as-is
  GET  /anchor                     -> {"cfg": .anchor-watch.json, "status": .anchor-watch-status.json}
  POST /anchor                     -> {"armed":bool} and/or {"radius_ft":n}, same rules as the screen app
  GET  /swell                      -> a fresh ~/.swell.json if one exists, else {}
  GET  /  and /radar.html and /radar-logo.png   -> the page itself (only those three files)
  GET  /health

Nothing takes a file path or a free-form URL. Only the paths above are forwarded, only to mayara.
Anyone on your boat network can use it, exactly as they can already use mayara's own page: there is no login.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("RADAR_WEB_PORT", "8480"))
MAYARA = os.environ.get("MAYARA_URL", "http://127.0.0.1:6502").rstrip("/") + "/signalk/v2/api/vessels/self/radars"
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
STATIC = {"/": ("radar.html", "text/html; charset=utf-8"), "/radar.html": ("radar.html", "text/html; charset=utf-8"),
          "/radar-logo.png": ("radar-logo.png", "image/png")}
AW_CFG = "/home/pi/.anchor-watch.json"
AW_STATUS = "/home/pi/.anchor-watch-status.json"
SWELL = "/home/pi/.swell.json"

_ID = r"[A-Za-z0-9_-]{1,40}"
_NAME = r"[A-Za-z0-9_]{1,40}"
GET_OK = re.compile(r"^(|/%s|/%s/capabilities|/%s/controls|/%s/controls/%s)$" % (_ID, _ID, _ID, _ID, _NAME))
PUT_OK = re.compile(r"^/%s/controls/%s$" % (_ID, _NAME))


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def anchor_write(body):
    """Same rules as aw_write() in radar-display.py, so the screen and the web page behave identically."""
    cur = read_json(AW_CFG)
    new = {"armed": bool(cur.get("armed", False)),
           "radius_ft": float(cur.get("radius_ft", 150)),
           "anchor": cur.get("anchor")}
    if "radius_ft" in body:
        new["radius_ft"] = max(25.0, min(2000.0, float(body["radius_ft"])))
    if "armed" in body:
        new["armed"] = bool(body["armed"])
        new["anchor"] = None              # switching on (or off) always re-takes the position
    tmp = AW_CFG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(new, f)
    os.replace(tmp, AW_CFG)


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200, raw=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send({"error": "not allowed"}, 403)               # no cross-origin use

    def _ours(self):
        """Only our own page sends this header; another website cannot add it without a permission we never grant."""
        return self.headers.get("X-Radar-Web") == "1"

    def _static(self, path):
        ent = STATIC.get(path)
        if not ent:
            return False
        try:
            with open(os.path.join(WEB, ent[0]), "rb") as f:
                body = f.read()
        except OSError:
            self._send({"error": "page file missing"}, 404)
            return True
        self.send_response(200)
        self.send_header("Content-Type", ent[1])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2048:
            raise ValueError("body too large")
        b = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(b, dict):
            raise ValueError("expected an object")
        return b

    def _mayara(self, method, rest, body=None):
        req = urllib.request.Request(MAYARA + rest, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=4) as r:
                self._send(None, r.status, raw=r.read())
        except urllib.error.HTTPError as e:
            self._send({"error": "radar server said %d" % e.code}, e.code)
        except Exception:
            self._send({"error": "no answer from the radar server (mayara)"}, 502)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if self._static(path):
            return
        if path == "/health":
            self._send({"ok": True, "t": time.time()})
        elif path == "/anchor":
            self._send({"cfg": read_json(AW_CFG), "status": read_json(AW_STATUS), "now": time.time()})
        elif path == "/swell":
            s = read_json(SWELL)
            ok = s and time.time() - float(s.get("t", 0)) < 600
            self._send(s if ok else {})
        elif path == "/radar" or path.startswith("/radar/"):
            rest = path[len("/radar"):]
            if GET_OK.match(rest):
                self._mayara("GET", rest)
            else:
                self._send({"error": "not allowed"}, 403)
        else:
            self._send({"error": "not found"}, 404)

    def do_PUT(self):
        path = self.path.split("?")[0].rstrip("/")
        if not self._ours():
            self._send({"error": "not allowed"}, 403)
            return
        if not path.startswith("/radar/") or not PUT_OK.match(path[len("/radar"):]):
            self._send({"error": "not allowed"}, 403)
            return
        try:
            body = self._body()
        except Exception as e:
            self._send({"error": str(e)}, 400)
            return
        self._mayara("PUT", path[len("/radar"):], body)

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        if not self._ours():
            self._send({"error": "not allowed"}, 403)
            return
        if path != "/anchor":
            self._send({"error": "not found"}, 404)
            return
        try:
            anchor_write(self._body())
        except Exception as e:
            self._send({"error": str(e)}, 400)
            return
        time.sleep(0.2)
        self._send({"cfg": read_json(AW_CFG), "status": read_json(AW_STATUS), "now": time.time()})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
