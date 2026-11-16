"""Platform-wide knobs: kernel cmdline, sysctl, PCIe ASPM, RAPL caps,
TLP config, per-device runtime PM.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

POWERCAP = Path("/sys/class/powercap")
SYS_BUS = Path("/sys/bus")


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _scan_sysctls() -> list[tuple[str, str | None, str]]:
    items: list[tuple[str, str | None, str]] = []
    for sysctl_path, key in (
        (Path("/proc/sys/vm/swappiness"), "vm.swappiness"),
        (Path("/proc/sys/vm/dirty_ratio"), "vm.dirty_ratio"),
        (Path("/proc/sys/vm/dirty_background_ratio"), "vm.dirty_background_ratio"),
        (Path("/proc/sys/kernel/nmi_watchdog"), "kernel.nmi_watchdog"),
    ):
        val = _read(sysctl_path)
        if val is not None:
            items.append((f"sysctl.{key}", val, "global"))
    return items


def _scan_aspm() -> list[tuple[str, str | None, str]]:
    val = _read(Path("/sys/module/pcie_aspm/parameters/policy"))
    return [("pcie.aspm.policy", val, "global")] if val else []


def _scan_cmdline() -> list[tuple[str, str | None, str]]:
    val = _read(Path("/proc/cmdline"))
    return [("kernel.cmdline", val, "global")] if val else []


def _scan_rapl_caps() -> list[tuple[str, str | None, str]]:
    items: list[tuple[str, str | None, str]] = []
    if not POWERCAP.exists():
        return items
    for pkg in sorted(POWERCAP.glob("intel-rapl:*")):
        name = _read(pkg / "name")
        if name is None:
            continue
        scope = name
        for constraint_file in sorted(pkg.glob("constraint_*_power_limit_uw")):
            n = constraint_file.name.split("_")[1]
            uw = _read(constraint_file)
            if uw is not None and uw.isdigit():
                items.append((
                    f"rapl.{name}.constraint{n}.power_limit_w",
                    f"{int(uw) / 1_000_000:.2f}",
                    scope,
                ))
        for constraint_file in sorted(pkg.glob("constraint_*_time_window_us")):
            n = constraint_file.name.split("_")[1]
            us = _read(constraint_file)
            if us is not None and us.isdigit():
                items.append((
                    f"rapl.{name}.constraint{n}.time_window_us",
                    us,
                    scope,
                ))
        enabled = _read(pkg / "enabled")
        if enabled is not None:
            items.append((f"rapl.{name}.enabled", enabled, scope))
    return items


def _scan_tlp() -> list[tuple[str, str | None, str]]:
    items: list[tuple[str, str | None, str]] = []
    if shutil.which("tlp-stat") is None:
        return items
    try:
        proc = subprocess.run(["tlp-stat", "-c"], capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return items
    if proc.returncode != 0:
        return items
    for line in proc.stdout.splitlines():
        line = line.strip()
        # tlp-stat -c emits "KEY=value" or "KEY=\"value\"" with comments starting with #
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if not key or not key.replace("_", "").isalnum():
            continue
        items.append((f"tlp.{key}", value, "global"))
    return items


def _scan_runtime_pm() -> list[tuple[str, str | None, str]]:
    """Summarize counts of control=auto vs on per bus (PCI/USB)."""
    items: list[tuple[str, str | None, str]] = []
    for bus in ("pci", "usb"):
        bus_path = SYS_BUS / bus / "devices"
        if not bus_path.exists():
            continue
        auto = 0
        on = 0
        for dev in bus_path.iterdir():
            ctrl = _read(dev / "power" / "control")
            if ctrl == "auto":
                auto += 1
            elif ctrl == "on":
                on += 1
        items.append((f"runtime_pm.{bus}.auto_count", str(auto), "global"))
        items.append((f"runtime_pm.{bus}.on_count", str(on), "global"))
    return items


def scan() -> list[tuple[str, str | None, str]]:
    out: list[tuple[str, str | None, str]] = []
    out.extend(_scan_sysctls())
    out.extend(_scan_aspm())
    out.extend(_scan_cmdline())
    out.extend(_scan_rapl_caps())
    out.extend(_scan_tlp())
    out.extend(_scan_runtime_pm())
    return out
