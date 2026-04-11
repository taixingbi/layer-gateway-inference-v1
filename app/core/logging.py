from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

# JSON key order: ts → level → logger → request_* / HTTP context → message → error → other extras
_JSON_CONTEXT_KEYS = ("request_id", "session_id", "method", "path", "status")
_JSON_FIXED_KEYS = frozenset(
    {"ts", "level", "logger", *_JSON_CONTEXT_KEYS, "message", "error"}
)


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line (same shape as the former tb-loki-central-logger JsonLogFormatter)."""

    def __init__(
        self,
        *,
        timezone: str = "EST",
        extra_fields: Sequence[str] = (),
    ):
        super().__init__()
        self._tz = ZoneInfo(timezone)
        self._extras = tuple(extra_fields)

    def format(self, record: logging.LogRecord) -> str:
        err = self.formatException(record.exc_info) if record.exc_info else None
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=self._tz).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        for key in _JSON_CONTEXT_KEYS:
            payload[key] = getattr(record, key, "-")
        payload["message"] = record.getMessage()
        payload["error"] = err
        for key in self._extras:
            if key in _JSON_FIXED_KEYS:
                continue
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    """Structured JSON logs on stdout (e.g. collected by Grafana Alloy → Loki)."""
    root = logging.getLogger()
    if root.handlers:
        return

    tz = os.environ.get("LOG_TIMEZONE", "UTC")
    fmt = JsonLogFormatter(timezone=tz, extra_fields=("backend",))

    root.setLevel(level)
    root.handlers.clear()
    root.filters.clear()
    root.propagate = False

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(level)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    _quiet_http_client_loggers()


def _quiet_http_client_loggers() -> None:
    """Reduce INFO noise from HTTP client libraries."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def shutdown_logging() -> None:
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler):
            h.flush()


def new_request_id() -> str:
    return str(uuid.uuid4())


class RequestLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        rid = self.extra.get("request_id", "-")
        return f"[{rid}] {msg}", kwargs
