"""`wattman report --since 24h`: bucketed text-mode timeline with sparkline."""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass

from rich.console import Console
from rich.table import Table

from wattman.store import queries

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


@dataclass
class Bucket:
    label: str
    avg_watts: float


def parse_since(s: str) -> int:
    m = re.fullmatch(r"(\d+)([smhd])", s.strip())
    if not m:
        raise ValueError(f"invalid --since value: {s!r}. Use e.g. 30m, 24h, 7d.")
    n = int(m.group(1))
    unit = m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def _sparkline(values: list[float]) -> str:
    if not values:
        return ""
    lo = min(values)
    hi = max(values)
    span = hi - lo if hi > lo else 1.0
    return "".join(_SPARK_CHARS[int((v - lo) / span * (len(_SPARK_CHARS) - 1))] for v in values)


def render(
    conn: sqlite3.Connection,
    since_seconds: int,
    n_buckets: int = 24,
    source: str = "package",
    console: Console | None = None,
) -> None:
    console = console or Console()
    now = time.time()
    start = now - since_seconds
    bucket_w = since_seconds / n_buckets
    buckets: list[Bucket] = []
    for i in range(n_buckets):
        b_start = start + i * bucket_w
        b_end = b_start + bucket_w
        agg = queries.window_total(conn, source, b_start, b_end)
        buckets.append(Bucket(
            label=time.strftime("%H:%M", time.localtime(b_start)),
            avg_watts=agg.avg_watts,
        ))

    standby = queries.standby_share(conn, source, start, now)
    overall = queries.window_total(conn, source, start, now)

    console.print(
        f"[bold]{source}[/bold]: avg {overall.avg_watts:.1f} W over last {since_seconds//60} min "
        f"({overall.n_samples} samples)   standby share: {standby*100:.0f}%"
    )
    console.print(_sparkline([b.avg_watts for b in buckets]))

    top = queries.window_pid_top(conn, "cpu", start, now, limit=10)
    if top:
        t = Table(title="top cpu consumers over window")
        t.add_column("pid", justify="right")
        t.add_column("comm")
        t.add_column("avg W", justify="right")
        for row in top:
            t.add_row(str(row.pid), row.comm, f"{row.avg_watts:.2f}")
        console.print(t)
