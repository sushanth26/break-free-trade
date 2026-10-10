"""Short alert texts with exact prices, in the plan's formats."""
from __future__ import annotations

from engine.trade import Action, TradePlan
from engine.zones import Zone


def _z(z: Zone) -> str:
    return f"{z.bottom:.2f}–{z.top:.2f}"


def watch(symbol: str, label: str, zone: Zone, score: float) -> str:
    return f"🟡 Watch · {symbol} at {label} {_z(zone)} ({score:.0f}) · watching"


def possible_bounce(symbol: str, label: str, aplus: int | None = None) -> str:
    a = f" · A+ {aplus}/7" if aplus is not None else ""
    return f"🟡 Possible bounce · {symbol} rejection at {label}{a} · waiting follow-through"


def entry(p: TradePlan, risk_dollars: float, note: str = "") -> str:
    side = "LONG" if p.direction == "long" else "SHORT"
    pm = " · premarket: limit only, mental stop" if p.premarket else ""
    n = f"\n🤖 {note}" if note else ""
    return (f"🟢 Entry · {p.symbol} {side} · entry {p.entry:.2f} · stop {p.stop:.2f} · T1 {p.t1:.2f} · "
            f"T2 {p.t2:.2f} · {p.shares} sh (${risk_dollars:.0f} risk) · {p.grade} {p.aplus}/7{pm}{n}")


def action(symbol: str, a: Action) -> str | None:
    if a.kind == "target1":
        return f"🟢 Target · {symbol} T1 hit · sell 1/3 · stop → {a.new_stop:.2f}"
    if a.kind == "target2":
        return f"🟢 Target · {symbol} T2 hit · sell 1/3 · stop → {a.new_stop:.2f}"
    if a.kind == "warning":
        return f"🟡 Warning · {symbol} {a.reason} · sell half · stop → {a.new_stop:.2f}"
    if a.kind == "stop":
        return f"🔴 Exit · {symbol} stop hit {a.price:.2f} · exit"
    if a.kind == "exit":
        return f"🔴 Exit · {symbol} {a.reason} · exit"
    if a.kind == "cancelled":
        return f"⚪ Cancel · {symbol} entry not filled ({a.reason})"
    return None


def replan(symbol: str, what: str, bias: str, consequence: str, note: str = "") -> str:
    n = f" · {note}" if note else ""
    return f"🔵 Re-plan · {symbol} {what} · bias → {bias} · {consequence}{n}"


def info(text: str) -> str:
    return f"ℹ️ {text}"


# ------------------------------------------------------------------ zone assistant

def zone_approaching(symbol: str, label: str, zone: Zone, score: float, hold: float) -> str:
    return f"🟡 {symbol} → {label} {_z(zone)} · score {score:.0f} · holds {hold:.0%}"


def zone_at(symbol: str, label: str, zone: Zone) -> str:
    return f"🟡 {symbol} at {label} {_z(zone)}"


def zone_reclaimed(symbol: str, label: str, close: float, wick: float, direction: str = "long") -> str:
    wick_label = "wick low" if direction == "long" else "wick high"
    return f"🟢 {symbol} reclaimed {label} · close {close:.2f} · {wick_label} {wick:.2f}"


def zone_broken(symbol: str, label: str, close: float) -> str:
    return f"🔴 {symbol} broke {label} · close {close:.2f}"
