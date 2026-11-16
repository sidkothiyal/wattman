"""Read-side aggregations for reports and the suggestion engine."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass


@dataclass
class WindowAgg:
    n_samples: int
    avg_watts: float
    min_watts: float
    max_watts: float


@dataclass
class PidRow:
    pid: int
    comm: str
    avg_watts: float
    n: int


def now() -> float:
    return time.time()


def last_sample_ts(conn: sqlite3.Connection) -> float | None:
    row = conn.execute("SELECT MAX(ts) FROM power_samples").fetchone()
    return row[0] if row and row[0] is not None else None


def window_total(
    conn: sqlite3.Connection,
    source: str,
    since: float,
    until: float | None = None,
) -> WindowAgg:
    until = until if until is not None else now()
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(AVG(watts), 0), COALESCE(MIN(watts), 0), COALESCE(MAX(watts), 0) "
        "FROM power_samples WHERE source = ? AND ts BETWEEN ? AND ? AND pid IS NULL",
        (source, since, until),
    ).fetchone()
    return WindowAgg(n_samples=row[0], avg_watts=row[1], min_watts=row[2], max_watts=row[3])


def window_pid_top(
    conn: sqlite3.Connection,
    source: str,
    since: float,
    until: float | None = None,
    limit: int = 15,
) -> list[PidRow]:
    until = until if until is not None else now()
    rows = conn.execute(
        "SELECT pid, comm, AVG(watts) as w, COUNT(*) as n FROM power_samples "
        "WHERE source = ? AND ts BETWEEN ? AND ? AND pid IS NOT NULL "
        "GROUP BY pid, comm ORDER BY w DESC LIMIT ?",
        (source, since, until, limit),
    ).fetchall()
    return [PidRow(pid=r[0], comm=r[1] or "?", avg_watts=r[2], n=r[3]) for r in rows]


def standby_share(
    conn: sqlite3.Connection,
    source: str,
    since: float,
    until: float | None = None,
) -> float:
    """Returns fraction in [0, 1] of total source watts attributed to __standby__."""
    from wattman.attribution.cpu import STANDBY_PID

    until = until if until is not None else now()
    total_row = conn.execute(
        "SELECT COALESCE(SUM(watts), 0) FROM power_samples WHERE source = ? AND ts BETWEEN ? AND ? AND pid IS NULL",
        (source, since, until),
    ).fetchone()
    standby_row = conn.execute(
        "SELECT COALESCE(SUM(watts), 0) FROM power_samples WHERE source = ? AND ts BETWEEN ? AND ? AND pid = ?",
        (source, since, until, STANDBY_PID),
    ).fetchone()
    total = total_row[0] or 0.0
    if total <= 0:
        return 0.0
    return min(max((standby_row[0] or 0.0) / total, 0.0), 1.0)


def current_settings(conn: sqlite3.Connection) -> dict[str, str | None]:
    """Most recent value per knob from settings_snapshot."""
    rows = conn.execute(
        "SELECT knob, value FROM settings_snapshot WHERE ts = (SELECT MAX(ts) FROM settings_snapshot)"
    ).fetchall()
    return {knob: value for knob, value in rows}


def latest_two_snapshots(conn: sqlite3.Connection) -> tuple[dict[str, str | None], dict[str, str | None]]:
    rows = conn.execute("SELECT DISTINCT ts FROM settings_snapshot ORDER BY ts DESC LIMIT 2").fetchall()
    if not rows:
        return ({}, {})
    if len(rows) == 1:
        latest = _snapshot_at(conn, rows[0][0])
        return ({}, latest)
    return (_snapshot_at(conn, rows[1][0]), _snapshot_at(conn, rows[0][0]))


def _snapshot_at(conn: sqlite3.Connection, ts: float) -> dict[str, str | None]:
    rows = conn.execute(
        "SELECT knob, value FROM settings_snapshot WHERE ts = ?", (ts,)
    ).fetchall()
    return {knob: value for knob, value in rows}


def setting_changes(conn: sqlite3.Connection, limit: int = 50) -> list[tuple]:
    return conn.execute(
        "SELECT id, ts, knob, old_value, new_value, source FROM setting_change "
        "ORDER BY ts DESC LIMIT ?",
        (limit,),
    ).fetchall()


def pending_ab_changes(
    conn: sqlite3.Connection, after_delay_seconds: int, after_window_seconds: int
) -> list[tuple]:
    """Returns setting_change rows that are old enough to compute A/B AND don't
    already have an ab_result."""
    cutoff = now() - (after_delay_seconds + after_window_seconds)
    return conn.execute(
        "SELECT sc.id, sc.ts, sc.knob, sc.old_value, sc.new_value FROM setting_change sc "
        "LEFT JOIN ab_result ab ON sc.id = ab.setting_change_id "
        "WHERE ab.setting_change_id IS NULL AND sc.ts <= ? "
        "ORDER BY sc.ts ASC",
        (cutoff,),
    ).fetchall()


def average_package_watts_in(
    conn: sqlite3.Connection, since: float, until: float
) -> tuple[float, int]:
    row = conn.execute(
        "SELECT COALESCE(AVG(watts), 0), COUNT(*) FROM power_samples "
        "WHERE source = 'package' AND ts BETWEEN ? AND ? AND pid IS NULL",
        (since, until),
    ).fetchone()
    return float(row[0]), int(row[1])


def insert_ab_result(
    conn: sqlite3.Connection,
    setting_change_id: int,
    before_avg: float,
    after_avg: float,
    n_before: int,
    n_after: int,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO ab_result "
        "(setting_change_id, computed_at, before_window_watts, after_window_watts, delta_watts, n_before, n_after) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (setting_change_id, now(), before_avg, after_avg, after_avg - before_avg, n_before, n_after),
    )


def ab_results(conn: sqlite3.Connection, limit: int = 50) -> list[tuple]:
    return conn.execute(
        "SELECT sc.id, sc.ts, sc.knob, sc.old_value, sc.new_value, "
        "ab.before_window_watts, ab.after_window_watts, ab.delta_watts, ab.n_before, ab.n_after "
        "FROM setting_change sc JOIN ab_result ab ON sc.id = ab.setting_change_id "
        "ORDER BY sc.ts DESC LIMIT ?",
        (limit,),
    ).fetchall()
