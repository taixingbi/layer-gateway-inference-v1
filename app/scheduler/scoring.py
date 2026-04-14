"""Score backends for dispatch: load, latency, errors, hot-spot, overload, class mix."""

from __future__ import annotations

from app.backends.state import BackendRuntimeState
from app.core.config import RoutingConfig
from app.core.types import RequestClass


def _class_penalty_for_backend(large_inflight: int, classify: RequestClass) -> float:
    """Advisory: nudge away from backends already holding large work."""
    if large_inflight <= 0:
        return 0.0
    if classify in (RequestClass.SMALL_CHAT, RequestClass.MEDIUM_CHAT):
        return min(5.0, float(large_inflight) * 1.5)
    return 0.0


def hot_penalty(
    state: BackendRuntimeState,
    total_dispatches: int,
    routing: RoutingConfig,
) -> float:
    """Penalize backends that take too large a share of recent dispatches (anti hotspot)."""
    if total_dispatches <= 0:
        return 0.0
    share = state.dispatch_share(routing.hot_window_sec)[0] / total_dispatches
    if share <= routing.hot_target_share:
        return 0.0
    excess = share - routing.hot_target_share
    return routing.hot_penalty_weight * (excess**2) * 100


def overload_penalty(state: BackendRuntimeState, routing: RoutingConfig) -> float:
    """Soft penalty once inflight exceeds soft_limit (steer before hard_limit)."""
    if state.inflight <= state.soft_limit:
        return 0.0
    over = state.inflight - state.soft_limit
    return routing.overload_penalty_weight * float(over)


def score_backend(
    state: BackendRuntimeState,
    routing: RoutingConfig,
    classify: RequestClass,
    total_dispatches_window: int,
) -> float:
    """Weighted cost for one backend; lower is better. Used by ``pick_backend``."""
    # ``ewma_queue_ms`` is reserved for a per-backend queue signal; it is not updated yet.
    s = (
        routing.inflight_weight * float(state.inflight)
        + routing.queue_weight * state.ewma_queue_ms
        + routing.ttft_weight * state.ewma_ttft_ms
        + routing.e2e_weight * state.ewma_e2e_ms
        + routing.error_weight * state.recent_error_rate
        + hot_penalty(state, total_dispatches_window, routing)
        + overload_penalty(state, routing)
        + _class_penalty_for_backend(state.large_inflight, classify)
    )
    return s


def pick_backend(
    candidates: list[BackendRuntimeState],
    routing: RoutingConfig,
    classify: RequestClass,
) -> BackendRuntimeState | None:
    """Choose eligible backend with minimum ``score_backend`` (tie-break: sort order)."""
    if not candidates:
        return None
    total_d = 0
    for c in candidates:
        total_d += c.dispatch_share(routing.hot_window_sec)[0]
    scored = [(score_backend(c, routing, classify, total_d), c) for c in candidates]
    scored.sort(key=lambda x: x[0])
    return scored[0][1]
