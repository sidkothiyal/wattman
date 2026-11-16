from __future__ import annotations

from pathlib import Path

from wattman.sources import cpufreq


def test_cpufreq_reads_governor_and_idle(fake_sys_cpu: Path) -> None:
    sampler = cpufreq.CpuFreqSampler(root=fake_sys_cpu)
    sample = sampler.sample()
    assert len(sample.cpus) == 1
    cpu = sample.cpus[0]
    assert cpu.cpu == 0
    assert cpu.governor == "performance"
    assert "POLL" in cpu.c_state_residency_us
    assert cpu.c_state_residency_us["C1"] == 67890
