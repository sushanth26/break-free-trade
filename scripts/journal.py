"""Trade journal, backed by logs/agent.sqlite.

  python scripts/journal.py add MRVL long 269.50 267.70 274.00
  python scripts/journal.py add MRVL long 269.50 267.70 274.00 --alert 42 --note "confirmed on 1h too"
  python scripts/journal.py close 7 271.30 --note "T1 hit, trailed the rest"
  python scripts/journal.py list
  python scripts/journal.py report --since 2026-10-01

``add`` links to the latest "at zone" or "reclaimed" alert for that symbol
if --alert is not given.
"""
import argparse

import _setup  # noqa: F401

import pandas as pd

import config
from live.store import Store

ACTIONABLE_KINDS = ("zone_at_zone", "zone_reclaimed")


def cmd_add(store, args):
    alert_id = args.alert
    note = ""
    if alert_id is None:
        a = store.latest_alert(args.symbol, kind=ACTIONABLE_KINDS)
        if a is None:
            note = "no matching alert found"
        else:
            alert_id = a["id"]
    tid = store.journal_add(args.symbol, args.direction, args.entry, args.stop, args.target, alert_id, args.note)
    linked = f"linked to alert #{alert_id}" if alert_id is not None else note
    print(f"#{tid} {args.symbol} {args.direction} entry {args.entry:.2f} stop {args.stop:.2f} "
          f"target {args.target:.2f} -- {linked}")


def cmd_close(store, args):
    rec = store.journal_close(args.id, args.exit, args.note)
    print(f"#{args.id} {rec['direction']} entry {rec['entry']:.2f} -> exit {args.exit:.2f} = {rec['r']:+.2f}R")


def cmd_list(store, args):
    rows = store.journal_rows()
    if not rows:
        print("no trades")
        return
    df = pd.DataFrame(rows)[["id", "time_opened", "symbol", "direction", "entry", "stop", "target",
                            "status", "exit_price", "r"]]
    print(df.to_string(index=False, float_format=lambda x: f"{x:.2f}"))


def _summarize(rows: list[dict]) -> dict:
    closed = [r for r in rows if r["r"] is not None]
    if not closed:
        return {"trades": 0, "win_rate": float("nan"), "profit_factor": float("nan"), "avg_r": float("nan"),
               "expectancy_r": float("nan")}
    rs = [r["r"] for r in closed]
    wins = [x for x in rs if x > 0]
    losses = [-x for x in rs if x <= 0]
    pf = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else float("inf")
    return {"trades": len(closed), "win_rate": len(wins) / len(closed), "profit_factor": pf,
           "avg_r": sum(rs) / len(rs), "expectancy_r": sum(rs) / len(rs)}


def _table(groups: dict[str, list[dict]], key_name: str) -> pd.DataFrame:
    return pd.DataFrame([{key_name: k, **_summarize(rs)} for k, rs in groups.items()])


def _band(score):
    if score is None:
        return "unlinked"
    return "80+" if score >= 80 else "50-79" if score >= 50 else "<50"


def cmd_report(store, args):
    rows = store.journal_rows_with_alerts()
    if args.since:
        rows = [r for r in rows if r["time_opened"] >= args.since]
    if not rows:
        print("no trades" + (f" since {args.since}" if args.since else ""))
        return

    print(f"All trades ({len(rows)} opened)")
    s = _summarize(rows)
    for k, v in s.items():
        print(f"  {k:<16} {v:.3f}" if isinstance(v, float) else f"  {k:<16} {v}")

    by_band: dict[str, list] = {}
    for r in rows:
        by_band.setdefault(_band(r["alert_score"]), []).append(r)
    print("\nBy score band")
    print(_table(by_band, "band").to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    by_stage: dict[str, list] = {}
    for r in rows:
        stage = {"zone_at_zone": "at zone", "zone_reclaimed": "reclaim"}.get(r["alert_kind"], "unlinked")
        by_stage.setdefault(stage, []).append(r)
    print("\nBy alert stage")
    print(_table(by_stage, "stage").to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    by_stock: dict[str, list] = {}
    for r in rows:
        by_stock.setdefault(r["symbol"], []).append(r)
    print("\nBy stock")
    print(_table(by_stock, "symbol").to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    print("\nAlerts taken vs. auto-outcomes")
    aa = store.actionable_alerts_with_outcomes()
    if not aa:
        print("  no actionable alerts yet")
        return
    taken = sum(1 for a in aa if a["taken"])
    held = sum(1 for a in aa if a["outcome"] == "held")
    broke = sum(1 for a in aa if a["outcome"] == "broke")
    pending = len(aa) - held - broke
    print(f"  {taken} / {len(aa)} actionable alerts taken ({taken / len(aa):.1%})")
    print(f"  all actionable alerts: {held} held, {broke} broke, {pending} unresolved/pending")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=config.DB_PATH, help="override the SQLite path (mainly for testing)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add")
    p.add_argument("symbol")
    p.add_argument("direction", choices=["long", "short"])
    p.add_argument("entry", type=float)
    p.add_argument("stop", type=float)
    p.add_argument("target", type=float)
    p.add_argument("--alert", type=int, default=None)
    p.add_argument("--note", default="")

    p = sub.add_parser("close")
    p.add_argument("id", type=int)
    p.add_argument("exit", type=float)
    p.add_argument("--note", default="")

    sub.add_parser("list")

    p = sub.add_parser("report")
    p.add_argument("--since", default=None)

    args = ap.parse_args()
    store = Store(args.db)
    {"add": cmd_add, "close": cmd_close, "list": cmd_list, "report": cmd_report}[args.cmd](store, args)


if __name__ == "__main__":
    main()
