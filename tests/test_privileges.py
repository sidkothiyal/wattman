from __future__ import annotations

from pathlib import Path

from wattman.daemon import privileges


def test_check_missing_powercap(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(privileges, "RAPL_ROOT", tmp_path / "nope")
    report = privileges.check()
    assert report.ok is False
    assert "fix" in report.fix_message().lower() or "wattman" in report.fix_message().lower()


def test_check_readable(monkeypatch, fake_sys_rapl: Path) -> None:
    monkeypatch.setattr(privileges, "RAPL_ROOT", fake_sys_rapl)
    report = privileges.check()
    assert report.ok is True
    assert report.rapl_probe_path is not None
