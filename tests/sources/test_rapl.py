from __future__ import annotations

from pathlib import Path

from wattman.sources import rapl


def test_discover_domains(fake_sys_rapl: Path) -> None:
    domains = rapl.discover_domains(fake_sys_rapl)
    names = [d.name for d in domains]
    assert "package-0" in names
    assert "core" in names


def test_compute_watts_basic(fake_sys_rapl: Path) -> None:
    domains = rapl.discover_domains(fake_sys_rapl)
    by_name = {d.name: d for d in domains}
    prev = rapl.RaplReading(timestamp=10.0,
                              energies_uj={"package-0": 1_000_000_000, "core": 700_000_000})
    curr = rapl.RaplReading(timestamp=11.0,
                              energies_uj={"package-0": 1_050_000_000, "core": 720_000_000})
    sample = rapl.compute_watts(prev, curr, domains)
    # 50 mJ over 1s = 50 W; 20 mJ = 20 W
    assert abs(sample.watts["package-0"] - 50.0) < 1e-6
    assert abs(sample.watts["core"] - 20.0) < 1e-6
    assert by_name["package-0"].name == "package-0"


def test_compute_watts_handles_wrap(fake_sys_rapl: Path) -> None:
    domains = rapl.discover_domains(fake_sys_rapl)
    max_uj = domains[0].max_energy_uj
    prev = rapl.RaplReading(timestamp=0.0, energies_uj={"package-0": max_uj - 100_000})
    curr = rapl.RaplReading(timestamp=1.0, energies_uj={"package-0": 200_000})
    sample = rapl.compute_watts(prev, curr, domains)
    # Wrapped delta = 300_000 uJ over 1s = 0.3 W
    assert abs(sample.watts["package-0"] - 0.3) < 1e-6
