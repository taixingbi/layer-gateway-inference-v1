from __future__ import annotations

import asyncio
import logging
import time

from app.backends import health as health_mod
from app.backends.registry import BackendRegistry
from app.core.config import GatewayConfig
from app.core.types import BackendTarget, PendingRequest, RejectionReason, RequestClass
from app.metrics.prometheus import gateway_dispatch_total, observe_rejection
from app.metrics.sync import sync_backend_gauges
from app.queue.admission_queue import AdmissionQueue
from app.scheduler import scoring

logger = logging.getLogger(__name__)


class ScheduleError(Exception):
    """Failed to assign a backend within policy."""


async def run_scheduler_loop(
    cfg: GatewayConfig,
    registry: BackendRegistry,
    queue: AdmissionQueue,
    stop: asyncio.Event,
) -> None:
    tick_s = cfg.scheduler.tick_ms / 1000.0
    max_age_s = cfg.scheduler.queue_max_age_ms / 1000.0
    while not stop.is_set():
        t0 = time.monotonic()
        try:
            await registry.tick_circuits()
            await _dispatch_tick(cfg, registry, queue, max_age_s)
            sync_backend_gauges(registry)
        except Exception:
            logger.exception("scheduler tick failed")
        elapsed = time.monotonic() - t0
        wait = max(0.0, tick_s - elapsed)
        try:
            await asyncio.wait_for(stop.wait(), timeout=wait)
        except TimeoutError:
            pass


async def _dispatch_tick(
    cfg: GatewayConfig,
    registry: BackendRegistry,
    queue: AdmissionQueue,
    max_age_s: float,
) -> None:
    batch = await queue.pop_batch(cfg.scheduler.dispatch_batch_size)
    if not batch:
        return

    requeue: list[PendingRequest] = []
    now = time.monotonic()

    for pending in batch:
        if pending.cancelled.is_set() or pending.dispatch_future.done():
            continue

        age_s = now - pending.enqueued_at_monotonic
        if age_s >= max_age_s:
            _reject(pending, ScheduleError("queue age exceeded"))
            observe_rejection(RejectionReason.QUEUE_AGE)
            continue

        eligible = [s for s in registry.all_states() if registry.is_healthy_for_schedule(s)]
        if not eligible:
            requeue.append(pending)
            continue

        chosen = scoring.pick_backend(eligible, cfg.routing, pending.classify.req_class)
        if chosen is None:
            requeue.append(pending)
            continue

        health_mod.on_request_start(chosen, registry.health_config())
        chosen.inflight += 1
        if pending.classify.req_class in (
            RequestClass.LARGE_CHAT,
            RequestClass.STREAMING_LONG,
        ):
            chosen.large_inflight += 1
        chosen.record_dispatch()
        gateway_dispatch_total.labels(backend=chosen.name).inc()
        target = BackendTarget(name=chosen.name, base_url=chosen.base_url)
        pending.dispatch_future.set_result(target)

    if requeue:
        await queue.requeue_front(requeue)


def _reject(pending: PendingRequest, exc: Exception) -> None:
    if not pending.dispatch_future.done():
        pending.dispatch_future.set_exception(exc)
