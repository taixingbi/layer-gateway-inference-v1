from __future__ import annotations

import logging
import os
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tb_loki_central_logger import LokiHandler

LOGGER_NAME = "layer-gateway-inference-v1"

_loki_handler: LokiHandler | None = None


def setup_logging(level: int = logging.INFO) -> None:
    """JSON logs on stderr; Loki when Grafana env credentials are set (see `.env.example`)."""
    global _loki_handler
    root = logging.getLogger()
    if root.handlers:
        return

    from tb_loki_central_logger import setup_central_logging

    _loki_handler = setup_central_logging(
        logger=root,
        logger_name=LOGGER_NAME,
        timezone=os.environ.get("LOG_TIMEZONE", "UTC"),
        extra_json_fields=("backend",),
        level=level,
        service="layer-gateway-inference-v1",
        component="gateway",
        env=os.environ.get("ENV"),
        version="0.1.0",
        loki_labels={"job": "layer-gateway-inference"},
    )
    _quiet_http_client_loggers()


def _quiet_http_client_loggers() -> None:
    """Avoid httpx/httpcore INFO lines on every Loki push (noise + redundant Loki traffic)."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def shutdown_logging() -> None:
    global _loki_handler
    if _loki_handler is None:
        return
    from tb_loki_central_logger import shutdown_central_logging

    shutdown_central_logging(logging.getLogger(), _loki_handler)
    _loki_handler = None


def new_request_id() -> str:
    return str(uuid.uuid4())


class RequestLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        rid = self.extra.get("request_id", "-")
        return f"[{rid}] {msg}", kwargs
