from __future__ import annotations

from app.backends.registry import BackendRegistry
from app.core.types import CircuitState
from app.metrics import prometheus as prom


def sync_backend_gauges(registry: BackendRegistry) -> None:
    for s in registry.all_states():
        prom.gateway_backend_inflight.labels(backend=s.name).set(s.inflight)
        prom.gateway_backend_ewma_ttft_ms.labels(backend=s.name).set(s.ewma_ttft_ms)
        prom.gateway_backend_ewma_e2e_ms.labels(backend=s.name).set(s.ewma_e2e_ms)
        prom.gateway_backend_error_rate.labels(backend=s.name).set(s.recent_error_rate)
        state_val = {
            CircuitState.CLOSED: 0.0,
            CircuitState.HALF_OPEN: 1.0,
            CircuitState.OPEN: 2.0,
        }[s.circuit]
        prom.gateway_backend_circuit_state.labels(backend=s.name).set(state_val)
