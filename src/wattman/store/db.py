"""SQLite store. WAL mode, schema versioned, with helpers for the daemon's
hot path (batched inserts) and the CLI's read path (window aggregates).
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
  version INTEGER PRIMARY KEY,
  applied_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS power_samples (
  ts REAL NOT NULL,
  pid INTEGER,            -- nullable for system-level rows; negative for synthetic buckets
  comm TEXT,
  source TEXT NOT NULL,   -- cpu | gpu | dram | package
  watts REAL NOT NULL,
  util REAL,
  approximate INTEGER NOT NULL DEFAULT 0,
  device INTEGER          -- gpu index, when applicable
);
CREATE INDEX IF NOT EXISTS idx_power_ts ON power_samples(ts);
CREATE INDEX IF NOT EXISTS idx_power_source_ts ON power_samples(source, ts);
CREATE INDEX IF NOT EXISTS idx_power_pid_ts ON power_samples(pid, ts);

CREATE TABLE IF NOT EXISTS settings_snapshot (
  ts REAL NOT NULL,
  knob TEXT NOT NULL,
  value TEXT,
  scope TEXT
);
CREATE INDEX IF NOT EXISTS idx_settings_ts ON settings_snapshot(ts);
CREATE INDEX IF NOT EXISTS idx_settings_knob_ts ON settings_snapshot(knob, ts);

CREATE TABLE IF NOT EXISTS setting_change (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  knob TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT,
  source TEXT
);
CREATE INDEX IF NOT EXISTS idx_setting_change_ts ON setting_change(ts);

CREATE TABLE IF NOT EXISTS suggestion (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  rule TEXT NOT NULL,
  severity TEXT NOT NULL,
  message TEXT NOT NULL,
  evidence_json TEXT,
  dismissed_at REAL
);

CREATE TABLE IF NOT EXISTS ab_result (
  setting_change_id INTEGER NOT NULL,
  computed_at REAL NOT NULL,
  before_window_watts REAL NOT NULL,
  after_window_watts REAL NOT NULL,
  delta_watts REAL NOT NULL,
  n_before INTEGER NOT NULL,
  n_after INTEGER NOT NULL,
  PRIMARY KEY (setting_change_id)
);

CREATE TABLE IF NOT EXISTS suggestion_dismissed (
  rule TEXT PRIMARY KEY,
  dismissed_at REAL NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.executescript(SCHEMA)
    cur = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_meta")
    (have,) = cur.fetchone()
    if have < SCHEMA_VERSION:
        conn.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, time.time()),
        )
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN")
    try:
        yield
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def insert_power_samples(
    conn: sqlite3.Connection,
    rows: Iterable[tuple[float, int | None, str | None, str, float, float | None, bool, int | None]],
) -> None:
    """rows: (ts, pid, comm, source, watts, util, approximate, device)."""
    conn.executemany(
        "INSERT INTO power_samples(ts, pid, comm, source, watts, util, approximate, device) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [
            (ts, pid, comm, source, watts, util, 1 if approximate else 0, device)
            for ts, pid, comm, source, watts, util, approximate, device in rows
        ],
    )


def insert_settings_snapshot(
    conn: sqlite3.Connection, ts: float, items: Iterable[tuple[str, str | None, str | None]]
) -> None:
    """items: (knob, value, scope)."""
    conn.executemany(
        "INSERT INTO settings_snapshot(ts, knob, value, scope) VALUES (?,?,?,?)",
        [(ts, knob, value, scope) for knob, value, scope in items],
    )


def insert_setting_change(
    conn: sqlite3.Connection,
    ts: float,
    knob: str,
    old_value: str | None,
    new_value: str | None,
    source: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO setting_change(ts, knob, old_value, new_value, source) VALUES (?,?,?,?,?)",
        (ts, knob, old_value, new_value, source),
    )
    return cur.lastrowid or 0


def insert_suggestion(
    conn: sqlite3.Connection,
    ts: float,
    rule: str,
    severity: str,
    message: str,
    evidence_json: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO suggestion(ts, rule, severity, message, evidence_json) VALUES (?,?,?,?,?)",
        (ts, rule, severity, message, evidence_json),
    )
    return cur.lastrowid or 0
