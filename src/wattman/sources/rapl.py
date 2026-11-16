"""RAPL energy reader. Computes watts per RAPL domain from energy_uj deltas.

Works for both Intel RAPL and AMD's powercap exposure (kernel exposes both
under /sys/class/powercap/intel-rapl:*).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

RAPL_ROOT = Path("/sys/class/powercap")


@dataclass
class RaplDomain:
    path: Path
    name: str           # e.g. "package-0", "core", "dram"
    parent: str | None  # e.g. "package-0" for "core"
    max_energy_uj: int

    @property
    def energy_path(self) -> Path:
        return self.path / "energy_uj"


@dataclass
class RaplReading:
    timestamp: float
    energies_uj: dict[str, int] = field(default_factory=dict)


@dataclass
class RaplSample:
    """Watts per RAPL domain over the interval ending at `timestamp`."""

    timestamp: float
    interval_seconds: float
    watts: dict[str, float]


def discover_domains(root: Path = RAPL_ROOT) -> list[RaplDomain]:
    if not root.exists():
        return []
    domains: list[RaplDomain] = []
    for pkg_path in sorted(root.glob("intel-rapl:*")):
        if not pkg_path.is_dir():
            continue
        if ":" in pkg_path.name and pkg_path.name.count(":") == 1:
            parent = None
        else:
            parent_pkg = pkg_path.name.rsplit(":", 1)[0]
            parent = (root / parent_pkg / "name").read_text().strip() if (root / parent_pkg / "name").exists() else None
        try:
            name = (pkg_path / "name").read_text().strip()
            max_uj = int((pkg_path / "max_energy_range_uj").read_text().strip())
        except OSError:
            continue
        domains.append(RaplDomain(path=pkg_path, name=name, parent=parent, max_energy_uj=max_uj))
        for sub_path in sorted(pkg_path.glob("intel-rapl:*:*")):
            try:
                sub_name = (sub_path / "name").read_text().strip()
                sub_max = int((sub_path / "max_energy_range_uj").read_text().strip())
            except OSError:
                continue
            domains.append(RaplDomain(path=sub_path, name=sub_name, parent=name, max_energy_uj=sub_max))
    return domains


def read_energies(domains: list[RaplDomain]) -> RaplReading:
    reading = RaplReading(timestamp=time.monotonic())
    for d in domains:
        try:
            reading.energies_uj[d.name] = int(d.energy_path.read_text().strip())
        except OSError:
            continue
    return reading


def compute_watts(prev: RaplReading, curr: RaplReading, domains: list[RaplDomain]) -> RaplSample:
    dt = curr.timestamp - prev.timestamp
    watts: dict[str, float] = {}
    by_name = {d.name: d for d in domains}
    if dt <= 0:
        return RaplSample(timestamp=curr.timestamp, interval_seconds=0.0, watts=watts)
    for name, curr_uj in curr.energies_uj.items():
        prev_uj = prev.energies_uj.get(name)
        if prev_uj is None:
            continue
        delta_uj = curr_uj - prev_uj
        if delta_uj < 0:
            # counter wrapped
            d = by_name.get(name)
            if d is not None:
                delta_uj += d.max_energy_uj
            else:
                continue
        joules = delta_uj / 1_000_000.0
        watts[name] = joules / dt
    return RaplSample(timestamp=curr.timestamp, interval_seconds=dt, watts=watts)


class RaplSampler:
    """Stateful sampler. Call sample() each tick; first call returns None."""

    def __init__(self, root: Path = RAPL_ROOT) -> None:
        self.domains = discover_domains(root)
        self._prev: RaplReading | None = None

    def sample(self) -> RaplSample | None:
        curr = read_energies(self.domains)
        if self._prev is None:
            self._prev = curr
            return None
        out = compute_watts(self._prev, curr, self.domains)
        self._prev = curr
        return out
