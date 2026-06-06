"""Tests for upstream chat body normalization (stream flag injection)."""

import json

from app.proxy.client import _upstream_chat_body


def test_upstream_body_injects_stream_true_when_omitted():
    body = json.dumps(
        {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "messages": [{"role": "user", "content": "hi"}],
        }
    ).encode()
    out = json.loads(_upstream_chat_body(body, True).decode())
    assert out["stream"] is True


def test_upstream_body_injects_stream_false():
    body = json.dumps(
        {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "messages": [{"role": "user", "content": "hi"}],
        }
    ).encode()
    out = json.loads(_upstream_chat_body(body, False).decode())
    assert out["stream"] is False


def test_upstream_body_preserves_stream_false():
    body = json.dumps(
        {
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        }
    ).encode()
    out = json.loads(_upstream_chat_body(body, False).decode())
    assert out["stream"] is False
