"""Typer CLI entry point. `wattman --help` for the full surface."""

from __future__ import annotations

import json
import logging
import os
import signal
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from wattman.config import WattmanConfig
from wattman.daemon import privileges, service
from wattman.discovery import change_watch, scan
from wattman.reports import snapshot, timeline, topk
from wattman.store import db, queries

app = typer.Typer(help="System power & utilization analyzer.", no_args_is_help=True)
console = Console()


def _load_config(db_path: Optional[Path] = None) -> WattmanConfig:
    cfg = WattmanConfig.load()
    if db_path is not None:
        cfg.db_path = db_path
    return cfg


@app.command()
def start(
    interval: float = typer.Option(1.0, help="Seconds between samples."),
    db_path: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
    log_level: str = typer.Option("INFO"),
) -> None:
    """Run the sampling daemon in the foreground (requires sudo)."""
    logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = _load_config(db_path=db_path)
    cfg.sampler.interval_seconds = interval
    raise typer.Exit(service.Daemon(cfg).run())


@app.command()
def stop(db_path: Optional[Path] = typer.Option(None, "--db")) -> None:
    """Signal the running daemon to exit cleanly."""
    cfg = _load_config(db_path=db_path)
    pid = service.is_running(cfg.pid_path)
    if pid is None:
        console.print("[yellow]daemon is not running[/yellow]")
        raise typer.Exit(1)
    try:
        os.kill(pid, signal.SIGTERM)
        console.print(f"sent SIGTERM to pid {pid}")
    except ProcessLookupError:
        console.print("[yellow]process already exited[/yellow]")
    except PermissionError:
        console.print("[red]permission denied — try sudo wattman stop[/red]")
        raise typer.Exit(2)


@app.command()
def status(db_path: Optional[Path] = typer.Option(None, "--db")) -> None:
    """Report whether the daemon is running and when it last wrote a sample."""
    cfg = _load_config(db_path=db_path)
    pid = service.is_running(cfg.pid_path)
    if pid is None:
        console.print("daemon: [red]not running[/red]")
    else:
        console.print(f"daemon: [green]running[/green] (pid {pid})")
    if cfg.db_path.exists():
        conn = db.connect(cfg.db_path)
        last = queries.last_sample_ts(conn)
        if last is None:
            console.print("samples: none yet")
        else:
            ago = max(0.0, time.time() - last)
            console.print(f"last sample: {ago:.1f}s ago")
        conn.close()
    else:
        console.print(f"db: not yet created ({cfg.db_path})")


@app.command()
def now(
    db_path: Optional[Path] = typer.Option(None, "--db"),
    window: int = typer.Option(5, "--window", help="Seconds of history to summarize."),
) -> None:
    """Show the most recent CPU/GPU/standby breakdown."""
    cfg = _load_config(db_path=db_path)
    conn = db.connect(cfg.db_path)
    snapshot.render(conn, console=console, window_seconds=window)
    conn.close()


@app.command()
def top(
    by: str = typer.Option("cpu", help="cpu | gpu | total"),
    n: int = typer.Option(15),
    window: int = typer.Option(5),
    db_path: Optional[Path] = typer.Option(None, "--db"),
) -> None:
    """Per-process power leaderboard."""
    cfg = _load_config(db_path=db_path)
    conn = db.connect(cfg.db_path)
    topk.render(conn, by=by, n=n, window_seconds=window, console=console)
    conn.close()


@app.command()
def report(
    since: str = typer.Option("1h", help="e.g. 30m, 24h, 7d"),
    fmt: str = typer.Option("text", "--format", help="text | json"),
    db_path: Optional[Path] = typer.Option(None, "--db"),
) -> None:
    """Window report with totals, standby share, and a sparkline."""
    cfg = _load_config(db_path=db_path)
    conn = db.connect(cfg.db_path)
    since_s = timeline.parse_since(since)
    if fmt == "json":
        now_t = time.time()
        start = now_t - since_s
        package = queries.window_total(conn, "package", start, now_t)
        gpu = queries.window_total(conn, "gpu", start, now_t)
        out = {
            "since_seconds": since_s,
            "package": {"avg_w": package.avg_watts, "n": package.n_samples,
                         "standby_share": queries.standby_share(conn, "package", start, now_t)},
            "gpu": {"avg_w": gpu.avg_watts, "n": gpu.n_samples,
                    "standby_share": queries.standby_share(conn, "gpu", start, now_t)},
            "top_cpu_pids": [{"pid": r.pid, "comm": r.comm, "avg_w": r.avg_watts}
                              for r in queries.window_pid_top(conn, "cpu", start, now_t, 10)],
        }
        console.print_json(data=out)
    else:
        timeline.render(conn, since_seconds=since_s, console=console)
    conn.close()


@app.command()
def settings(
    diff: bool = typer.Option(False, "--diff", help="Show only what changed vs. previous snapshot."),
    rescan: bool = typer.Option(False, "--rescan", help="Force a fresh scan before reporting."),
    db_path: Optional[Path] = typer.Option(None, "--db"),
) -> None:
    """List discovered power/perf settings, or diff against the last snapshot."""
    cfg = _load_config(db_path=db_path)
    conn = db.connect(cfg.db_path)
    if rescan:
        items = scan.full_scan()
        with db.transaction(conn):
            change_watch.diff_and_persist(conn, items)
            db.insert_settings_snapshot(conn, ts=time.time(), items=items)
    if diff:
        rows = change_watch.latest_diff(conn)
        if not rows:
            console.print("[green]no changes since previous snapshot[/green]")
        else:
            t = Table(title="settings diff (prev → current)")
            t.add_column("knob")
            t.add_column("old")
            t.add_column("new")
            for knob, old, new in rows:
                t.add_row(knob, old or "—", new or "—")
            console.print(t)
    else:
        snap = queries.current_settings(conn)
        if not snap:
            console.print("[yellow]no settings snapshot yet — start the daemon or pass --rescan[/yellow]")
        else:
            t = Table(title=f"current settings ({len(snap)} knobs)")
            t.add_column("knob")
            t.add_column("value")
            for knob in sorted(snap):
                t.add_row(knob, snap[knob] or "—")
            console.print(t)
    conn.close()


@app.command()
def suggest(
    include_dismissed: bool = typer.Option(False, "--include-dismissed"),
    lookback_hours: int = typer.Option(24, "--lookback-hours"),
    db_path: Optional[Path] = typer.Option(None, "--db"),
) -> None:
    """Active suggestions and the evidence behind them."""
    from wattman.suggest import rules as rules_mod

    cfg = _load_config(db_path=db_path)
    conn = db.connect(cfg.db_path)
    # Force a fresh evaluation so the CLI is interactive even between daemon ticks.
    with db.transaction(conn):
        rules_mod.evaluate_and_persist(conn, lookback_seconds=lookback_hours * 3600)

    query = (
        "SELECT s.id, s.ts, s.rule, s.severity, s.message, s.evidence_json "
        "FROM suggestion s "
        "WHERE s.id IN (SELECT MAX(id) FROM suggestion GROUP BY rule) "
    )
    if not include_dismissed:
        query += "AND s.rule NOT IN (SELECT rule FROM suggestion_dismissed) "
    query += "ORDER BY s.ts DESC"
    rows = conn.execute(query).fetchall()
    if not rows:
        console.print("[green]no active suggestions[/green]")
    for sid, ts, rule, severity, message, evidence in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        color = {"info": "cyan", "warn": "yellow", "strong": "red"}.get(severity, "white")
        console.print(f"[{color}]#{sid} [{severity}] {rule}[/{color}]  ({when})")
        console.print(f"  {message}")
        if evidence:
            try:
                console.print(f"  evidence: {json.dumps(json.loads(evidence), indent=None)}")
            except json.JSONDecodeError:
                pass
    conn.close()


@app.command()
def dismiss(rule: str, db_path: Optional[Path] = typer.Option(None, "--db")) -> None:
    """Stop showing suggestions for a given rule."""
    cfg = _load_config(db_path=db_path)
    conn = db.connect(cfg.db_path)
    conn.execute(
        "INSERT OR REPLACE INTO suggestion_dismissed(rule, dismissed_at) VALUES (?, ?)",
        (rule, time.time()),
    )
    conn.close()
    console.print(f"dismissed rule [bold]{rule}[/bold]")


@app.command()
def ab(db_path: Optional[Path] = typer.Option(None, "--db"), limit: int = 25) -> None:
    """Measured before/after deltas for every setting change."""
    cfg = _load_config(db_path=db_path)
    conn = db.connect(cfg.db_path)
    rows = queries.ab_results(conn, limit=limit)
    if not rows:
        console.print("[yellow]no measured changes yet[/yellow]")
        conn.close()
        return
    t = Table(title="setting changes with measured power delta")
    t.add_column("when")
    t.add_column("knob")
    t.add_column("old → new")
    t.add_column("Δ W", justify="right")
    t.add_column("n (b/a)")
    for _id, ts, knob, old, new, _bw, _aw, delta, nb, na in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        t.add_row(when, knob, f"{old} → {new}", f"{delta:+.2f}", f"{nb}/{na}")
    console.print(t)
    conn.close()


@app.command()
def check() -> None:
    """Pre-flight privilege check (no daemon required)."""
    report = privileges.check()
    if report.ok:
        console.print(f"[green]OK[/green]: RAPL readable at {report.rapl_probe_path}")
    else:
        console.print(report.fix_message())
        raise typer.Exit(2)


if __name__ == "__main__":
    app()
