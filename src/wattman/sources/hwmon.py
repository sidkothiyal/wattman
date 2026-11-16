"""hwmon temperature + (optional) power sampler.

Walks /sys/class/hwmon and emits whatever temp*_input and power*_input each
chip exposes, with labels where present.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

HWMON_ROOT = Path("/sys/class/hwmon")


@dataclass
class HwmonReading:
    chip: str
    temperatures_c: dict[str, float] = field(default_factory=dict)
    powers_w: dict[str, float] = field(default_factory=dict)


@dataclass
class HwmonSample:
    timestamp: float
    chips: list[HwmonReading]


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


def _label(base: Path, prefix: str, idx: int, default: str) -> str:
    label = _read_str(base / f"{prefix}{idx}_label")
    return label if label else default


def read_chip(path: Path) -> HwmonReading | None:
    name = _read_str(path / "name")
    if not name:
        return None
    reading = HwmonReading(chip=name)
    # Temperatures (millidegree C)
    for tfile in sorted(path.glob("temp*_input")):
        idx_str = tfile.name.removeprefix("temp").removesuffix("_input")
        try:
            idx = int(idx_str)
        except ValueError:
            continue
        val = _read_int(tfile)
        if val is None:
            continue
        label = _label(path, "temp", idx, f"temp{idx}")
        reading.temperatures_c[label] = val / 1000.0
    # Power (microwatts)
    for pfile in sorted(path.glob("power*_input")):
        idx_str = pfile.name.removeprefix("power").removesuffix("_input")
        try:
            idx = int(idx_str)
        except ValueError:
            continue
        val = _read_int(pfile)
        if val is None:
            continue
        label = _label(path, "power", idx, f"power{idx}")
        reading.powers_w[label] = val / 1_000_000.0
    return reading


class HwmonSampler:
    def __init__(self, root: Path = HWMON_ROOT) -> None:
        self.root = root

    def sample(self) -> HwmonSample:
        chips: list[HwmonReading] = []
        if self.root.exists():
            for chip_path in sorted(self.root.glob("hwmon*")):
                reading = read_chip(chip_path)
                if reading is not None:
                    chips.append(reading)
        return HwmonSample(timestamp=time.monotonic(), chips=chips)
