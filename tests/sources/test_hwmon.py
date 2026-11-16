from __future__ import annotations

from pathlib import Path

from wattman.sources import hwmon


def test_hwmon_reads_temp_and_power(fake_sys_hwmon: Path) -> None:
    sampler = hwmon.HwmonSampler(root=fake_sys_hwmon)
    sample = sampler.sample()
    assert len(sample.chips) == 1
    chip = sample.chips[0]
    assert chip.chip == "zenpower"
    assert chip.temperatures_c["Tdie"] == 48.0
    assert abs(chip.powers_w["SVI2_P_Core"] - 12.5) < 1e-6


def test_hwmon_empty_dir(tmp_path: Path) -> None:
    sampler = hwmon.HwmonSampler(root=tmp_path / "missing")
    sample = sampler.sample()
    assert sample.chips == []
