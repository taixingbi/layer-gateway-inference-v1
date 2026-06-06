"""Tests for chat body classification (request class buckets)."""

import json

from app.core.types import RequestClass
from app.scheduler.classifier import classify_chat_body


def test_classify_default_stream_true():
    body = json.dumps(
        {
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 100,
        }
    ).encode()
    r = classify_chat_body(body)
    assert r.stream is True


def test_classify_small():
    body = json.dumps(
        {
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 100,
            "stream": False,
        }
    ).encode()
    r = classify_chat_body(body)
    assert r.req_class == RequestClass.SMALL_CHAT


def test_classify_streaming_long():
    long_content = "x" * 5000
    body = json.dumps(
        {
            "model": "m",
            "messages": [{"role": "user", "content": long_content}],
            "max_tokens": 4096,
            "stream": True,
        }
    ).encode()
    r = classify_chat_body(body)
    assert r.req_class == RequestClass.STREAMING_LONG
