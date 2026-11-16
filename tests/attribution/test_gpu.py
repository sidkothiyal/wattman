from __future__ import annotations

from wattman.attribution import gpu as gpu_attr
from wattman.sources.nvidia import GpuProcUtil, GpuSample


def test_proportional_split() -> None:
    sample = GpuSample(
        timestamp=1.0, available=True, index=0, name="RTX 3090",
        power_watts=200.0, sm_util=80.0,
        per_process=[
            GpuProcUtil(pid=1, sm_util=60.0, mem_util=0, enc_util=0, dec_util=0),
            GpuProcUtil(pid=2, sm_util=20.0, mem_util=0, enc_util=0, dec_util=0),
        ],
    )
    out = gpu_attr.attribute(sample)
    # active fraction = 0.8, active_w = 160; pid1 = 0.75 * 160 = 120, pid2 = 40
    assert abs(out.per_pid_watts[1] - 120.0) < 1e-6
    assert abs(out.per_pid_watts[2] - 40.0) < 1e-6
    assert abs(out.standby_watts - 40.0) < 1e-6


def test_fallback_equal_split_when_per_process_empty() -> None:
    sample = GpuSample(
        timestamp=1.0, available=True, index=0, name="RTX 3090",
        power_watts=100.0, sm_util=50.0,
        per_process=[],
        process_pids_running=[10, 20],
    )
    out = gpu_attr.attribute(sample)
    assert out.approximate is True
    # active_w = 50; split 25 each
    assert abs(out.per_pid_watts[10] - 25.0) < 1e-6
    assert abs(out.per_pid_watts[20] - 25.0) < 1e-6


def test_idle_gpu_is_all_standby() -> None:
    sample = GpuSample(timestamp=1.0, available=True, index=0, name="x",
                        power_watts=30.0, sm_util=0.0)
    out = gpu_attr.attribute(sample)
    assert out.per_pid_watts == {}
    assert abs(out.standby_watts - 30.0) < 1e-6
