from __future__ import annotations

from wattman.discovery import change_watch
from wattman.store import db


def test_diff_against_pure() -> None:
    prev = {"a": "1", "b": "2", "c": "3"}
    curr = {"a": "1", "b": "X", "d": "4"}
    diff = change_watch.diff_against(prev, curr)
    diff_map = {k: (o, n) for k, o, n in diff}
    assert diff_map["b"] == ("2", "X")
    assert diff_map["c"] == ("3", None)
    assert diff_map["d"] == (None, "4")
    assert "a" not in diff_map


def test_diff_and_persist_emits_changes(tmp_db) -> None:
    import time
    initial = [("cpu.cpufreq.scaling_governor", "performance", "policy:policy0")]
    db.insert_settings_snapshot(tmp_db, ts=time.time() - 60, items=initial)
    new = [("cpu.cpufreq.scaling_governor", "schedutil", "policy:policy0")]
    ids = change_watch.diff_and_persist(tmp_db, new)
    assert len(ids) == 1
    row = tmp_db.execute("SELECT knob, old_value, new_value FROM setting_change").fetchone()
    assert row[0] == "cpu.cpufreq.scaling_governor@policy:policy0"
    assert row[1] == "performance"
    assert row[2] == "schedutil"
