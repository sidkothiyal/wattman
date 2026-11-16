"""CPU-side suggestion rules."""

from __future__ import annotations

from wattman.suggest.rules import Suggestion, Window, register


def _governor(window: Window) -> str | None:
    settings = window.settings()
    # any one policy's governor (they're typically the same across policies)
    for k, v in settings.items():
        if k.startswith("cpu.cpufreq.scaling_governor"):
            return v
    return None


@register("cpu_governor_overspec")
def cpu_governor_overspec(window: Window) -> list[Suggestion]:
    governor = _governor(window)
    if governor != "performance":
        return []
    package_avg = window.avg_watts("package")
    standby_share = window.standby_share("package")
    n = window.n_samples("package")
    if n < 60:
        return []
    if standby_share < 0.6:
        return []  # CPU is actually busy
    return [Suggestion(
        rule="cpu_governor_overspec",
        severity="warn",
        message=(
            f"governor=performance but ~{standby_share*100:.0f}% of package power "
            f"(avg {package_avg:.1f} W over {window.lookback_seconds//3600}h) is in __standby__. "
            "Try schedutil or powersave."
        ),
        evidence={"governor": governor, "package_avg_w": package_avg,
                  "standby_share": standby_share, "n_samples": n},
    )]


@register("c_state_disabled")
def c_state_disabled(window: Window) -> list[Suggestion]:
    settings = window.settings()
    disabled = [k for k, v in settings.items()
                if k.startswith("cpu.cpuidle.") and k.endswith(".disable") and v == "1"]
    if not disabled:
        return []
    standby = window.standby_share("package")
    if standby < 0.5:
        return []
    return [Suggestion(
        rule="c_state_disabled",
        severity="warn",
        message=(
            f"{len(disabled)} cpuidle state(s) disabled while package idle share is "
            f"{standby*100:.0f}%. Re-enabling deep C-states usually cuts standby power."
        ),
        evidence={"disabled_states": disabled[:10], "standby_share": standby},
    )]


@register("process_runaway")
def process_runaway(window: Window) -> list[Suggestion]:
    top = window.top_pids("cpu", limit=5)
    out: list[Suggestion] = []
    for row in top:
        if row.avg_watts >= 10.0 and row.n >= 60:
            out.append(Suggestion(
                rule="process_runaway",
                severity="info",
                message=(
                    f"PID {row.pid} ({row.comm}) averaged {row.avg_watts:.1f} W of CPU power "
                    f"over the last {window.lookback_seconds//3600}h ({row.n} samples)."
                ),
                evidence={"pid": row.pid, "comm": row.comm, "avg_w": row.avg_watts, "n": row.n},
            ))
    return out
