"""GPU-side suggestion rules."""

from __future__ import annotations

from wattman.suggest.rules import Suggestion, Window, register


@register("gpu_persistence_idle")
def gpu_persistence_idle(window: Window) -> list[Suggestion]:
    settings = window.settings()
    persistence = None
    for k, v in settings.items():
        if k.startswith("gpu.persistence_mode"):
            persistence = v
            break
    if persistence not in ("Enabled", "1"):
        return []
    avg = window.avg_watts("gpu")
    n = window.n_samples("gpu")
    if n < 60:
        return []
    if avg > 30.0:
        return []  # GPU is actually busy
    return [Suggestion(
        rule="gpu_persistence_idle",
        severity="info",
        message=(
            f"GPU persistence mode is enabled but the GPU has averaged only {avg:.1f} W "
            f"over the last {window.lookback_seconds//3600}h. Disabling persistence "
            "(nvidia-smi -pm 0) lets the device drop to deeper sleep states."
        ),
        evidence={"persistence_mode": persistence, "gpu_avg_w": avg, "n": n},
    )]


@register("gpu_powerlimit_unused")
def gpu_powerlimit_unused(window: Window) -> list[Suggestion]:
    settings = window.settings()
    cur = None
    default = None
    for k, v in settings.items():
        if k.startswith("gpu.power.current_limit_w"):
            cur = v
        elif k.startswith("gpu.power.default_limit_w"):
            default = v
    if cur is None or default is None:
        return []
    try:
        cur_f = float(cur)
        default_f = float(default)
    except ValueError:
        return []
    if cur_f < default_f - 1.0:
        return []  # already lowered
    avg = window.avg_watts("gpu")
    n = window.n_samples("gpu")
    if n < 60 or avg > cur_f * 0.4:
        return []
    return [Suggestion(
        rule="gpu_powerlimit_unused",
        severity="info",
        message=(
            f"GPU power limit is at default ({cur_f:.0f} W) but average draw is only "
            f"{avg:.1f} W. Lowering the cap (`nvidia-smi -pl <W>`) caps spikes without "
            "hurting steady-state work."
        ),
        evidence={"current_limit_w": cur_f, "default_limit_w": default_f, "gpu_avg_w": avg},
    )]
