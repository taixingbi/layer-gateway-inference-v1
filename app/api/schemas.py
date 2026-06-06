"""Pydantic shapes for OpenAI-style chat payloads (optional strict validation)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """One chat message (OpenAI-style ``role`` + ``content``)."""

    role: str
    content: str | list[dict[str, Any]]


class ChatCompletionRequest(BaseModel):
    """Minimal chat completion request shape (optional validation)."""

    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    max_tokens: int | None = None
    stream: bool = True
    temperature: float | None = None
    top_p: float | None = None
