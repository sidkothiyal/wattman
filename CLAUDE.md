# CLAUDE.md — wattman

**wattman** is a system power & utilization analyzer. A foreground daemon samples CPU package / DRAM / GPU watts every second, attributes them per-process and per-`__standby__` bucket, and writes everything to SQLite. CLI commands query the store for snapshots, leaderboards, settings discovery, and rule-based tuning suggestions backed by measured A/B deltas for every setting change.

## Tooling

- **Python env**: `uv` (defined in `pyproject.toml`). Always use `uv run` to execute Python.
- **CLI framework**: Typer (matches `beam`).
- **Config**: Pydantic v2 + YAML at `~/.config/wattman/config.yaml`. Env vars override via `WATTMAN_*` (e.g. `WATTMAN_SAMPLER__INTERVAL_SECONDS=2`).
- **Store**: SQLite WAL at `~/.local/share/wattman/wattman.db` (override with `--db`).
- **Optional**: `nvidia-ml-py` (gpu extra) for NVIDIA power & per-process attribution.

## Commands

```bash
uv sync --extra dev --extra gpu                              # install
sudo $(which wattman) start [--interval 1.0] [--db PATH]     # foreground daemon; needs RAPL access
wattman stop                                                 # SIGTERM the daemon
wattman status                                               # is it running, last sample timestamp
wattman now [--window 5]                                     # snapshot of recent CPU/GPU/standby watts
wattman top --by cpu|gpu|total [--n 15] [--window 5]         # per-process leaderboard
wattman report --since 30m|24h|7d [--format text|json]       # window report + sparkline
wattman settings [--diff] [--rescan]                         # discovered knobs / diff vs last snapshot
wattman suggest [--lookback-hours 24] [--include-dismissed]  # rule-based suggestions (re-evaluates on call)
wattman dismiss <rule>                                       # stop showing a given rule
wattman ab [--limit 25]                                      # measured Δ watts per setting change
wattman check                                                # privilege pre-flight (no daemon)
uv run pytest tests/                                         # full test suite (no hw, no root)
uv run pytest tests/attribution/ -v                          # subset
```

## Non-Obvious Patterns

### Privilege model
The daemon refuses to start unless `/sys/class/powercap/intel-rapl:0/energy_uj` is readable as the current user. We picked "require sudo / explicit setcap" over silent fallback because mixed-source data would invalidate every A/B comparison. The pre-flight check is `wattman check`; it prints exact fix commands when it fails. AMD systems expose RAPL under the `intel-rapl` powercap names too — don't be confused by the path.

### Per-process attribution is approximate by design
We have core-domain watts (RAPL) and per-process CPU ticks (`/proc/<pid>/stat`), so:
`proc_w = (proc_ticks / sum_ticks) × core_w`. Package − attributed lands in the synthetic `__standby__` row (`pid=-1`). Kernel threads (`PF_KTHREAD`) go to `__kernel__` (`pid=-2`). Processes below `cpu_proc_min_share` (default 0.1%) collapse into `__other__` (`pid=-3`) to keep the per-tick fanout small. **Negative PIDs are reserved synthetic buckets** — don't insert real-PID rows with negative ids.

### GPU attribution flags approximation in-band
`approximate = 1` on a `power_samples` row means the per-PID API didn't return util breakdown and we equal-split SM-util-active watts across `nvmlDeviceGetComputeRunningProcesses`. The CLI does not hide these; rule code checks `approximate` when deciding severity.

### Differential samplers must be primed
`RaplSampler`, `CpuProcSampler` return `None` on first `sample()` (no prior reading to diff against). The daemon's main loop calls `sampler.tick()` once before entering the persistence loop. If you add another delta-based source, follow that convention.

### Settings discovery → diff → A/B chain
The order matters:
1. `discovery.scan.full_scan()` enumerates current knob values.
2. `discovery.change_watch.diff_and_persist()` writes `setting_change` rows for any knob whose value differs from the previous snapshot. The diff runs **before** the new snapshot is inserted so it has something to compare against.
3. `suggest.ab.process_pending()` (called from `evaluate_and_persist`) finds `setting_change` rows older than `ABConfig.after_delay_seconds + after_window_seconds` and computes before/after `package` watt averages over `before_window_seconds` / `after_window_seconds`. Result lands in `ab_result` keyed by `setting_change_id`.
4. `rules_platform.ab_validated` picks up `ab_result` rows with `min(n_before, n_after) ≥ 60` and `|Δ| ≥ 2 W` and emits user-facing suggestions.

If you change any of the constants in `ABConfig`, also update `rules_platform.ab_validated`'s thresholds — they intentionally mirror each other.

### Rule registry is import-side-effect
Rules register themselves via the `@register(name)` decorator at module import. `evaluate_and_persist` imports `rules_cpu`, `rules_gpu`, `rules_platform` at the top of its body so adding a new rule module **requires** adding that import there too. (Pattern chosen over auto-discovery to keep imports explicit.)

### Schema is append-only per-sample
`power_samples` is one row per (ts, pid, source). At 1 Hz sampling with ~200 active PIDs and 2 sources this is ~17M rows/day. Retention (in `RetentionConfig`) downsamples to per-minute after 24 h and per-hour after 30 days — but the compaction job is **not yet wired** in `service.py`; add it before running for weeks.

### Wall-clock vs monotonic
`Sampler.tick()` uses `time.time()` (wall-clock, persisted to SQLite). Source-level diff loops use `time.monotonic()` to compute Δt. Don't cross the streams — passing a monotonic ts to `power_samples.ts` will break window queries that compare against `time.time()`.

### Import convention
`src/` is on `PYTHONPATH` (set in `pyproject.toml`'s `[tool.pytest.ini_options]`). Import as `from wattman.sources.rapl import RaplSampler` — **never** `from src.wattman...`.

## Adding New Components

| Component | Steps |
|-----------|-------|
| **Data source** | `src/wattman/sources/my_source.py` exposing a `MySampler.sample()` returning a dataclass. Wire into `daemon/sampler.py:Sampler.tick()`. |
| **Attribution rule** | `src/wattman/attribution/my.py`. Add a `_persist_tick` branch in `daemon/service.py` to insert the produced rows. |
| **Settings knob set** | `src/wattman/discovery/my_knobs.py` returning `list[tuple[knob, value, scope]]`. Add a call in `discovery/scan.py:full_scan()`. |
| **Suggestion rule** | New file under `src/wattman/suggest/` decorated with `@register("rule_name")`. Add an import line in `suggest/rules.py:evaluate_and_persist()`. |
| **CLI command** | New `@app.command()` in `src/wattman/cli.py`. |

## Documentation

- `README.md` — user-facing overview.
- `ARCHITECTURE.md` — implementation details.

Update both when behavior changes. Outdated docs are worse than no docs.

## Testing

Tests mirror `src/` structure under `tests/`. Fixtures in `tests/conftest.py` synthesize `/sys/class/powercap`, `/sys/devices/system/cpu`, and `/sys/class/hwmon` trees under `tmp_path` so the suite runs without root and without real hardware. NVIDIA / hwmon real-hw probes are not part of the suite; verify them via the live verification steps in the plan.

## Planning

If a task looks like it will have more than 3 steps, write a plan first and get alignment before executing.
