"""A/B logging: pair every setting_change with before/after power windows."""

from __future__ import annotations

import sqlite3

from wattman.config import ABConfig
from wattman.store import queries


def process_pending(conn: sqlite3.Connection, config: ABConfig | None = None) -> int:
    """For each setting_change row that's old enough, compute and persist its
    ab_result. Returns the number of new ab_result rows."""
    cfg = config or ABConfig()
    rows = queries.pending_ab_changes(conn, cfg.after_delay_seconds, cfg.after_window_seconds)
    written = 0
    for change_id, ts, _knob, _old, _new in rows:
        before_start = ts - cfg.before_window_seconds
        before_end = ts
        after_start = ts + cfg.after_delay_seconds
        after_end = after_start + cfg.after_window_seconds
        before_avg, n_before = queries.average_package_watts_in(conn, before_start, before_end)
        after_avg, n_after = queries.average_package_watts_in(conn, after_start, after_end)
        if n_before == 0 or n_after == 0:
            continue
        queries.insert_ab_result(conn, change_id, before_avg, after_avg, n_before, n_after)
        written += 1
    return written
