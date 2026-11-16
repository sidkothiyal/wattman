"""turbostat subprocess wrapper, used as a fallback for package power when
RAPL energy_uj is unreadable.

Only invoked when the RAPL probe fails AND privileges aren't elevated. Returns
an empty sample silently if turbostat isn't installed.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass


@dataclass
class TurbostatSample:
    timestamp: float
    available: bool
    package_watts: float = 0.0
    raw: str = ""


def _have_turbostat() -> bool:
    return shutil.which("turbostat") is not None


class TurbostatSampler:
    def __init__(self, interval_seconds: float = 1.0) -> None:
        self.interval = interval_seconds
        self.available = _have_turbostat()

    def sample(self) -> TurbostatSample:
        if not self.available:
            return TurbostatSample(timestamp=time.monotonic(), available=False)
        try:
            proc = subprocess.run(
                ["turbostat", "--quiet", "--interval", str(self.interval),
                 "--num_iterations", "1", "--show", "PkgWatt"],
                capture_output=True, text=True, timeout=self.interval + 5.0,
            )
        except (subprocess.TimeoutExpired, OSError):
            return TurbostatSample(timestamp=time.monotonic(), available=False)
        out = proc.stdout.strip().splitlines()
        if len(out) < 2:
            return TurbostatSample(timestamp=time.monotonic(), available=False, raw=proc.stdout)
        # First line is header, second is values.
        header = out[0].split()
        values = out[1].split()
        try:
            col = header.index("PkgWatt")
            pkg = float(values[col])
        except (ValueError, IndexError):
            return TurbostatSample(timestamp=time.monotonic(), available=False, raw=proc.stdout)
        return TurbostatSample(timestamp=time.monotonic(), available=True, package_watts=pkg, raw=proc.stdout)
