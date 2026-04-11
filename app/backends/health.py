from __future__ import annotations

import logging
import time

from app.backends.state import BackendRuntimeState
from app.core.config import HealthConfig
from app.core.logging import log_gateway_event
from app.core.types import CircuitState

_circuit_logger = logging.getLogger(__name__)


def on_request_start(state: BackendRuntimeState, health: HealthConfig) -> None:
    if state.circuit == CircuitState.HALF_OPEN:
        state.half_open_probes += 1


def on_success(state: BackendRuntimeState, _health: HealthConfig) -> None:
    state.consecutive_failures = 0
    if state.circuit == CircuitState.HALF_OPEN:
        state.circuit = CircuitState.CLOSED
        state.half_open_probes = 0
        state.circuit_opened_at_monotonic = None
        log_gateway_event(
            _circuit_logger,
            logging.INFO,
            "circuit_closed",
            backend=state.name,
        )


def on_failure(
    state: BackendRuntimeState,
    health: HealthConfig,
) -> None:
    state.consecutive_failures += 1
    if state.circuit == CircuitState.HALF_OPEN:
        state.circuit = CircuitState.OPEN
        state.circuit_opened_at_monotonic = time.monotonic()
        state.half_open_probes = 0
        log_gateway_event(
            _circuit_logger,
            logging.WARN,
            "circuit_opened",
            backend=state.name,
            gateway_meta={"reason": "half_open_probe_failed"},
        )
        return

    if state.circuit == CircuitState.CLOSED:
        if state.consecutive_failures >= health.consecutive_failures_open:
            state.circuit = CircuitState.OPEN
            state.circuit_opened_at_monotonic = time.monotonic()
            log_gateway_event(
                _circuit_logger,
                logging.WARN,
                "circuit_opened",
                backend=state.name,
                gateway_meta={
                    "reason": "consecutive_failures",
                    "threshold": health.consecutive_failures_open,
                },
            )


def maybe_transition_from_open(state: BackendRuntimeState, health: HealthConfig) -> None:
    if state.circuit != CircuitState.OPEN or state.circuit_opened_at_monotonic is None:
        return
    elapsed_ms = (time.monotonic() - state.circuit_opened_at_monotonic) * 1000
    if elapsed_ms >= health.open_cooldown_ms:
        state.circuit = CircuitState.HALF_OPEN
        state.half_open_probes = 0
        state.consecutive_failures = 0
        log_gateway_event(
            _circuit_logger,
            logging.INFO,
            "circuit_half_open",
            backend=state.name,
            gateway_meta={"cooldown_ms": health.open_cooldown_ms},
        )


def half_open_allow_dispatch(state: BackendRuntimeState, health: HealthConfig) -> bool:
    if state.circuit != CircuitState.HALF_OPEN:
        return True
    return state.half_open_probes < health.half_open_max_inflight
