"""Tests for admission queue and scheduler tick interactions."""

import asyncio
import time

import pytest

from app.core.types import ClassifyResult, PendingRequest, RequestClass
from app.queue.admission_queue import AdmissionQueue, QueueFullError
from app.scheduler.dispatcher import ScheduleError, _dispatch_tick
from app.core.config import GatewayConfig, BackendEntry, SchedulerConfig
from app.backends.registry import BackendRegistry


@pytest.mark.asyncio
async def test_queue_full():
    q = AdmissionQueue(1)
    loop = asyncio.get_event_loop()
    f1 = loop.create_future()
    f2 = loop.create_future()
    c = ClassifyResult(RequestClass.SMALL_CHAT, 10, 100, False, "m")
    p1 = PendingRequest("1", "conv_1", False, time.monotonic(), c, b"{}", "/v1/chat/completions", "", {}, f1)
    p2 = PendingRequest("2", "conv_2", False, time.monotonic(), c, b"{}", "/v1/chat/completions", "", {}, f2)
    await q.enqueue(p1)
    with pytest.raises(QueueFullError):
        await q.enqueue(p2)


@pytest.mark.asyncio
async def test_dispatch_age_rejects():
    cfg = GatewayConfig(
        scheduler=SchedulerConfig(dispatch_batch_size=10, queue_max_age_ms=50),
        backends=[
            BackendEntry(name="a", url="http://a", soft_limit=8, hard_limit=16),
            BackendEntry(name="b", url="http://b", soft_limit=8, hard_limit=16),
        ],
    )
    registry = BackendRegistry(cfg)
    q = AdmissionQueue(100)
    loop = asyncio.get_event_loop()
    f = loop.create_future()
    c = ClassifyResult(RequestClass.SMALL_CHAT, 10, 100, False, "m")
    past = time.monotonic() - 1.0
    p = PendingRequest("x", "conv_x", False, past, c, b"{}", "/v1/chat/completions", "", {}, f)
    await q.enqueue(p)
    await _dispatch_tick(cfg, registry, q, max_age_s=0.05)
    assert f.done()
    with pytest.raises(ScheduleError):
        await f
