"""Attribute CPU package watts to processes by CPU-tick share.

Approximation: we have core-domain watts from RAPL and per-process CPU ticks
from /proc. Process share = (proc_ticks / sum_proc_ticks). Watts not
attributable to running processes are placed in the synthetic __standby__
bucket (uncore, package idle, DRAM access not visible per-process).
"""

from __future__ import annotations

from dataclasses import dataclass

from wattman.sources.cpu_procs import ProcSample
from wattman.sources.rapl import RaplSample

STANDBY_PID = -1
KERNEL_PID = -2
OTHER_PID = -3
COMM_STANDBY = "__standby__"
COMM_KERNEL = "__kernel__"
COMM_OTHER = "__other__"


@dataclass
class CpuAttribution:
    timestamp: float
    package_watts: float
    core_watts: float
    dram_watts: float
    standby_watts: float          # package - sum of attributed process watts
    kernel_watts: float           # kthreads' share of core_watts
    other_watts: float            # bucketed small-share procs (below min_share)
    per_pid_watts: dict[int, float]
    per_pid_comm: dict[int, str]


def _pick(watts: dict[str, float], *names: str) -> float:
    for n in names:
        if n in watts:
            return watts[n]
    return 0.0


def attribute(
    rapl: RaplSample,
    proc: ProcSample,
    min_share: float = 0.001,
) -> CpuAttribution:
    # Find package domain (first key starting with "package").
    package_w = 0.0
    for name, w in rapl.watts.items():
        if name.startswith("package"):
            package_w = w
            break
    core_w = _pick(rapl.watts, "core")
    dram_w = _pick(rapl.watts, "dram")

    total_ticks = sum(proc.pid_delta.values())
    per_pid: dict[int, float] = {}
    kernel_w = 0.0
    other_w = 0.0

    # Active power = core_w if exposed, otherwise estimate as package_w (uncore
    # contribution will then flow into __standby__ via remainder).
    active_w = core_w if core_w > 0 else package_w

    if total_ticks > 0 and active_w > 0:
        for pid, ticks in proc.pid_delta.items():
            share = ticks / total_ticks
            watts = share * active_w
            if proc.pid_kernel.get(pid):
                kernel_w += watts
                continue
            if share < min_share:
                other_w += watts
                continue
            per_pid[pid] = watts

    attributed = sum(per_pid.values()) + kernel_w + other_w
    standby_w = max(package_w - attributed, 0.0)

    return CpuAttribution(
        timestamp=rapl.timestamp,
        package_watts=package_w,
        core_watts=core_w,
        dram_watts=dram_w,
        standby_watts=standby_w,
        kernel_watts=kernel_w,
        other_watts=other_w,
        per_pid_watts=per_pid,
        per_pid_comm={pid: proc.pid_comm.get(pid, "?") for pid in per_pid},
    )
