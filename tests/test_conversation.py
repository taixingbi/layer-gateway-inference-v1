"""Tests for conversation_id resolution and stripping."""

import json

from app.core.conversation import resolve_conversation_id, strip_conversation_fields


def test_resolve_missing_generates_conv_prefix_and_new():
    cid, is_new = resolve_conversation_id({"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    assert is_new is True
    assert cid.startswith("conv_")
    assert len(cid) == len("conv_") + 32


def test_resolve_blank_generates_new():
    for blank in ("", "   ", "\t"):
        cid, is_new = resolve_conversation_id(
            {"model": "m", "messages": [{"role": "user", "content": "hi"}], "conversation_id": blank}
        )
        assert is_new is True
        assert cid.startswith("conv_")


def test_resolve_non_blank_preserved():
    cid, is_new = resolve_conversation_id(
        {
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}],
            "conversation_id": "  thread-abc  ",
        }
    )
    assert is_new is False
    assert cid == "thread-abc"


def test_strip_removes_thread_fields():
    data = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "conversation_id": "t1",
        "is_new_conversation": False,
        "stream": False,
    }
    stripped = strip_conversation_fields(data)
    assert "conversation_id" not in stripped
    assert "is_new_conversation" not in stripped
    assert stripped["model"] == "m"
    body = json.dumps(stripped).encode()
    assert b"conversation_id" not in body
