"""Main daemon loop. Run in foreground (sudo) — users supervise with their
init system of choice (systemd unit example in README)."""

from __future__ import annotations

import logging
import os
import signal
import sqlite3
import time
from pathlib import Path

from wattman.attribution.cpu import COMM_KERNEL, COMM_OTHER, COMM_STANDBY, KERNEL_PID, OTHER_PID, STANDBY_PID
from wattman.config import WattmanConfig
from wattman.daemon import privileges
from wattman.daemon.sampler import Sampler, Tick
from wattman.discovery import change_watch, scan
from wattman.store import db
from wattman.suggest import rules

log = logging.getLogger("wattman.daemon")


class Daemon:
    def __init__(self, config: WattmanConfig) -> None:
        self.config = config
        self.sampler = Sampler(config)
        self.conn: sqlite3.Connection | None = None
        self._stop = False
        self._last_settings_scan = 0.0
        self._last_rule_eval = 0.0

    def _signal(self, signum, _frame) -> None:
        log.info("received signal %s, stopping", signum)
        self._stop = True

    def _write_pid(self) -> None:
        self.config.pid_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.pid_path.write_text(str(os.getpid()))

    def _clear_pid(self) -> None:
        try:
            self.config.pid_path.unlink()
        except FileNotFoundError:
            pass

    def _persist_tick(self, tick: Tick) -> None:
        assert self.conn is not None
        rows: list[tuple[float, int | None, str | None, str, float, float | None, bool, int | None]] = []
        if tick.cpu is not None:
            cpu = tick.cpu
            rows.append((tick.ts, None, None, "package", cpu.package_watts, None, False, None))
            if cpu.dram_watts > 0:
                rows.append((tick.ts, None, None, "dram", cpu.dram_watts, None, False, None))
            rows.append((tick.ts, STANDBY_PID, COMM_STANDBY, "package", cpu.standby_watts, None, False, None))
            if cpu.kernel_watts > 0:
                rows.append((tick.ts, KERNEL_PID, COMM_KERNEL, "cpu", cpu.kernel_watts, None, False, None))
            if cpu.other_watts > 0:
                rows.append((tick.ts, OTHER_PID, COMM_OTHER, "cpu", cpu.other_watts, None, False, None))
            for pid, watts in cpu.per_pid_watts.items():
                rows.append((tick.ts, pid, cpu.per_pid_comm.get(pid), "cpu", watts, None, False, None))
        for gpu in tick.gpu:
            rows.append((tick.ts, None, None, "gpu", gpu.total_watts, None, gpu.approximate, gpu.gpu_index))
            rows.append((tick.ts, STANDBY_PID, COMM_STANDBY, "gpu", gpu.standby_watts, None, gpu.approximate, gpu.gpu_index))
            for pid, watts in gpu.per_pid_watts.items():
                rows.append((tick.ts, pid, None, "gpu", watts, None, gpu.approximate, gpu.gpu_index))
        if rows:
            with db.transaction(self.conn):
                db.insert_power_samples(self.conn, rows)

    def _maybe_scan_settings(self, now: float) -> None:
        assert self.conn is not None
        interval = self.config.sampler.settings_scan_minutes * 60
        if now - self._last_settings_scan < interval:
            return
        items = scan.full_scan()
        with db.transaction(self.conn):
            change_watch.diff_and_persist(self.conn, items)
            db.insert_settings_snapshot(self.conn, ts=now, items=items)
        self._last_settings_scan = now

    def _maybe_evaluate_rules(self, now: float) -> None:
        assert self.conn is not None
        # Run rules every 5 minutes.
        if now - self._last_rule_eval < 300:
            return
        with db.transaction(self.conn):
            rules.evaluate_and_persist(self.conn, lookback_seconds=24 * 3600)
        self._last_rule_eval = now

    def run(self) -> int:
        report = privileges.check()
        if not report.ok:
            print(report.fix_message())
            return 2

        signal.signal(signal.SIGTERM, self._signal)
        signal.signal(signal.SIGINT, self._signal)

        self.conn = db.connect(self.config.db_path)
        self._write_pid()
        log.info("daemon started, pid=%s db=%s interval=%ss",
                 os.getpid(), self.config.db_path, self.config.sampler.interval_seconds)

        try:
            # Prime the differential samplers; first tick returns None.
            self.sampler.tick()
            self._maybe_scan_settings(time.time())

            next_tick = time.monotonic() + self.config.sampler.interval_seconds
            while not self._stop:
                sleep_for = next_tick - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                tick = self.sampler.tick()
                self._persist_tick(tick)
                now = time.time()
                self._maybe_scan_settings(now)
                self._maybe_evaluate_rules(now)
                next_tick += self.config.sampler.interval_seconds
                # Catch up if we fell behind.
                if next_tick < time.monotonic() - self.config.sampler.interval_seconds:
                    next_tick = time.monotonic() + self.config.sampler.interval_seconds
        finally:
            self.sampler.shutdown()
            if self.conn is not None:
                self.conn.close()
            self._clear_pid()
        return 0


def is_running(pid_path: Path) -> int | None:
    if not pid_path.exists():
        return None
    try:
        pid = int(pid_path.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return pid
    return pid
