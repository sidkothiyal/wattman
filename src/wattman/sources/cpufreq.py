"""Per-CPU cpufreq + cpuidle stats — frequencies and C-state residencies."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

CPU_ROOT = Path("/sys/devices/system/cpu")


@dataclass
class CpuFreqReading:
    cpu: int
    cur_khz: int | None
    governor: str | None
    c_state_residency_us: dict[str, int] = field(default_factory=dict)  # state name -> microseconds


@dataclass
class CpuFreqSample:
    timestamp: float
    cpus: list[CpuFreqReading]


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _read_str(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def read_cpu(cpu_path: Path) -> CpuFreqReading | None:
    try:
        cpu = int(cpu_path.name.removeprefix("cpu"))
    except ValueError:
        return None
    cur_khz = _read_int(cpu_path / "cpufreq" / "scaling_cur_freq")
    governor = _read_str(cpu_path / "cpufreq" / "scaling_governor")
    residencies: dict[str, int] = {}
    cpuidle = cpu_path / "cpuidle"
    if cpuidle.exists():
        for state in sorted(cpuidle.glob("state*")):
            name = _read_str(state / "name") or state.name
            time_us = _read_int(state / "time")
            if time_us is not None:
                residencies[name] = time_us
    return CpuFreqReading(cpu=cpu, cur_khz=cur_khz, governor=governor, c_state_residency_us=residencies)


class CpuFreqSampler:
    def __init__(self, root: Path = CPU_ROOT) -> None:
        self.root = root

    def sample(self) -> CpuFreqSample:
        readings: list[CpuFreqReading] = []
        if self.root.exists():
            for cpu_path in sorted(self.root.glob("cpu[0-9]*")):
                if not (cpu_path / "cpufreq").exists():
                    continue
                reading = read_cpu(cpu_path)
                if reading is not None:
                    readings.append(reading)
        return CpuFreqSample(timestamp=time.monotonic(), cpus=readings)
