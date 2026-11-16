"""Shared fixtures. All tests run without root and without real hardware."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from wattman.store import db


@pytest.fixture
def tmp_db(tmp_path: Path) -> sqlite3.Connection:
    conn = db.connect(tmp_path / "test.db")
    yield conn
    conn.close()


@pytest.fixture
def fake_sys_rapl(tmp_path: Path) -> Path:
    """Build a minimal fake /sys/class/powercap tree."""
    root = tmp_path / "powercap"
    pkg = root / "intel-rapl:0"
    pkg.mkdir(parents=True)
    (pkg / "name").write_text("package-0")
    (pkg / "max_energy_range_uj").write_text("262143328850")
    (pkg / "energy_uj").write_text("1000000000")
    sub = pkg / "intel-rapl:0:0"
    sub.mkdir()
    (sub / "name").write_text("core")
    (sub / "max_energy_range_uj").write_text("262143328850")
    (sub / "energy_uj").write_text("700000000")
    return root


@pytest.fixture
def fake_sys_cpu(tmp_path: Path) -> Path:
    """Build a minimal fake /sys/devices/system/cpu tree."""
    root = tmp_path / "cpu"
    root.mkdir()
    cpufreq = root / "cpufreq"
    cpufreq.mkdir()
    (cpufreq / "boost").write_text("1")
    policy0 = cpufreq / "policy0"
    policy0.mkdir()
    (policy0 / "scaling_governor").write_text("performance")
    (policy0 / "scaling_min_freq").write_text("550000")
    (policy0 / "scaling_max_freq").write_text("5084000")
    (policy0 / "scaling_available_governors").write_text("performance powersave")
    (policy0 / "scaling_driver").write_text("acpi-cpufreq")

    cpu0 = root / "cpu0"
    cpu0.mkdir()
    (cpu0 / "cpufreq").symlink_to(policy0)
    cpuidle = cpu0 / "cpuidle"
    cpuidle.mkdir()
    state0 = cpuidle / "state0"
    state0.mkdir()
    (state0 / "name").write_text("POLL")
    (state0 / "disable").write_text("0")
    (state0 / "time").write_text("12345")
    state1 = cpuidle / "state1"
    state1.mkdir()
    (state1 / "name").write_text("C1")
    (state1 / "disable").write_text("1")
    (state1 / "time").write_text("67890")
    return root


@pytest.fixture
def fake_sys_hwmon(tmp_path: Path) -> Path:
    root = tmp_path / "hwmon"
    root.mkdir()
    h0 = root / "hwmon0"
    h0.mkdir()
    (h0 / "name").write_text("zenpower")
    (h0 / "temp1_input").write_text("48000")
    (h0 / "temp1_label").write_text("Tdie")
    (h0 / "power1_input").write_text("12500000")
    (h0 / "power1_label").write_text("SVI2_P_Core")
    return root
