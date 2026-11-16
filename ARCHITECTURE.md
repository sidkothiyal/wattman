# Architecture — wattman

```
                ┌────────────────────────────────────────────────────────┐
                │                       Daemon                           │
                │                                                        │
   /sys/...     │   RaplSampler ──┐                                      │
   /proc/...    │   CpuProcSamp. ─┤                                      │
   nvml         │   NvidiaSamp. ──┼─► Sampler.tick() ─► attribution ──┐  │
   hwmon        │   HwmonSamp. ───┤        (CPU + GPU)                │  │
   sysfs        │   CpuFreqSamp. ─┘                                   ▼  │
                │                                              power_samples
                │   discovery.scan ─► change_watch ─► settings_snapshot   │
                │                                       └─► setting_change│
                │                                                         │
                │   suggest.rules ─► suggestion                           │
                │            └────► ab.process_pending ─► ab_result       │
                └────────────────────────┬────────────────────────────────┘
                                         │ SQLite (WAL)
                                         ▼
                         CLI (Typer) reads & renders:
                         now / top / report / settings / suggest / ab
```

## Layers

### sources/ — raw measurement
Each module exposes a `sample()` returning a dataclass. Stateful samplers
(those that compute deltas: `RaplSampler`, `CpuProcSampler`) return `None` on
the first call and a populated sample on subsequent calls.

| Module      | Returns                              | Notes |
|-------------|--------------------------------------|-------|
| `rapl`      | per-domain watts (package, core, dram)| handles counter wrap |
| `cpu_procs` | per-PID Δticks + comm + is_kthread   | reads `/proc/*/stat` |
| `nvidia`    | GPU power, sm util, per-PID util     | optional (nvml)      |
| `hwmon`     | temps + power_input per chip         | discovery on each tick |
| `cpufreq`   | per-CPU freq + C-state residency     | informational         |
| `turbostat` | package watts via subprocess         | fallback for unread RAPL |

### attribution/ — turn samples into per-PID watts

- `cpu.attribute(rapl_sample, proc_sample)` → `CpuAttribution` with
  `per_pid_watts`, `standby_watts`, `kernel_watts`, `other_watts`.
- `gpu.attribute(gpu_sample)` → `GpuAttribution` with `per_pid_watts`,
  `standby_watts`, `approximate` flag.

Standby = total − Σ attributed. This bucket explicitly absorbs the systematic
gap between full-package power and what we can pin to running processes
(uncore, DRAM, idle controller draw, fans on motherboard rails).

### store/ — persistence

`db.connect()` opens SQLite in WAL mode with the schema in
`store.db.SCHEMA`. Tables:

- `power_samples` — one row per (ts, pid, source). `pid` is `NULL` for
  system-level totals; `-1` is `__standby__`, `-2` is `__kernel__`, `-3` is
  `__other__`.
- `settings_snapshot` — one row per (ts, knob, value, scope) snapshot,
  rewritten every `sampler.settings_scan_minutes`.
- `setting_change` — one row per detected diff, written by
  `discovery.change_watch` before the new snapshot is inserted.
- `suggestion` — one row per rule firing, with optional `evidence_json`.
- `ab_result` — keyed by `setting_change_id`, populated by
  `suggest.ab.process_pending`.
- `suggestion_dismissed` — per-rule mute, updated by `wattman dismiss`.

### discovery/ — what knobs exist

- `cpu_knobs.scan()` — governor, EPP, freqs, C-states, boost.
- `gpu_knobs.scan()` — parses `nvidia-smi -q -x`.
- `platform_knobs.scan()` — sysctls, ASPM, RAPL caps, TLP config, runtime PM.
- `scan.full_scan()` concatenates and sorts; the daemon calls it every
  `settings_scan_minutes`.
- `change_watch.diff_and_persist()` compares the current scan against the most
  recent persisted snapshot and writes `setting_change` rows.

### suggest/ — rules + A/B

- `rules.py` provides `@register("name")` and `Window` (a read-only handle
  over recent samples + current settings).
- `rules_cpu.py`, `rules_gpu.py`, `rules_platform.py` are imported (and thus
  registered) inside `evaluate_and_persist`.
- `ab.process_pending(conn)` finds `setting_change` rows old enough for the
  full before/after window and computes the watt delta against `package`
  source rows.

### daemon/ — orchestration

- `privileges.check()` — pre-flight RAPL read test.
- `sampler.Sampler.tick()` — calls every source, returns a `Tick`.
- `service.Daemon.run()` — fixed-interval loop:
  1. prime samplers
  2. each tick: sample → persist (`_persist_tick`)
  3. every `settings_scan_minutes`: discover + diff + snapshot
  4. every 5 min: `rules.evaluate_and_persist` (which also runs `ab.process_pending`)

### cli.py — Typer surface

Each command opens its own short-lived SQLite connection. The `suggest` and
`settings --rescan` commands run a fresh evaluation on demand, so the CLI is
useful between daemon ticks.

## Data flow for the A/B feedback loop

1. User runs `sudo cpupower frequency-set -g schedutil`.
2. Next settings scan (≤ 5 min later) sees `scaling_governor` changed.
3. `change_watch.diff_and_persist` writes a `setting_change` row at time `T`.
4. The daemon keeps sampling `power_samples (source='package')`.
5. ≥ `after_delay_seconds + after_window_seconds` after `T`,
   `ab.process_pending` computes the avg over `[T − before_window, T]` and
   `[T + after_delay, T + after_delay + after_window]`, writes `ab_result`.
6. `rules_platform.ab_validated` notices the new `ab_result` and emits a
   `suggestion` row like "saved 6.3 W on average — keep it".

## Things the architecture deliberately does not do

- **No live agentic tuning.** We only ever read knobs; we never write them.
  The user changes settings; we measure the impact.
- **No central per-process accuracy claim.** The standby bucket exists
  because precise per-process power doesn't exist on consumer hardware.
- **No remote shipping.** Everything is local SQLite. Add Prometheus later
  by reading from the DB in a separate process — don't push it into the hot
  path.
