from __future__ import annotations

import time

from wattman.attribution.cpu import STANDBY_PID
from wattman.store import db, queries


def test_insert_and_window_total(tmp_db) -> None:
    now = time.time()
    rows = [
        (now - 1.0, None, None, "package", 50.0, None, False, None),
        (now - 0.5, None, None, "package", 60.0, None, False, None),
        (now, None, None, "package", 70.0, None, False, None),
    ]
    db.insert_power_samples(tmp_db, rows)
    agg = queries.window_total(tmp_db, "package", now - 2.0, now + 1.0)
    assert agg.n_samples == 3
    assert abs(agg.avg_watts - 60.0) < 1e-6
    assert agg.min_watts == 50.0
    assert agg.max_watts == 70.0


def test_standby_share(tmp_db) -> None:
    now = time.time()
    db.insert_power_samples(tmp_db, [
        (now, None, None, "package", 100.0, None, False, None),
        (now, STANDBY_PID, "__standby__", "package", 40.0, None, False, None),
    ])
    share = queries.standby_share(tmp_db, "package", now - 1.0, now + 1.0)
    assert abs(share - 0.4) < 1e-6


def test_setting_change_and_ab(tmp_db) -> None:
    ts = time.time() - 30 * 60  # 30 min ago
    cid = db.insert_setting_change(tmp_db, ts=ts, knob="cpu.cpufreq.scaling_governor",
                                     old_value="performance", new_value="schedutil")
    assert cid > 0
    # populate package samples around the change
    for t in (ts - 200, ts - 100, ts - 50):
        db.insert_power_samples(tmp_db, [(t, None, None, "package", 80.0, None, False, None)])
    for t in (ts + 16 * 60, ts + 17 * 60, ts + 18 * 60):
        db.insert_power_samples(tmp_db, [(t, None, None, "package", 60.0, None, False, None)])

    from wattman.config import ABConfig
    from wattman.suggest import ab
    written = ab.process_pending(tmp_db, ABConfig())
    assert written == 1
    rows = queries.ab_results(tmp_db)
    assert len(rows) == 1
    _id, _ts, _knob, _old, _new, before_w, after_w, delta, nb, na = rows[0]
    assert abs(before_w - 80.0) < 1e-6
    assert abs(after_w - 60.0) < 1e-6
    assert abs(delta + 20.0) < 1e-6
    assert nb == 3 and na == 3
