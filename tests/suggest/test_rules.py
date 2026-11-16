from __future__ import annotations

import time

from wattman.attribution.cpu import STANDBY_PID
from wattman.store import db
from wattman.suggest.rules import evaluate_and_persist


def _seed_idle_high_perf_governor(conn) -> None:
    ts = time.time()
    # Snapshot says governor=performance
    db.insert_settings_snapshot(conn, ts=ts, items=[
        ("cpu.cpufreq.scaling_governor", "performance", "policy:policy0"),
    ])
    # 120 package samples avg 30W, with 25W standby each → standby share ~83%
    rows = []
    for i in range(120):
        t = ts - 60 + i * 0.5
        rows.append((t, None, None, "package", 30.0, None, False, None))
        rows.append((t, STANDBY_PID, "__standby__", "package", 25.0, None, False, None))
    db.insert_power_samples(conn, rows)


def test_cpu_governor_overspec_fires(tmp_db) -> None:
    _seed_idle_high_perf_governor(tmp_db)
    evaluate_and_persist(tmp_db, lookback_seconds=3600)
    rows = tmp_db.execute(
        "SELECT rule, message FROM suggestion WHERE rule = 'cpu_governor_overspec'"
    ).fetchall()
    assert len(rows) >= 1
    assert "performance" in rows[0][1]


def test_evaluation_skips_dismissed(tmp_db) -> None:
    _seed_idle_high_perf_governor(tmp_db)
    tmp_db.execute(
        "INSERT INTO suggestion_dismissed(rule, dismissed_at) VALUES (?, ?)",
        ("cpu_governor_overspec", time.time()),
    )
    evaluate_and_persist(tmp_db, lookback_seconds=3600)
    rows = tmp_db.execute(
        "SELECT COUNT(*) FROM suggestion WHERE rule = 'cpu_governor_overspec'"
    ).fetchone()
    assert rows[0] == 0
