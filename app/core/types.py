"""Shared domain types: circuit/rejection enums, classify result, pending request."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RejectionReason(StrEnum):
    QUEUE_FULL = "queue_full"
    QUEUE_AGE = "queue_age"
    NO_BACKEND = "no_backend"
    OVERLOAD = "overload"


class RequestClass(StrEnum):
    SMALL_CHAT = "small_chat"
    MEDIUM_CHAT = "medium_chat"
    LARGE_CHAT = "large_chat"
    STREAMING_LONG = "streaming_long"
    EMBEDDING = "embedding"


@dataclass
class BackendTarget:
    name: str
    base_url: str


@dataclass
class ClassifyResult:
    req_class: RequestClass
    est_tokens: int
    max_tokens: int | None
    stream: bool
    model: str | None = None


@dataclass
class PendingRequest:
    """A chat completion waiting for scheduler dispatch."""

    request_id: str
    conversation_id: str
    is_new_conversation: bool
    enqueued_at_monotonic: float
    classify: ClassifyResult
    body: bytes
    path: str
    query: str
    client_headers: dict[str, str]
    dispatch_future: asyncio.Future[BackendTarget]
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
