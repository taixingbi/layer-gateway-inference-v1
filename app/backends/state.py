"""Per-backend mutable metrics: inflight, EWMA latencies, error rate, circuit fields."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from app.core.types import CircuitState


def _ewma(prev: float, sample: float, alpha: float = 0.2) -> float:
    """Exponential moving average: higher ``alpha`` reacts faster to ``sample``."""
    return alpha * sample + (1 - alpha) * prev


@dataclass
class BackendRuntimeState:
    """Mutable per-backend metrics and circuit fields used by scheduler and proxy."""

    name: str
    base_url: str
    soft_limit: int
    hard_limit: int
    drained: bool = False

    # Gateway-side count: requests dispatched here but not yet released by proxy.
    inflight: int = 0
    # Smoothed time-to-first-token (ms); updated on successful responses (see update_success).
    ewma_ttft_ms: float = 50.0
    # Reserved for per-backend queue-wait EWMA; not populated today (scoring hook only).
    ewma_queue_ms: float = 0.0
    # Smoothed end-to-end latency (ms) for completed requests on this backend.
    ewma_e2e_ms: float = 200.0
    # EWMA failure tendency ~[0,1]; eligibility cap + scoring (update_success / update_failure).
    recent_error_rate: float = 0.0

    circuit: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    circuit_opened_at_monotonic: float | None = None
    half_open_probes: int = 0

    large_inflight: int = 0

    _dispatch_times: deque[float] = field(default_factory=lambda: deque(maxlen=256))

    def record_dispatch(self) -> None:
        """Timestamp this dispatch for hot-share / recent-traffic scoring."""
        self._dispatch_times.append(time.monotonic())

    def dispatch_share(self, window_sec: float) -> tuple[int, float]:
        """Count dispatches in the last ``window_sec`` seconds; returns (count, now)."""
        now = time.monotonic()
        cutoff = now - window_sec
        count = sum(1 for t in self._dispatch_times if t >= cutoff)
        return count, now

    def update_success(self, ttft_ms: float | None, e2e_ms: float) -> None:
        """Blend latency samples in; pull error EWMA toward healthy."""
        if ttft_ms is not None:
            self.ewma_ttft_ms = _ewma(self.ewma_ttft_ms, ttft_ms)
        self.ewma_e2e_ms = _ewma(self.ewma_e2e_ms, e2e_ms)
        self.recent_error_rate = _ewma(self.recent_error_rate, 0.0, alpha=0.15)

    def update_failure(self) -> None:
        """Pull error EWMA toward unhealthy (does not update latency EWMA)."""
        self.recent_error_rate = _ewma(self.recent_error_rate, 1.0, alpha=0.25)
