"""GET /version build metadata."""

from fastapi.testclient import TestClient

from app.build_info import SERVICE_NAME, version_payload
from app.main import app


def test_version_payload_from_env(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "v1.0.0")
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.setenv("GIT_BRANCH", "main")
    monkeypatch.setenv("BUILD_TIME", "2026-06-01T12:30:00Z")
    monkeypatch.setenv("BUILD_IMAGE", "ghcr.io/taixingbi/layer-gateway-inference-v1:v1.0.0")
    monkeypatch.setenv("IMAGE_DIGEST", "sha256:deadbeef")
    monkeypatch.setenv("ENVIRONMENT", "ai-dev")
    assert version_payload() == {
        "service": SERVICE_NAME,
        "version": "v1.0.0",
        "git_sha": "abc1234",
        "git_branch": "main",
        "build_time": "2026-06-01T12:30:00Z",
        "image": "ghcr.io/taixingbi/layer-gateway-inference-v1:v1.0.0",
        "image_digest": "sha256:deadbeef",
        "environment": "ai-dev",
        "status": "ok",
    }


def test_version_payload_defaults(monkeypatch):
    for key in (
        "APP_VERSION",
        "GIT_SHA",
        "GIT_BRANCH",
        "BUILD_TIME",
        "BUILD_IMAGE",
        "IMAGE_DIGEST",
        "ENVIRONMENT",
        "ENV",
    ):
        monkeypatch.delenv(key, raising=False)
    body = version_payload()
    assert body["service"] == SERVICE_NAME
    assert body["version"] == "dev"
    assert body["git_sha"] == "unknown"
    assert body["environment"] == "dev"


def test_version_endpoint(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "v1.0.0")
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.setenv("GIT_BRANCH", "main")
    monkeypatch.setenv("BUILD_TIME", "2026-06-01T12:30:00Z")
    monkeypatch.setenv("BUILD_IMAGE", "taixingbi/layer-gateway-inference-v1:v1.0.0")
    monkeypatch.setenv("ENVIRONMENT", "ai-dev")
    with TestClient(app) as client:
        response = client.get("/version")
    assert response.status_code == 200
    assert response.json()["service"] == "layer-gateway-inference"
    assert response.json()["version"] == "v1.0.0"
    assert response.json()["environment"] == "ai-dev"
