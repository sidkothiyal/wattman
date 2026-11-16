"""`wattman top`: leaderboard of per-process power draw."""

from __future__ import annotations

import sqlite3

from rich.console import Console
from rich.table import Table

from wattman.store import queries


def render(
    conn: sqlite3.Connection,
    by: str = "cpu",
    n: int = 15,
    window_seconds: int = 5,
    console: Console | None = None,
) -> None:
    console = console or Console()
    last = queries.last_sample_ts(conn)
    if last is None:
        console.print("[yellow]no samples yet[/yellow]")
        return
    until = last
    since = until - window_seconds

    if by == "total":
        cpu = {r.pid: r for r in queries.window_pid_top(conn, "cpu", since, until, limit=n * 4)}
        gpu = {r.pid: r for r in queries.window_pid_top(conn, "gpu", since, until, limit=n * 4)}
        merged: dict[int, tuple[str, float, float]] = {}
        for pid, row in cpu.items():
            merged[pid] = (row.comm, row.avg_watts, 0.0)
        for pid, row in gpu.items():
            comm, c, _ = merged.get(pid, (row.comm, 0.0, 0.0))
            merged[pid] = (comm, c, row.avg_watts)
        ranked = sorted(merged.items(), key=lambda kv: kv[1][1] + kv[1][2], reverse=True)[:n]
        t = Table(title=f"top {n} processes by total W (cpu+gpu, last {window_seconds}s)")
        t.add_column("pid", justify="right")
        t.add_column("comm")
        t.add_column("cpu W", justify="right")
        t.add_column("gpu W", justify="right")
        t.add_column("total", justify="right")
        for pid, (comm, c, g) in ranked:
            t.add_row(str(pid), comm, f"{c:.2f}", f"{g:.2f}", f"{c + g:.2f}")
        console.print(t)
        return

    rows = queries.window_pid_top(conn, by, since, until, limit=n)
    t = Table(title=f"top {n} processes by {by} W (last {window_seconds}s)")
    t.add_column("pid", justify="right")
    t.add_column("comm")
    t.add_column("avg W", justify="right")
    t.add_column("n", justify="right")
    for row in rows:
        t.add_row(str(row.pid), row.comm, f"{row.avg_watts:.2f}", str(row.n))
    console.print(t)
