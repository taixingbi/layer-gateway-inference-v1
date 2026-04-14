"""Registry of per-backend runtime state and scheduling eligibility rules."""

from __future__ import annotations

from collections.abc import Iterator

from app.backends import health as health_mod
from app.backends.state import BackendRuntimeState
from app.core.config import BackendEntry, GatewayConfig, HealthConfig
from app.core.types import CircuitState


class BackendRegistry:
    """In-memory map of backend name → runtime state; eligibility for scheduling."""

    def __init__(self, cfg: GatewayConfig) -> None:
        self._health_cfg = cfg.health
        self._by_name: dict[str, BackendRuntimeState] = {}
        for b in cfg.backends:
            self._by_name[b.name] = self._from_entry(b)

    @staticmethod
    def _from_entry(b: BackendEntry) -> BackendRuntimeState:
        """Build runtime row from static YAML backend entry."""
        return BackendRuntimeState(
            name=b.name,
            base_url=b.url.rstrip("/"),
            soft_limit=b.soft_limit,
            hard_limit=b.hard_limit,
            drained=b.drained,
        )

    def all_states(self) -> Iterator[BackendRuntimeState]:
        """Iterate all backend runtime states (scheduling candidates)."""
        yield from self._by_name.values()

    def get(self, name: str) -> BackendRuntimeState | None:
        """Lookup by backend name, or None if unknown."""
        return self._by_name.get(name)

    async def tick_circuits(self) -> None:
        """Try OPEN → HALF_OPEN transitions on cooldown for every backend."""
        for s in self._by_name.values():
            health_mod.maybe_transition_from_open(s, self._health_cfg)

    def health_config(self) -> HealthConfig:
        """Health thresholds shared across backends (circuit, error rate cap)."""
        return self._health_cfg

    def is_healthy_for_schedule(self, s: BackendRuntimeState) -> bool:
        """True if backend may receive a new dispatch (drain/circuit/limits/errors)."""
        health_mod.maybe_transition_from_open(s, self._health_cfg)
        if s.drained:
            return False
        if s.circuit == CircuitState.OPEN:
            return False
        if s.inflight >= s.hard_limit:
            return False
        if s.recent_error_rate > self._health_cfg.max_error_rate_for_eligibility:
            return False
        if s.circuit == CircuitState.HALF_OPEN and not health_mod.half_open_allow_dispatch(
            s, self._health_cfg
        ):
            return False
        return True
