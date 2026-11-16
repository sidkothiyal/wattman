"""Per-process CPU tick accounting from /proc/<pid>/stat.

We track delta (utime + stime) per PID between samples; the attribution layer
turns those into watt shares against the RAPL package/core readings.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

PROC = Path("/proc")


@dataclass
class ProcSnapshot:
    timestamp: float
    total_cpu_ticks: int                            # /proc/stat total (user+nice+sys+...)
    proc_ticks: dict[int, int] = field(default_factory=dict)   # pid -> utime+stime
    proc_comm: dict[int, str] = field(default_factory=dict)    # pid -> comm
    proc_kernel: dict[int, bool] = field(default_factory=dict)  # pid -> is_kthread


@dataclass
class ProcSample:
    """Per-PID delta ticks over the interval ending at `timestamp`."""

    timestamp: float
    interval_seconds: float
    total_delta_ticks: int
    pid_delta: dict[int, int]           # pid -> tick delta
    pid_comm: dict[int, str]
    pid_kernel: dict[int, bool]


def _read_stat_total() -> int:
    """Sum the first /proc/stat cpu aggregate line."""
    with (PROC / "stat").open() as f:
        line = f.readline()
    # "cpu  user nice system idle iowait irq softirq steal guest guest_nice"
    parts = line.split()
    return sum(int(p) for p in parts[1:])


def _read_proc_stat(pid: int) -> tuple[int, str, bool] | None:
    """Returns (utime+stime ticks, comm, is_kthread) or None if unreadable."""
    try:
        with (PROC / str(pid) / "stat").open() as f:
            raw = f.read()
    except OSError:
        return None
    # comm is in parentheses and may contain spaces / closing parens.
    open_paren = raw.find("(")
    close_paren = raw.rfind(")")
    if open_paren == -1 or close_paren == -1:
        return None
    comm = raw[open_paren + 1 : close_paren]
    rest = raw[close_paren + 2 :].split()
    # After the closing paren, fields per proc(5): state(0) ppid(1) pgrp(2) ...
    # utime is field 14 (1-indexed in proc(5)), 0-indexed here field 14 - 3 = 11. Use indices.
    # Field offsets (0-based after splitting "rest"): 0=state, 1=ppid, 2=pgrp, 3=session,
    # 4=tty_nr, 5=tpgid, 6=flags, 7=minflt, 8=cminflt, 9=majflt, 10=cmajflt,
    # 11=utime, 12=stime
    try:
        utime = int(rest[11])
        stime = int(rest[12])
        flags = int(rest[6])
    except (IndexError, ValueError):
        return None
    is_kthread = bool(flags & 0x00200000)  # PF_KTHREAD
    return utime + stime, comm, is_kthread


def snapshot() -> ProcSnapshot:
    ts = time.monotonic()
    total = _read_stat_total()
    proc_ticks: dict[int, int] = {}
    proc_comm: dict[int, str] = {}
    proc_kernel: dict[int, bool] = {}
    for name in os.listdir(PROC):
        if not name.isdigit():
            continue
        pid = int(name)
        result = _read_proc_stat(pid)
        if result is None:
            continue
        ticks, comm, is_kthread = result
        proc_ticks[pid] = ticks
        proc_comm[pid] = comm
        proc_kernel[pid] = is_kthread
    return ProcSnapshot(
        timestamp=ts,
        total_cpu_ticks=total,
        proc_ticks=proc_ticks,
        proc_comm=proc_comm,
        proc_kernel=proc_kernel,
    )


def diff(prev: ProcSnapshot, curr: ProcSnapshot) -> ProcSample:
    dt = curr.timestamp - prev.timestamp
    pid_delta: dict[int, int] = {}
    for pid, ticks in curr.proc_ticks.items():
        prev_ticks = prev.proc_ticks.get(pid)
        if prev_ticks is None:
            continue  # newly seen process — skip first interval to avoid spike
        delta = ticks - prev_ticks
        if delta < 0:
            continue
        if delta > 0:
            pid_delta[pid] = delta
    total_delta = curr.total_cpu_ticks - prev.total_cpu_ticks
    return ProcSample(
        timestamp=curr.timestamp,
        interval_seconds=max(dt, 0.0),
        total_delta_ticks=max(total_delta, 0),
        pid_delta=pid_delta,
        pid_comm=curr.proc_comm,
        pid_kernel=curr.proc_kernel,
    )


class CpuProcSampler:
    def __init__(self) -> None:
        self._prev: ProcSnapshot | None = None

    def sample(self) -> ProcSample | None:
        curr = snapshot()
        if self._prev is None:
            self._prev = curr
            return None
        out = diff(self._prev, curr)
        self._prev = curr
        return out
