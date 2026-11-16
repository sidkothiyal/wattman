"""Rule registry. Each rule sees a `Window` and emits zero or more Suggestions."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Callable

from wattman.store import db, queries


@dataclass
class Suggestion:
    rule: str
    severity: str          # info | warn | strong
    message: str
    evidence: dict = field(default_factory=dict)


@dataclass
class Window:
    """Read-only view of recent samples + current settings, passed to rules."""

    conn: sqlite3.Connection
    now_ts: float
    lookback_seconds: int

    def settings(self) -> dict[str, str | None]:
        return queries.current_settings(self.conn)

    def avg_watts(self, source: str = "package") -> float:
        agg = queries.window_total(self.conn, source, self.now_ts - self.lookback_seconds, self.now_ts)
        return agg.avg_watts

    def standby_share(self, source: str = "package") -> float:
        return queries.standby_share(self.conn, source, self.now_ts - self.lookback_seconds, self.now_ts)

    def top_pids(self, source: str, limit: int = 10) -> list[queries.PidRow]:
        return queries.window_pid_top(
            self.conn, source, self.now_ts - self.lookback_seconds, self.now_ts, limit
        )

    def n_samples(self, source: str = "package") -> int:
        return queries.window_total(self.conn, source, self.now_ts - self.lookback_seconds, self.now_ts).n_samples


RuleFn = Callable[[Window], list[Suggestion]]
_REGISTRY: list[tuple[str, RuleFn]] = []


def register(name: str):
    def decorator(fn: RuleFn) -> RuleFn:
        _REGISTRY.append((name, fn))
        return fn
    return decorator


def all_rules() -> list[tuple[str, RuleFn]]:
    return list(_REGISTRY)


def evaluate_and_persist(conn: sqlite3.Connection, lookback_seconds: int = 24 * 3600) -> list[int]:
    """Runs every rule, persists any suggestions that aren't dismissed for
    that rule, and returns the new suggestion ids."""
    # import for side effect: registers concrete rules
    import wattman.suggest.rules_cpu  # noqa: F401
    import wattman.suggest.rules_gpu  # noqa: F401
    import wattman.suggest.rules_platform  # noqa: F401
    import wattman.suggest.ab as ab_mod
    ab_mod.process_pending(conn)

    dismissed = {
        row[0] for row in conn.execute("SELECT rule FROM suggestion_dismissed").fetchall()
    }
    window = Window(conn=conn, now_ts=time.time(), lookback_seconds=lookback_seconds)
    new_ids: list[int] = []
    for name, fn in all_rules():
        if name in dismissed:
            continue
        try:
            suggestions = fn(window)
        except Exception as e:
            suggestions = [Suggestion(rule=name, severity="info",
                                       message=f"Rule {name} failed: {e}")]
        for s in suggestions:
            new_ids.append(
                db.insert_suggestion(
                    conn,
                    ts=time.time(),
                    rule=s.rule,
                    severity=s.severity,
                    message=s.message,
                    evidence_json=json.dumps(s.evidence, default=str) if s.evidence else None,
                )
            )
    return new_ids
