"""SQLite log of everything the live system does, for the after-close review."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (time TEXT, symbol TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS alerts (time TEXT, symbol TEXT, kind TEXT, text TEXT, sent INTEGER, score REAL);
CREATE TABLE IF NOT EXISTS ai_calls (time TEXT, role TEXT, prompt_version TEXT, model TEXT, system TEXT,
    input TEXT, output TEXT, status TEXT, latency_s REAL, cost_usd REAL, action TEXT);
CREATE TABLE IF NOT EXISTS trades (time TEXT, symbol TEXT, record TEXT);
CREATE TABLE IF NOT EXISTS zone_outcomes (time TEXT, alert_id INTEGER, symbol TEXT, outcome TEXT,
    max_move_atr REAL, reached_next INTEGER);
CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, time_opened TEXT, symbol TEXT,
    direction TEXT, entry REAL, stop REAL, target REAL, alert_id INTEGER, note TEXT, status TEXT,
    time_closed TEXT, exit_price REAL, exit_note TEXT, r REAL);
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

    def alert(self, symbol: str, kind: str, text: str, sent: bool, time=None, score: float | None = None) -> int:
        cur = self.db.execute("INSERT INTO alerts VALUES (?,?,?,?,?,?)",
                              (str(time or self._now()), symbol, kind, text, int(sent), score))
        self.db.commit()
        return cur.lastrowid

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

    # ------------------------------------------------------------------ zone assistant

    def zone_outcome(self, alert_id: int, symbol: str, outcome: str | None, max_move_atr: float,
                    reached_next: bool, time=None):
        self.db.execute("INSERT INTO zone_outcomes VALUES (?,?,?,?,?,?)",
                        (str(time or self._now()), alert_id, symbol, outcome, max_move_atr, int(reached_next)))
        self.db.commit()

    def latest_alert(self, symbol: str, kind: str | tuple[str, ...] | None = None) -> dict | None:
        q, args = "SELECT rowid, time, symbol, kind, text, score FROM alerts WHERE symbol = ?", [symbol]
        if isinstance(kind, str):
            q += " AND kind = ?"
            args.append(kind)
        elif kind:
            q += f" AND kind IN ({','.join('?' * len(kind))})"
            args += list(kind)
        q += " ORDER BY rowid DESC LIMIT 1"
        row = self.db.execute(q, args).fetchone()
        return dict(zip(("id", "time", "symbol", "kind", "text", "score"), row)) if row else None

    def alert_outcome(self, alert_id: int) -> dict | None:
        row = self.db.execute("SELECT outcome, max_move_atr, reached_next FROM zone_outcomes WHERE alert_id = ?",
                              (alert_id,)).fetchone()
        return dict(zip(("outcome", "max_move_atr", "reached_next"), row)) if row else None

    # ------------------------------------------------------------------ trade journal

    def journal_add(self, symbol: str, direction: str, entry: float, stop: float, target: float,
                    alert_id: int | None, note: str) -> int:
        cur = self.db.execute(
            "INSERT INTO journal (time_opened, symbol, direction, entry, stop, target, alert_id, note, status) "
            "VALUES (?,?,?,?,?,?,?,?, 'open')",
            (self._now(), symbol, direction, entry, stop, target, alert_id, note))
        self.db.commit()
        return cur.lastrowid

    def journal_close(self, trade_id: int, exit_price: float, note: str = "") -> dict:
        row = self.db.execute("SELECT direction, entry, stop FROM journal WHERE id = ?", (trade_id,)).fetchone()
        if row is None:
            raise ValueError(f"no journal entry with id {trade_id}")
        direction, entry, stop = row
        risk = abs(entry - stop)
        r = (exit_price - entry) / risk if direction == "long" else (entry - exit_price) / risk
        self.db.execute("UPDATE journal SET status='closed', time_closed=?, exit_price=?, exit_note=?, r=? "
                        "WHERE id = ?", (self._now(), exit_price, note, r, trade_id))
        self.db.commit()
        return {"id": trade_id, "direction": direction, "entry": entry, "stop": stop, "exit_price": exit_price, "r": r}

    def journal_rows(self) -> list[dict]:
        cols = [d[1] for d in self.db.execute("PRAGMA table_info(journal)").fetchall()]
        return [dict(zip(cols, row)) for row in self.db.execute("SELECT * FROM journal ORDER BY id").fetchall()]

    def actionable_alerts_with_outcomes(self) -> list[dict]:
        """Every "at zone" / "reclaimed" alert, whether a journal entry took it, and its
        auto-outcome (held/broke) if resolved -- for "alerts taken vs. their outcomes"."""
        q = """
        SELECT a.rowid, a.symbol, a.kind, a.score,
               (SELECT COUNT(*) FROM journal j WHERE j.alert_id = a.rowid) AS taken,
               o.outcome, o.max_move_atr, o.reached_next
        FROM alerts a LEFT JOIN zone_outcomes o ON o.alert_id = a.rowid
        WHERE a.kind IN ('zone_at_zone', 'zone_reclaimed')
        ORDER BY a.rowid
        """
        cols = ("id", "symbol", "kind", "score", "taken", "outcome", "max_move_atr", "reached_next")
        return [dict(zip(cols, row)) for row in self.db.execute(q).fetchall()]

    def journal_rows_with_alerts(self) -> list[dict]:
        """Journal rows plus their linked alert's kind/score (for the score-band /
        alert-stage breakdowns) -- alert_kind/alert_score are None if unlinked."""
        cols = [d[1] for d in self.db.execute("PRAGMA table_info(journal)").fetchall()]
        q = (f"SELECT {','.join('j.' + c for c in cols)}, a.kind, a.score FROM journal j "
            "LEFT JOIN alerts a ON a.rowid = j.alert_id ORDER BY j.id")
        out = []
        for row in self.db.execute(q).fetchall():
            d = dict(zip(cols, row[:len(cols)]))
            d["alert_kind"], d["alert_score"] = row[len(cols)], row[len(cols) + 1]
            out.append(d)
        return out
