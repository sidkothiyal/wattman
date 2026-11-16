"""Diff the latest two settings_snapshot rows and emit setting_change rows."""

from __future__ import annotations

import sqlite3
import time

from wattman.store import db, queries


def diff_and_persist(conn: sqlite3.Connection, current: list[tuple[str, str | None, str]]) -> list[int]:
    """Compares `current` (the snapshot just taken) against the most-recent
    persisted snapshot and writes one setting_change row per differing knob.
    Returns the new setting_change row ids.
    """
    prev_rows = conn.execute(
        "SELECT knob, value, scope FROM settings_snapshot WHERE ts = (SELECT MAX(ts) FROM settings_snapshot)"
    ).fetchall()
    prev: dict[tuple[str, str], str | None] = {(knob, scope): value for knob, value, scope in prev_rows}
    curr: dict[tuple[str, str], str | None] = {(knob, scope): value for knob, value, scope in current}

    if not prev:
        return []  # first ever snapshot; nothing to diff against

    new_ids: list[int] = []
    ts = time.time()
    keys = sorted(set(prev) | set(curr))
    for key in keys:
        old = prev.get(key)
        new = curr.get(key)
        if old == new:
            continue
        knob, scope = key
        scoped_knob = f"{knob}@{scope}" if scope else knob
        new_ids.append(
            db.insert_setting_change(conn, ts=ts, knob=scoped_knob, old_value=old, new_value=new, source="scan")
        )
    return new_ids


def diff_against(prev_map: dict[str, str | None], curr_map: dict[str, str | None]) -> list[tuple[str, str | None, str | None]]:
    """Pure-function diff used by `wattman settings --diff`."""
    out: list[tuple[str, str | None, str | None]] = []
    for knob in sorted(set(prev_map) | set(curr_map)):
        old = prev_map.get(knob)
        new = curr_map.get(knob)
        if old != new:
            out.append((knob, old, new))
    return out


def latest_diff(conn: sqlite3.Connection) -> list[tuple[str, str | None, str | None]]:
    prev_map, curr_map = queries.latest_two_snapshots(conn)
    return diff_against(prev_map, curr_map)
