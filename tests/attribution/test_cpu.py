from __future__ import annotations

from wattman.attribution import cpu as cpu_attr
from wattman.sources.cpu_procs import ProcSample
from wattman.sources.rapl import RaplSample


def _rapl(package_w: float, core_w: float = 0.0) -> RaplSample:
    watts = {"package-0": package_w}
    if core_w:
        watts["core"] = core_w
    return RaplSample(timestamp=1.0, interval_seconds=1.0, watts=watts)


def _proc(pid_ticks: dict[int, int], kernel: dict[int, bool] | None = None) -> ProcSample:
    return ProcSample(
        timestamp=1.0,
        interval_seconds=1.0,
        total_delta_ticks=sum(pid_ticks.values()),
        pid_delta=pid_ticks,
        pid_comm={pid: f"proc{pid}" for pid in pid_ticks},
        pid_kernel={pid: bool((kernel or {}).get(pid, False)) for pid in pid_ticks},
    )


def test_proportional_split() -> None:
    rapl = _rapl(package_w=100.0, core_w=80.0)
    proc = _proc({1: 75, 2: 25})
    out = cpu_attr.attribute(rapl, proc, min_share=0.0)
    assert abs(out.per_pid_watts[1] - 60.0) < 1e-6  # 75% of 80W
    assert abs(out.per_pid_watts[2] - 20.0) < 1e-6
    assert abs(out.standby_watts - 20.0) < 1e-6     # package - core


def test_kernel_bucket() -> None:
    rapl = _rapl(package_w=50.0, core_w=50.0)
    proc = _proc({1: 50, 99: 50}, kernel={99: True})
    out = cpu_attr.attribute(rapl, proc, min_share=0.0)
    assert 1 in out.per_pid_watts
    assert 99 not in out.per_pid_watts
    assert abs(out.kernel_watts - 25.0) < 1e-6
    assert out.standby_watts == 0.0


def test_min_share_bucket() -> None:
    rapl = _rapl(package_w=100.0, core_w=100.0)
    proc = _proc({1: 999, 2: 1})  # pid 2 has 0.1% share
    out = cpu_attr.attribute(rapl, proc, min_share=0.01)
    assert 2 not in out.per_pid_watts
    assert out.other_watts > 0


def test_no_active_falls_back_to_package_for_standby() -> None:
    rapl = _rapl(package_w=20.0)        # no core domain
    proc = _proc({1: 10})
    out = cpu_attr.attribute(rapl, proc, min_share=0.0)
    assert out.per_pid_watts[1] == 20.0
    assert out.standby_watts == 0.0
