"""One-shot enumeration of all power/perf knobs across CPU, GPU, platform."""

from __future__ import annotations

from wattman.discovery import cpu_knobs, gpu_knobs, platform_knobs


def full_scan() -> list[tuple[str, str | None, str]]:
    items: list[tuple[str, str | None, str]] = []
    items.extend(cpu_knobs.scan())
    items.extend(gpu_knobs.scan())
    items.extend(platform_knobs.scan())
    # stable order
    items.sort(key=lambda x: (x[0], x[2]))
    return items
