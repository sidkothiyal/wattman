from __future__ import annotations

from pathlib import Path

from wattman.discovery import cpu_knobs


def test_cpu_knobs_scan(fake_sys_cpu: Path) -> None:
    items = cpu_knobs.scan(root=fake_sys_cpu)
    knobs = {(knob, scope): value for knob, value, scope in items}
    assert knobs.get(("cpu.boost", "global")) == "1"
    assert knobs.get(("cpu.cpufreq.scaling_governor", "policy:policy0")) == "performance"
    assert knobs.get(("cpu.cpuidle.C1.disable", "cpu0")) == "1"
    assert knobs.get(("cpu.cpuidle.POLL.disable", "cpu0")) == "0"
