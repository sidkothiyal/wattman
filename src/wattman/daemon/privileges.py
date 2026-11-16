"""Privilege gate. We require sudo so RAPL energy_uj is readable for clean data."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

RAPL_ROOT = Path("/sys/class/powercap")


@dataclass
class PrivilegeReport:
    ok: bool
    euid: int
    rapl_readable: bool
    rapl_probe_path: Path | None
    error: str | None

    def fix_message(self) -> str:
        lines = [
            "wattman requires elevated privileges to read RAPL energy counters cleanly.",
            "",
            "Fixes (any one):",
            "  1) sudo wattman start",
            "  2) Grant your user read access to RAPL energy_uj files (udev rule):",
            "       echo 'SUBSYSTEM==\"powercap\", ACTION==\"add\", RUN+=\"/bin/chmod a+r /sys/class/powercap/intel-rapl:%n/energy_uj\"' \\",
            "         | sudo tee /etc/udev/rules.d/99-rapl.rules",
            "       sudo udevadm control --reload && sudo udevadm trigger",
            "  3) Or for an immediate session-only fix:",
            "       sudo chmod a+r /sys/class/powercap/intel-rapl:*/energy_uj",
        ]
        if self.error:
            lines.insert(1, f"Underlying error: {self.error}")
        return "\n".join(lines)


def _find_rapl_probe() -> Path | None:
    if not RAPL_ROOT.exists():
        return None
    for entry in sorted(RAPL_ROOT.glob("intel-rapl:*")):
        candidate = entry / "energy_uj"
        if candidate.exists():
            return candidate
    return None


def check() -> PrivilegeReport:
    euid = os.geteuid()
    probe = _find_rapl_probe()
    if probe is None:
        return PrivilegeReport(
            ok=False,
            euid=euid,
            rapl_readable=False,
            rapl_probe_path=None,
            error="No /sys/class/powercap/intel-rapl:* energy_uj file present.",
        )
    try:
        with probe.open("rb") as f:
            f.read(32)
        return PrivilegeReport(ok=True, euid=euid, rapl_readable=True, rapl_probe_path=probe, error=None)
    except PermissionError as e:
        return PrivilegeReport(
            ok=False,
            euid=euid,
            rapl_readable=False,
            rapl_probe_path=probe,
            error=str(e),
        )
    except OSError as e:
        return PrivilegeReport(
            ok=False,
            euid=euid,
            rapl_readable=False,
            rapl_probe_path=probe,
            error=str(e),
        )
