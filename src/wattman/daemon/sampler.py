"""Orchestrates samplers, attribution, and persistence on a fixed interval."""

from __future__ import annotations

import time
from dataclasses import dataclass

from wattman.attribution import cpu as cpu_attr
from wattman.attribution import gpu as gpu_attr
from wattman.config import WattmanConfig
from wattman.sources.cpu_procs import CpuProcSampler
from wattman.sources.cpufreq import CpuFreqSampler
from wattman.sources.hwmon import HwmonSampler
from wattman.sources.nvidia import NvidiaSampler
from wattman.sources.rapl import RaplSampler


@dataclass
class Tick:
    """Everything one tick produced; the daemon flushes this to SQLite."""

    ts: float
    cpu: cpu_attr.CpuAttribution | None
    gpu: list[gpu_attr.GpuAttribution]


class Sampler:
    def __init__(self, config: WattmanConfig) -> None:
        self.config = config
        self.rapl = RaplSampler()
        self.cpu_proc = CpuProcSampler()
        self.cpufreq = CpuFreqSampler()
        self.hwmon = HwmonSampler()
        self.nvidia = NvidiaSampler()

    def tick(self) -> Tick:
        ts = time.time()
        rapl_sample = self.rapl.sample()
        proc_sample = self.cpu_proc.sample()
        cpu_attribution = None
        if rapl_sample is not None and proc_sample is not None:
            cpu_attribution = cpu_attr.attribute(
                rapl_sample, proc_sample,
                min_share=self.config.sampler.cpu_proc_min_share,
            )

        gpu_attributions: list[gpu_attr.GpuAttribution] = []
        for gpu_sample in self.nvidia.sample():
            gpu_attributions.append(gpu_attr.attribute(
                gpu_sample, unknown_split=self.config.attribution.gpu_unknown_split,
            ))

        return Tick(ts=ts, cpu=cpu_attribution, gpu=gpu_attributions)

    def shutdown(self) -> None:
        self.nvidia.shutdown()
