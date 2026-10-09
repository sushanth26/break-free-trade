"""SQLite log of everything the live system does, for the after-close review."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (time TEXT, symbol TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS alerts (time TEXT, symbol TEXT, kind TEXT, text TEXT, sent INTEGER);
CREATE TABLE IF NOT EXISTS ai_calls (time TEXT, role TEXT, prompt_version TEXT, model TEXT, system TEXT,
    input TEXT, output TEXT, status TEXT, latency_s REAL, cost_usd REAL, action TEXT);
CREATE TABLE IF NOT EXISTS trades (time TEXT, symbol TEXT, record TEXT);
"""


class Store:
    def __init__(self, path: str | Path = config.DB_PATH):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)

    def _now(self):
        import pandas as pd
        return pd.Timestamp.now(tz=config.TZ).isoformat()

    def event(self, ev):
        self.db.execute("INSERT INTO events VALUES (?,?,?,?)",
                        (str(ev.time), ev.symbol, ev.kind, json.dumps(ev.detail, default=str)))
        self.db.commit()

    def alert(self, symbol: str, kind: str, text: str, sent: bool, time=None):
        self.db.execute("INSERT INTO alerts VALUES (?,?,?,?,?)", (str(time or self._now()), symbol, kind, text, int(sent)))
        self.db.commit()

    def ai_call(self, rec: dict):
        self.db.execute("INSERT INTO ai_calls VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (self._now(), rec["role"], rec["prompt_version"], rec["model"], rec["system"], rec["input"],
                         rec["output"], rec["status"], rec["latency_s"], rec["cost_usd"], rec["action"]))
        self.db.commit()

    def trade(self, symbol: str, record: dict):
        self.db.execute("INSERT INTO trades VALUES (?,?,?)", (self._now(), symbol, json.dumps(record, default=str)))
        self.db.commit()

    def rows(self, table: str) -> list[tuple]:
        return self.db.execute(f"SELECT * FROM {table}").fetchall()
