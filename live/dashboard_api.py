"""JSON API functions for the dashboard, kept separate from the HTTP transport
(live.dashboard_server) so they're directly testable without a real socket.
"""
from __future__ import annotations

import config
from live.store import Store


def get_alerts(store: Store, since: str | None = None, symbol: str | None = None, limit: int = 300) -> list[dict]:
    q = "SELECT rowid, time, symbol, kind, text, sent, score FROM alerts WHERE 1=1"
    args: list = []
    if since:
        q += " AND time >= ?"
        args.append(since)
    if symbol:
        q += " AND symbol = ?"
        args.append(symbol)
    q += " ORDER BY rowid DESC LIMIT ?"
    args.append(limit)
    cols = ("id", "time", "symbol", "kind", "text", "sent", "score")
    return [dict(zip(cols, r)) for r in store.db.execute(q, args).fetchall()]


def get_outcomes(store: Store) -> list[dict]:
    cols = ("time", "alert_id", "symbol", "outcome", "max_move_atr", "reached_next")
    rows = store.db.execute("SELECT time, alert_id, symbol, outcome, max_move_atr, reached_next "
                            "FROM zone_outcomes ORDER BY rowid DESC").fetchall()
    return [dict(zip(cols, r)) for r in rows]


def get_journal(store: Store) -> list[dict]:
    return store.journal_rows_with_alerts()


def add_journal(store: Store, payload: dict) -> dict:
    required = ("symbol", "direction", "entry", "stop", "target")
    missing = [k for k in required if k not in payload]
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")
    alert_id = payload.get("alert_id")
    tid = store.journal_add(payload["symbol"].upper(), payload["direction"], float(payload["entry"]),
                            float(payload["stop"]), float(payload["target"]),
                            int(alert_id) if alert_id not in (None, "") else None, payload.get("note", ""))
    return {"id": tid}


def close_journal(store: Store, trade_id: int, payload: dict) -> dict:
    return store.journal_close(trade_id, float(payload["exit"]), payload.get("note", ""))


def get_watchlist() -> list[str]:
    return list(config.load_watchlist())


def set_watchlist(payload: dict) -> list[str]:
    symbols = payload.get("symbols")
    if not isinstance(symbols, list) or not all(isinstance(s, str) for s in symbols):
        raise ValueError("payload must be {'symbols': [str, ...]}")
    cleaned = [s.strip().upper() for s in symbols if s.strip()]
    config.save_watchlist(cleaned)
    return cleaned


def get_summary(store: Store) -> dict:
    """One-glance counts for the dashboard header."""
    alerts = store.rows("alerts")
    outcomes = store.rows("zone_outcomes")
    held = sum(1 for o in outcomes if o[3] == "held")
    broke = sum(1 for o in outcomes if o[3] == "broke")
    journal = store.journal_rows()
    open_trades = sum(1 for j in journal if j["status"] == "open")
    return {"alerts": len(alerts), "outcomes_held": held, "outcomes_broke": broke,
           "journal_trades": len(journal), "journal_open": open_trades, "watchlist": get_watchlist()}
