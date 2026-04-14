"""Bounded admission queue: enqueue, batch dequeue, requeue, queue gauges."""

from __future__ import annotations

import asyncio
import time
from collections import deque

from app.core.types import PendingRequest
from app.metrics.prometheus import gateway_queue_age_ms, gateway_queue_depth


class QueueFullError(Exception):
    """Raised when ``enqueue`` would exceed ``max_size`` (admission rejected)."""


class AdmissionQueue:
    """FIFO queue of pending chat requests between API accept and scheduler dispatch."""

    def __init__(self, max_size: int) -> None:
        self._max_size = max_size
        self._q: deque[PendingRequest] = deque()
        self._lock = asyncio.Lock()

    async def enqueue(self, item: PendingRequest) -> None:
        """Append one pending request or raise if at capacity."""
        async with self._lock:
            if len(self._q) >= self._max_size:
                raise QueueFullError()
            self._q.append(item)
            self._update_gauges_locked()

    def _update_gauges_locked(self) -> None:
        """Refresh depth and oldest-wait gauges (caller must hold ``_lock``)."""
        d = len(self._q)
        gateway_queue_depth.set(d)
        if self._q:
            oldest = min(x.enqueued_at_monotonic for x in self._q)
            gateway_queue_age_ms.set(max(0.0, (time.monotonic() - oldest) * 1000))
        else:
            gateway_queue_age_ms.set(0)

    async def pop_batch(self, n: int) -> list[PendingRequest]:
        """Remove up to ``n`` items from the head (FIFO)."""
        async with self._lock:
            out: list[PendingRequest] = []
            while self._q and len(out) < n:
                out.append(self._q.popleft())
            self._update_gauges_locked()
            return out

    async def requeue_front(self, items: list[PendingRequest]) -> None:
        """Put items back at the front preserving relative order (FIFO retry)."""
        async with self._lock:
            for it in reversed(items):
                self._q.appendleft(it)
            self._update_gauges_locked()
