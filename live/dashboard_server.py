"""Local HTTP server for the zone-assistant dashboard: a small JSON API over
live/store.py + the editable watchlist, plus the static React frontend.
Stdlib only (http.server) -- no new dependency for a page that only ever
needs to talk to localhost.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config
from live import dashboard_api as api
from live.store import Store

STATIC_DIR = Path(__file__).resolve().parent / "dashboard_static"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".json": "application/json"}


def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.0 on purpose: closes the connection after every response, no keep-alive
        # bookkeeping -- simplest, most robust choice for a small local single-threaded API
        # a browser polls every few seconds (keep-alive bought nothing here and could wedge
        # the single request-handling thread on a connection nobody closed).

        def log_message(self, fmt, *args):
            pass   # quiet; the terminal running run_assistant.py is the log

        def _send_json(self, obj, status: int = 200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error_json(self, message: str, status: int = 400):
            self._send_json({"error": message}, status)

        def _send_static(self, path: str):
            if path in ("", "/"):
                path = "/index.html"
            f = (STATIC_DIR / path.lstrip("/")).resolve()
            if STATIC_DIR not in f.parents or not f.is_file():
                return self._send_error_json("not found", 404)
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES.get(f.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")   # never let the browser mask a fix with a stale copy
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length)) if length else {}

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/api/alerts":
                    return self._send_json(api.get_alerts(store, q.get("since"), q.get("symbol"),
                                                          int(q.get("limit", 300))))
                if u.path == "/api/outcomes":
                    return self._send_json(api.get_outcomes(store))
                if u.path == "/api/journal":
                    return self._send_json(api.get_journal(store))
                if u.path == "/api/watchlist":
                    return self._send_json(api.get_watchlist())
                if u.path == "/api/summary":
                    return self._send_json(api.get_summary(store))
            except Exception as e:
                return self._send_error_json(f"{type(e).__name__}: {e}", 500)
            if u.path.startswith("/api/"):
                return self._send_error_json("not found", 404)
            self._send_static(u.path)

        def do_POST(self):
            u = urlparse(self.path)
            try:
                payload = self._body()
                if u.path == "/api/journal":
                    return self._send_json(api.add_journal(store, payload), 201)
                if u.path.startswith("/api/journal/") and u.path.endswith("/close"):
                    trade_id = int(u.path.split("/")[3])
                    return self._send_json(api.close_journal(store, trade_id, payload))
                if u.path == "/api/watchlist":
                    return self._send_json(api.set_watchlist(payload))
            except ValueError as e:
                return self._send_error_json(str(e), 400)
            except Exception as e:
                return self._send_error_json(f"{type(e).__name__}: {e}", 500)
            self._send_error_json("not found", 404)

    return Handler


def serve(port: int = 8787, db_path: str = config.DB_PATH):
    """Single-threaded on purpose: one local user, infrequent SQLite queries --
    simpler and safer than making the Store connection thread-safe."""
    store = Store(db_path)
    httpd = HTTPServer(("127.0.0.1", port), make_handler(store))
    print(f"zone assistant dashboard: http://127.0.0.1:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
