"""Tests for upstream backend probes and `/ready` payload."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi.testclient import TestClient

from app.backends.probe import not_ready_payload, probe_backends, ready_payload
from app.core.config import BackendEntry
from app.main import app


def test_probe_backends_all_healthy():
    client = AsyncMock(spec=httpx.AsyncClient)
    ok = MagicMock(status_code=200)
    client.get = AsyncMock(return_value=ok)
    backends = (
        BackendEntry(name="gpu-node-1", url="http://a:30080"),
        BackendEntry(name="gpu-node-2", url="http://b:30080"),
    )
    status = asyncio.run(probe_backends(backends, client))
    assert status == {
        "gpu-node-1": "healthy",
        "gpu-node-2": "healthy",
    }
    assert client.get.await_count == 2


def test_probe_backends_one_fails():
    client = AsyncMock(spec=httpx.AsyncClient)

    async def get(url: str, timeout=None):
        if "a:" in url:
            return MagicMock(status_code=200)
        raise httpx.ConnectError("down")

    client.get = get
    backends = (
        BackendEntry(name="gpu-node-1", url="http://a:30080"),
        BackendEntry(name="gpu-node-2", url="http://b:30080"),
    )
    status = asyncio.run(probe_backends(backends, client))
    assert status["gpu-node-1"] == "healthy"
    assert status["gpu-node-2"] == "unhealthy"


def test_ready_payload_all_healthy():
    body, code = ready_payload(
        {"gpu-node-1": "healthy", "gpu-node-2": "healthy"},
    )
    assert code == 200
    assert body["status"] == "ready"
    assert body["healthy_backends"] == 2
    assert body["total_backends"] == 2


def test_ready_payload_partial():
    body, code = ready_payload(
        {"gpu-node-1": "healthy", "gpu-node-2": "unhealthy"},
    )
    assert code == 503
    assert body["status"] == "not_ready"
    assert body["healthy_backends"] == 1


def test_not_ready_payload_shape():
    body = not_ready_payload(reason="missing_state", missing=["cfg"])
    assert body["healthy_backends"] == 0
    assert body["backends"] == {}
    assert body["reason"] == "missing_state"


def test_ready_endpoint_mocked(monkeypatch):
    async def fake_probe(*_args, **_kwargs):
        return {"gpu-node-1": "healthy", "gpu-node-2": "healthy"}

    monkeypatch.setattr("app.api.routes.probe_backends", fake_probe)
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "healthy_backends": 2,
        "total_backends": 2,
        "backends": {
            "gpu-node-1": "healthy",
            "gpu-node-2": "healthy",
        },
    }
