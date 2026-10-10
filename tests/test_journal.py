import subprocess
import sys

from live.store import Store

PY = sys.executable


def run(db, *args):
    return subprocess.run([PY, "scripts/journal.py", "--db", str(db), *args], capture_output=True, text=True)


def test_add_without_alert_list_close_report(tmp_path):
    db = tmp_path / "j.sqlite"

    r = run(db, "add", "MRVL", "long", "269.50", "267.70", "274.00", "--note", "manual")
    assert r.returncode == 0, r.stderr
    assert "#1" in r.stdout and "no matching alert" in r.stdout

    r = run(db, "list")
    assert r.returncode == 0 and "MRVL" in r.stdout and "open" in r.stdout

    r = run(db, "close", "1", "271.30", "--note", "T1 hit")
    assert r.returncode == 0 and "+1.00R" in r.stdout   # (271.30-269.50)/(269.50-267.70) = 1.00

    r = run(db, "report")
    assert r.returncode == 0
    assert "All trades" in r.stdout and "By score band" in r.stdout and "By alert stage" in r.stdout
    assert "By stock" in r.stdout and "Alerts taken vs. auto-outcomes" in r.stdout


def test_add_links_to_latest_at_zone_alert(tmp_path):
    db = tmp_path / "j.sqlite"
    store = Store(db)
    alert_id = store.alert("MRVL", "zone_at_zone", "🟡 MRVL at S1 269.00-271.00", True, score=84.0)

    r = run(db, "add", "MRVL", "long", "269.50", "267.70", "274.00")
    assert r.returncode == 0
    assert f"linked to alert #{alert_id}" in r.stdout

    rows = store.journal_rows_with_alerts()
    assert rows[0]["alert_id"] == alert_id
    assert rows[0]["alert_score"] == 84.0
    assert rows[0]["alert_kind"] == "zone_at_zone"


def test_explicit_alert_id_overrides_latest_match(tmp_path):
    db = tmp_path / "j.sqlite"
    store = Store(db)
    store.alert("MRVL", "zone_at_zone", "first", True, score=40.0)
    second = store.alert("MRVL", "zone_at_zone", "second", True, score=90.0)

    r = run(db, "add", "MRVL", "long", "100", "99", "103", "--alert", "1")
    assert r.returncode == 0 and "linked to alert #1" in r.stdout
    rows = store.journal_rows_with_alerts()
    assert rows[0]["alert_id"] == 1 and rows[0]["alert_score"] == 40.0
    assert second == 2   # sanity: the "latest" would have been #2 had we not pinned #1
