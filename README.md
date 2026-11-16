# wattman

System power & utilization analyzer. Runs as a daemon that samples CPU
package, DRAM, and GPU power; attributes it per-process and per-standby; tracks
every power/perf knob on the system; and pairs each setting change with the
measured before/after power delta.

Built for Linux workstations with Intel RAPL or AMD's powercap exposure plus
optional NVIDIA NVML. Tested on a Ryzen 9 5950X + RTX 3090 on Ubuntu 22.04
(kernel 6.8).

## Install

```bash
cd /home/siddharth/xyz/wattman
uv sync --extra dev --extra gpu     # gpu extra pulls nvidia-ml-py
```

## Quick start

```bash
sudo $(which wattman) start          # foreground daemon; needs RAPL access
wattman now                          # snapshot of last 5 s
wattman top --by total               # per-process leaderboard (CPU+GPU watts)
wattman report --since 1h            # window report with sparkline
wattman settings                     # all discovered power/perf knobs
wattman settings --diff              # what changed since last snapshot
wattman suggest                      # rule-based tuning suggestions
wattman ab                           # measured Δ watts per setting change
```

## What it measures

- **Package, core, and DRAM watts** from `/sys/class/powercap/intel-rapl:*/energy_uj`
  (works for AMD too — kernel exposes both under `intel-rapl`).
- **Per-process CPU watts** by attributing core watts proportionally to each
  PID's CPU-tick share from `/proc/<pid>/stat`. The remainder of package power
  is bucketed into `__standby__` (uncore, DRAM you can't pin to a PID, package
  idle).
- **Per-process GPU watts** via NVML: `nvmlDeviceGetPowerUsage` × SM-util
  share. When the per-process util API is empty, falls back to equal split
  across compute processes and flags the row as `approximate`.
- **hwmon temps + power inputs** (zenpower, nct6798, NVMe, iwlwifi, etc.).

## What it discovers

CPU governors, EPP, min/max frequencies, C-state enables, boost; GPU
persistence, power limit, pstate, application clocks, ECC; RAPL caps with time
windows; TLP key/values; PCIe ASPM policy; sysctl swappiness / dirty ratios;
kernel command line; per-bus runtime PM summary.

## What it suggests

Transparent, rule-based heuristics with the evidence inline:

- `cpu_governor_overspec` — governor=performance while standby share > 60%.
- `c_state_disabled` — a deep C-state is disabled and idle share is high.
- `gpu_persistence_idle` — persistence is on but GPU is idle most of the day.
- `gpu_powerlimit_unused` — power limit at default but average draw < 40%.
- `pcie_aspm_performance` — ASPM is in performance mode.
- `process_runaway` — a PID has averaged > 10 W for over an hour.
- `ab_validated` — when a setting you changed actually saved/cost > 2 W in the
  measured window, promote it to a confirmed recommendation.

## Accuracy notes

Per-process CPU watts are an **approximation**: we have core-domain watts from
RAPL and per-process CPU ticks from `/proc`, but no per-process DRAM access
counters. The split is `tick_share × core_watts`, with package − attributed
landing in `__standby__`. This is the same heuristic powertop / scaph use.

GPU per-process is approximate when the per-process NVML API can't see all
processes (CUDA MPS, some driver versions). Affected rows have
`approximate = 1` in the DB.

## Running as a service

```ini
# /etc/systemd/system/wattman.service
[Unit]
Description=wattman power sampler
After=multi-user.target

[Service]
Type=simple
ExecStart=/usr/local/bin/wattman start --db /var/lib/wattman/wattman.db
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wattman.service
```
