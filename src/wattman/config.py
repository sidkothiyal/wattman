"""Runtime configuration loaded from YAML + env, validated by Pydantic."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DB = Path.home() / ".local" / "share" / "wattman" / "wattman.db"
DEFAULT_PID = Path.home() / ".local" / "state" / "wattman" / "wattman.pid"
DEFAULT_LOG = Path.home() / ".local" / "state" / "wattman" / "wattman.log"
DEFAULT_CONFIG = Path.home() / ".config" / "wattman" / "config.yaml"


class SamplerConfig(BaseModel):
    interval_seconds: float = 1.0
    settings_scan_minutes: int = 5
    cpu_proc_min_share: float = 0.001  # processes below 0.1% share are bucketed into __other__


class AttributionConfig(BaseModel):
    gpu_unknown_split: str = "equal"  # equal | drop
    runaway_watts: float = 10.0
    runaway_hours: float = 1.0


class ABConfig(BaseModel):
    before_window_seconds: int = 5 * 60
    after_window_seconds: int = 5 * 60
    after_delay_seconds: int = 15 * 60
    min_samples_per_side: int = 60
    significant_delta_watts: float = 2.0


class RetentionConfig(BaseModel):
    per_second_hours: int = 24
    per_minute_days: int = 30
    per_hour_days: int = 365


class WattmanConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WATTMAN_", env_nested_delimiter="__")

    db_path: Path = Field(default=DEFAULT_DB)
    pid_path: Path = Field(default=DEFAULT_PID)
    log_path: Path = Field(default=DEFAULT_LOG)

    sampler: SamplerConfig = Field(default_factory=SamplerConfig)
    attribution: AttributionConfig = Field(default_factory=AttributionConfig)
    ab: ABConfig = Field(default_factory=ABConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)

    @classmethod
    def load(cls, path: Path | None = None) -> "WattmanConfig":
        path = path or DEFAULT_CONFIG
        if path.exists():
            with path.open() as f:
                data = yaml.safe_load(f) or {}
            return cls(**data)
        return cls()
