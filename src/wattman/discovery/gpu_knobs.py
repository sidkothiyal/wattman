"""Enumerate NVIDIA GPU power knobs via nvidia-smi -q -x.

We parse XML rather than depending on pynvml here so settings discovery still
works when pynvml isn't installed.
"""

from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET


def _have_nvidia_smi() -> bool:
    return shutil.which("nvidia-smi") is not None


def _text(node, tag: str) -> str | None:
    el = node.find(tag) if node is not None else None
    return el.text.strip() if el is not None and el.text else None


def scan() -> list[tuple[str, str | None, str]]:
    items: list[tuple[str, str | None, str]] = []
    if not _have_nvidia_smi():
        return items
    try:
        proc = subprocess.run(["nvidia-smi", "-q", "-x"], capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        return items
    if proc.returncode != 0:
        return items
    try:
        root = ET.fromstring(proc.stdout)
    except ET.ParseError:
        return items
    for idx, gpu in enumerate(root.findall("gpu")):
        scope = f"gpu:{idx}"
        items.append(("gpu.persistence_mode", _text(gpu, "persistence_mode"), scope))
        items.append(("gpu.compute_mode", _text(gpu, "compute_mode"), scope))
        power = gpu.find("gpu_power_readings") or gpu.find("power_readings")
        if power is not None:
            items.append(("gpu.power.current_limit_w",
                          _strip_unit(_text(power, "current_power_limit"), "W"), scope))
            items.append(("gpu.power.min_limit_w",
                          _strip_unit(_text(power, "min_power_limit"), "W"), scope))
            items.append(("gpu.power.max_limit_w",
                          _strip_unit(_text(power, "max_power_limit"), "W"), scope))
            items.append(("gpu.power.default_limit_w",
                          _strip_unit(_text(power, "default_power_limit"), "W"), scope))
        pstate = _text(gpu, "performance_state")
        if pstate is not None:
            items.append(("gpu.performance_state", pstate, scope))
        clocks = gpu.find("applications_clocks")
        if clocks is not None:
            items.append(("gpu.app_clocks.graphics_mhz",
                          _strip_unit(_text(clocks, "graphics_clock"), "MHz"), scope))
            items.append(("gpu.app_clocks.memory_mhz",
                          _strip_unit(_text(clocks, "mem_clock"), "MHz"), scope))
        ecc = gpu.find("ecc_mode")
        if ecc is not None:
            items.append(("gpu.ecc.current", _text(ecc, "current_ecc"), scope))
    return items


def _strip_unit(s: str | None, unit: str) -> str | None:
    if s is None:
        return None
    s = s.strip()
    if s.endswith(unit):
        s = s[: -len(unit)].strip()
    return s if s and s != "N/A" else None
