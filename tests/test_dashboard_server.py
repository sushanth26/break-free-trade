import json
import threading
import time
import urllib.error
import urllib.request

import pytest

import config
from http.server import HTTPServer
from live.dashboard_server import make_handler
from live.store import Store


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WATCHLIST_PATH", str(tmp_path / "w.json"))
    store = Store(tmp_path / "a.sqlite")
    httpd = HTTPServer(("127.0.0.1", 0), make_handler(store))
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)
    yield f"http://127.0.0.1:{port}", store
    httpd.shutdown()
    t.join(timeout=2)


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _post(url, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_static_index_served(server):
    base, _ = server
    with urllib.request.urlopen(base + "/", timeout=5) as r:
        assert r.status == 200
        assert b"Zone Assistant" in r.read()


def test_alerts_and_summary_endpoints(server):
    base, store = server
    store.alert("MRVL", "zone_at_zone", "at S1", True, score=84.0)
    status, body = _get(base + "/api/alerts")
    assert status == 200 and len(body) == 1 and body[0]["symbol"] == "MRVL"
    status, body = _get(base + "/api/summary")
    assert status == 200 and body["alerts"] == 1


def test_watchlist_get_and_post(server):
    base, _ = server
    status, body = _get(base + "/api/watchlist")
    assert status == 200 and body == list(config.WATCHLIST)
    status, body = _post(base + "/api/watchlist", {"symbols": ["nvda", "amd"]})
    assert status == 200 and body == ["NVDA", "AMD"]
    status, body = _get(base + "/api/watchlist")
    assert body == ["NVDA", "AMD"]


def test_journal_add_and_close(server):
    base, _ = server
    status, added = _post(base + "/api/journal", {"symbol": "MRVL", "direction": "long", "entry": 100,
                                                  "stop": 99, "target": 103})
    assert status == 201 and "id" in added
    status, closed = _post(f"{base}/api/journal/{added['id']}/close", {"exit": 101.5})
    assert status == 200 and closed["r"] == pytest.approx(1.5)
    status, rows = _get(base + "/api/journal")
    assert status == 200 and len(rows) == 1 and rows[0]["status"] == "closed"


def test_bad_journal_payload_returns_400(server):
    base, _ = server
    status, body = _post(base + "/api/journal", {"symbol": "MRVL"})
    assert status == 400 and "error" in body


def test_unknown_path_is_404(server):
    base, _ = server
    status, body = _get(base + "/api/nope")
    assert status == 404
