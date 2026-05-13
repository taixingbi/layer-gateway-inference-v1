"""Resolve chat thread id from request body; strip gateway-only fields before upstream."""

from __future__ import annotations

import secrets
from typing import Any


def strip_conversation_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy without gateway thread fields (not forwarded to OpenAI/vLLM)."""
    return {k: v for k, v in data.items() if k not in ("conversation_id", "is_new_conversation")}


def resolve_conversation_id(data: dict[str, Any]) -> tuple[str, bool]:
    """
    Effective thread id and whether this request started a new conversation.

    Missing or blank ``conversation_id`` → ``conv_`` + 32 hex chars, ``is_new=True``.
    Non-blank string → that value (stripped), ``is_new=False``.
    """
    raw = data.get("conversation_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip(), False
    return f"conv_{secrets.token_hex(16)}", True
