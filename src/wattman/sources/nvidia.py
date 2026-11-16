"""NVIDIA GPU sampler via NVML. Degrades gracefully if pynvml is missing."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

try:
    import pynvml  # type: ignore
    _HAS_NVML = True
except ImportError:
    pynvml = None  # type: ignore
    _HAS_NVML = False


@dataclass
class GpuProcUtil:
    pid: int
    sm_util: float       # 0..100, % of SM busy by this process
    mem_util: float      # 0..100
    enc_util: float
    dec_util: float


@dataclass
class GpuSample:
    timestamp: float
    available: bool
    index: int = 0
    name: str = ""
    power_watts: float = 0.0
    sm_util: float = 0.0
    mem_used_bytes: int = 0
    mem_total_bytes: int = 0
    per_process: list[GpuProcUtil] = field(default_factory=list)
    process_pids_running: list[int] = field(default_factory=list)
    note: str = ""


class NvidiaSampler:
    def __init__(self) -> None:
        self.available = False
        self._handles: list = []
        if not _HAS_NVML:
            return
        try:
            pynvml.nvmlInit()
        except Exception:
            return
        try:
            count = pynvml.nvmlDeviceGetCount()
            for i in range(count):
                self._handles.append(pynvml.nvmlDeviceGetHandleByIndex(i))
            self.available = True
        except Exception:
            self.available = False

    def shutdown(self) -> None:
        if _HAS_NVML and self.available:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass

    def sample(self) -> list[GpuSample]:
        if not self.available:
            return []
        ts = time.monotonic()
        out: list[GpuSample] = []
        for i, handle in enumerate(self._handles):
            sample = GpuSample(timestamp=ts, available=True, index=i)
            try:
                sample.name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(sample.name, bytes):
                    sample.name = sample.name.decode()
            except Exception:
                pass
            try:
                sample.power_watts = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
            except Exception:
                pass
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                sample.sm_util = float(util.gpu)
            except Exception:
                pass
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                sample.mem_used_bytes = int(mem.used)
                sample.mem_total_bytes = int(mem.total)
            except Exception:
                pass
            # per-process utilization (rolling window, microseconds)
            try:
                lookback_us = 2_000_000
                procs = pynvml.nvmlDeviceGetProcessUtilization(handle, lookback_us)
                for p in procs:
                    sample.per_process.append(
                        GpuProcUtil(
                            pid=int(p.pid),
                            sm_util=float(p.smUtil),
                            mem_util=float(p.memUtil),
                            enc_util=float(p.encUtil),
                            dec_util=float(p.decUtil),
                        )
                    )
            except Exception as e:
                sample.note = f"per-process unavailable: {type(e).__name__}"
            # fallback list of compute processes
            try:
                running = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                sample.process_pids_running = [int(p.pid) for p in running]
            except Exception:
                pass
            out.append(sample)
        return out
