"""Classify chat requests (size/streaming) from JSON body for scheduling hints."""

from __future__ import annotations

import json
from typing import Any

from app.core.types import ClassifyResult, RequestClass


def _rough_tokens_from_messages(messages: list[dict[str, Any]]) -> int:
    """Cheap token estimate: ~4 characters per token (not a real tokenizer)."""
    n = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            n += max(1, len(content) // 4)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    n += max(1, len(str(part["text"])) // 4)
    return n


def classify_chat_body(body: bytes) -> ClassifyResult:
    """Derive request class from JSON: prompt size + max_tokens (+ streaming rules)."""
    data = json.loads(body.decode("utf-8"))
    messages: list[dict[str, Any]] = list(data.get("messages") or [])
    est = _rough_tokens_from_messages(messages)
    max_tokens = data.get("max_tokens")
    if max_tokens is not None:
        try:
            max_tokens = int(max_tokens)
        except (TypeError, ValueError):
            max_tokens = None
    stream = bool(data.get("stream", True))
    model = data.get("model")
    if isinstance(model, str):
        mname = model
    else:
        mname = None

    # Rough total work: prompt estimate + generation cap (default 512 if omitted).
    total_est = est + (max_tokens or 512)

    # Bucket thresholds (heuristic): streaming long jobs are tracked separately.
    if stream and total_est > 4000:
        req_class = RequestClass.STREAMING_LONG
    elif total_est < 1500:
        req_class = RequestClass.SMALL_CHAT
    elif total_est < 8000:
        req_class = RequestClass.MEDIUM_CHAT
    else:
        req_class = RequestClass.LARGE_CHAT

    return ClassifyResult(
        req_class=req_class,
        est_tokens=est,
        max_tokens=max_tokens,
        stream=stream,
        model=mname,
    )
