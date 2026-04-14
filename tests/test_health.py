"""Tests for backend circuit breaker behavior."""

import time

from app.backends import health as health_mod
from app.backends.state import BackendRuntimeState
from app.core.config import HealthConfig
from app.core.types import CircuitState


def test_circuit_opens_after_failures():
    h = HealthConfig(consecutive_failures_open=3, open_cooldown_ms=1_000)
    s = BackendRuntimeState("x", "http://x", 4, 8)
    for _ in range(3):
        health_mod.on_failure(s, h)
    assert s.circuit == CircuitState.OPEN
    assert s.circuit_opened_at_monotonic is not None


def test_circuit_half_open_after_cooldown():
    h = HealthConfig(consecutive_failures_open=2, open_cooldown_ms=1)
    s = BackendRuntimeState("x", "http://x", 4, 8)
    health_mod.on_failure(s, h)
    health_mod.on_failure(s, h)
    assert s.circuit == CircuitState.OPEN
    s.circuit_opened_at_monotonic = time.monotonic() - 10
    health_mod.maybe_transition_from_open(s, h)
    assert s.circuit == CircuitState.HALF_OPEN
