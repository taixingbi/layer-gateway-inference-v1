"""Build and deployment metadata for GET /version (no dependency checks)."""

from __future__ import annotations

import os

SERVICE_NAME = "layer-gateway-inference"


def _env(name: str, default: str = "unknown") -> str:
    value = os.getenv(name, "").strip()
    return value if value else default


def version_payload() -> dict[str, str]:
    """Return service identity and build metadata from environment variables."""
    environment = os.getenv("ENVIRONMENT", "").strip()
    if not environment:
        environment = os.getenv("ENV", "").strip() or "dev"
    return {
        "service": SERVICE_NAME,
        "version": _env("APP_VERSION", "dev"),
        "git_sha": _env("GIT_SHA"),
        "git_branch": _env("GIT_BRANCH"),
        "build_time": _env("BUILD_TIME"),
        "image": _env("BUILD_IMAGE"),
        "image_digest": _env("IMAGE_DIGEST"),
        "environment": environment,
        "status": "ok",
    }
