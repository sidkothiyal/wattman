"""`wattman now`: rich table summarizing the latest sample window."""

from __future__ import annotations

import sqlite3
import time

from rich.console import Console
from rich.table import Table

from wattman.store import queries


def render(conn: sqlite3.Connection, console: Console | None = None, window_seconds: int = 5) -> None:
    console = console or Console()
    last = queries.last_sample_ts(conn)
    if last is None:
        console.print("[yellow]no samples yet — is the daemon running?[/yellow]")
        return
    until = last
    since = until - window_seconds

    table = Table(title=f"wattman: last {window_seconds}s ending {time.strftime('%H:%M:%S', time.localtime(until))}")
    table.add_column("source")
    table.add_column("avg W", justify="right")
    table.add_column("min", justify="right")
    table.add_column("max", justify="right")
    table.add_column("standby %", justify="right")
    for source in ("package", "gpu"):
        agg = queries.window_total(conn, source, since, until)
        standby = queries.standby_share(conn, source, since, until)
        if agg.n_samples == 0:
            continue
        table.add_row(source, f"{agg.avg_watts:.1f}", f"{agg.min_watts:.1f}",
                       f"{agg.max_watts:.1f}", f"{standby*100:.0f}")
    console.print(table)

    for source in ("cpu", "gpu"):
        top = queries.window_pid_top(conn, source, since, until, limit=8)
        if not top:
            continue
        t = Table(title=f"top {source} consumers")
        t.add_column("pid", justify="right")
        t.add_column("comm")
        t.add_column("avg W", justify="right")
        t.add_column("n", justify="right")
        for row in top:
            t.add_row(str(row.pid), row.comm, f"{row.avg_watts:.2f}", str(row.n))
        console.print(t)
