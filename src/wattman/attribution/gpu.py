"""Attribute GPU watts to processes by SM-util share."""

from __future__ import annotations

from dataclasses import dataclass

from wattman.sources.nvidia import GpuSample


@dataclass
class GpuAttribution:
    timestamp: float
    gpu_index: int
    gpu_name: str
    total_watts: float
    standby_watts: float
    per_pid_watts: dict[int, float]
    approximate: bool      # True when we used fallback split (per-proc API empty)


def attribute(sample: GpuSample, unknown_split: str = "equal") -> GpuAttribution:
    total = sample.power_watts
    per_pid: dict[int, float] = {}
    approximate = False

    sum_util = sum(p.sm_util for p in sample.per_process)
    if sum_util > 0 and sample.sm_util > 0:
        # Cap utilization-attributed share by the device's overall SM util so we
        # don't claim more than the GPU is actually doing.
        active_fraction = min(sample.sm_util / 100.0, 1.0)
        active_w = total * active_fraction
        for p in sample.per_process:
            share = p.sm_util / sum_util
            per_pid[p.pid] = share * active_w
    elif sample.sm_util > 0 and sample.process_pids_running:
        # Per-process util API empty but device is doing work and we know PIDs.
        approximate = True
        if unknown_split == "drop":
            pass
        else:
            active_w = total * (sample.sm_util / 100.0)
            n = len(sample.process_pids_running)
            per = active_w / n
            for pid in sample.process_pids_running:
                per_pid[pid] = per

    attributed = sum(per_pid.values())
    standby = max(total - attributed, 0.0)

    return GpuAttribution(
        timestamp=sample.timestamp,
        gpu_index=sample.index,
        gpu_name=sample.name,
        total_watts=total,
        standby_watts=standby,
        per_pid_watts=per_pid,
        approximate=approximate,
    )
