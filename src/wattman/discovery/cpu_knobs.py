"""Enumerate CPU-side power knobs.

Knob name format: `cpu.<scope>.<key>` so they sort cleanly in the snapshot.
"""

from __future__ import annotations

from pathlib import Path

CPU_ROOT = Path("/sys/devices/system/cpu")


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def scan(root: Path = CPU_ROOT) -> list[tuple[str, str | None, str]]:
    """Returns (knob, value, scope) tuples."""
    items: list[tuple[str, str | None, str]] = []

    # cpufreq policy-level knobs
    cpufreq = root / "cpufreq"
    boost = _read(cpufreq / "boost")
    if boost is not None:
        items.append(("cpu.boost", boost, "global"))

    if cpufreq.exists():
        for policy in sorted(cpufreq.glob("policy*")):
            scope = f"policy:{policy.name}"
            for key in ("scaling_governor", "scaling_min_freq", "scaling_max_freq",
                        "energy_performance_preference", "scaling_driver"):
                val = _read(policy / key)
                if val is not None:
                    items.append((f"cpu.cpufreq.{key}", val, scope))
            avail = _read(policy / "scaling_available_governors")
            if avail is not None:
                items.append(("cpu.cpufreq.scaling_available_governors", avail, scope))

    # Per-CPU cpuidle states
    if root.exists():
        for cpu_path in sorted(root.glob("cpu[0-9]*")):
            try:
                cpu_id = cpu_path.name
            except ValueError:
                continue
            cpuidle = cpu_path / "cpuidle"
            if not cpuidle.exists():
                continue
            for state in sorted(cpuidle.glob("state*")):
                name = _read(state / "name") or state.name
                disable = _read(state / "disable")
                if disable is not None:
                    items.append((f"cpu.cpuidle.{name}.disable", disable, cpu_id))

    return items
