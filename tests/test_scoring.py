from app.backends.state import BackendRuntimeState
from app.core.config import RoutingConfig
from app.core.types import RequestClass
from app.scheduler import scoring


def _backends():
    return [
        BackendRuntimeState("a", "http://a", soft_limit=4, hard_limit=8, inflight=2),
        BackendRuntimeState("b", "http://b", soft_limit=4, hard_limit=8, inflight=5),
    ]


def test_pick_prefers_lower_inflight():
    routing = RoutingConfig()
    a, b = _backends()
    chosen = scoring.pick_backend([a, b], routing, RequestClass.SMALL_CHAT)
    assert chosen.name == "a"


def test_hot_penalty_flips_choice():
    routing = RoutingConfig(hot_penalty_weight=500.0, hot_window_sec=2.0, hot_target_share=0.5)
    a = BackendRuntimeState("a", "http://a", soft_limit=8, hard_limit=16, inflight=2)
    b = BackendRuntimeState("b", "http://b", soft_limit=8, hard_limit=16, inflight=2)
    for _ in range(20):
        a.record_dispatch()
    chosen = scoring.pick_backend([a, b], routing, RequestClass.SMALL_CHAT)
    assert chosen.name == "b"


def test_overload_penalty():
    routing = RoutingConfig(overload_penalty_weight=50.0)
    light = BackendRuntimeState("light", "http://l", soft_limit=4, hard_limit=8, inflight=3)
    heavy = BackendRuntimeState("heavy", "http://h", soft_limit=2, hard_limit=8, inflight=4)
    chosen = scoring.pick_backend([light, heavy], routing, RequestClass.SMALL_CHAT)
    assert chosen.name == "light"
