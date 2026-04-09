from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8010
    request_timeout_ms: int = 60_000


class SchedulerConfig(BaseModel):
    tick_ms: int = 10
    queue_max_size: int = 500
    queue_max_age_ms: int = 2000
    dispatch_batch_size: int = 20


class RoutingConfig(BaseModel):
    inflight_weight: float = 8.0
    queue_weight: float = 0.04
    ttft_weight: float = 0.03
    e2e_weight: float = 0.02
    error_weight: float = 100.0
    hot_penalty_weight: float = 20.0
    overload_penalty_weight: float = 15.0
    hot_window_sec: float = 2.0
    hot_target_share: float = 0.55


class BackendEntry(BaseModel):
    name: str
    url: str
    soft_limit: int = 20
    hard_limit: int = 28
    drained: bool = False


class HealthConfig(BaseModel):
    consecutive_failures_open: int = 5
    open_cooldown_ms: int = 15_000
    half_open_max_inflight: int = 1
    max_error_rate_for_eligibility: float = 0.35


class RetryConfig(BaseModel):
    max_attempts: int = 2
    retryable_statuses: list[int] = Field(default_factory=lambda: [502, 503, 504])


class GatewayConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    backends: list[BackendEntry] = Field(default_factory=list)
    health: HealthConfig = Field(default_factory=HealthConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)


def load_gateway_config(path: str | Path | None = None) -> GatewayConfig:
    p = Path(path or os.environ.get("GATEWAY_CONFIG", "config.yaml"))
    raw = yaml.safe_load(p.read_text())
    return GatewayConfig.model_validate(raw)
