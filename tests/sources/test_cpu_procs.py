from __future__ import annotations

from wattman.sources import cpu_procs


def _snap(ts: float, total: int, ticks: dict[int, int], kernels: dict[int, bool] | None = None):
    return cpu_procs.ProcSnapshot(
        timestamp=ts,
        total_cpu_ticks=total,
        proc_ticks=ticks,
        proc_comm={pid: f"proc{pid}" for pid in ticks},
        proc_kernel={pid: bool((kernels or {}).get(pid, False)) for pid in ticks},
    )


def test_diff_basic() -> None:
    a = _snap(0.0, 1000, {100: 50, 200: 20})
    b = _snap(1.0, 1100, {100: 70, 200: 25, 300: 5})
    out = cpu_procs.diff(a, b)
    assert out.total_delta_ticks == 100
    # pid 300 is new — skipped this interval
    assert out.pid_delta == {100: 20, 200: 5}
    assert out.interval_seconds == 1.0


def test_diff_ignores_negative_and_zero() -> None:
    a = _snap(0.0, 1000, {100: 50})
    b = _snap(1.0, 1010, {100: 50})
    out = cpu_procs.diff(a, b)
    assert out.pid_delta == {}
