"""Structured JSON logging, gateway events, and root logger setup for stdout."""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _load_log_timezone(name: str) -> ZoneInfo:
    """Resolve LOG_TIMEZONE; slim images need PyPI ``tzdata`` (see pyproject)."""
    raw = (name or "EST").strip()
    # "EST" is not a stable IANA key everywhere; US Eastern is the usual intent.
    if raw.upper() in ("EST", "EDT") or raw == "US/Eastern":
        raw = "America/New_York"
    try:
        return ZoneInfo(raw)
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/New_York")

# Legacy JSON key order (non-gateway lines)
_JSON_CONTEXT_KEYS = ("request_id", "session_id", "method", "path", "status")
_JSON_FIXED_KEYS = frozenset(
    {"ts", "level", "logger", *_JSON_CONTEXT_KEYS, "message", "error"}
)

_GATEWAY_OPTIONAL_STRINGS = (
    "trace_id",
    "request_id",
    "session_id",
    "conversation_id",
    "path",
    "backend",
)


def _gateway_env() -> str:
    """Deployment label for structured logs (``GATEWAY_ENV`` then ``ENV``, else dev)."""
    return os.environ.get("GATEWAY_ENV") or os.environ.get("ENV", "dev")


def log_gateway_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    conversation_id: str | None = None,
    is_new_conversation: bool | None = None,
    path: str | None = None,
    backend: str | None = None,
    latency_ms: float | None = None,
    status_code: int | None = None,
    error: Mapping[str, Any] | None = None,
    gateway_meta: Mapping[str, Any] | None = None,
) -> None:
    """Emit one structured gateway log line (see tmp.md schema)."""
    extra: dict[str, Any] = {
        "event": event,
        "service": "gateway",
        "env": _gateway_env(),
    }
    if request_id is not None:
        extra["request_id"] = request_id
    if trace_id is not None:
        extra["trace_id"] = trace_id
    if session_id is not None:
        extra["session_id"] = session_id
    if conversation_id is not None:
        extra["conversation_id"] = conversation_id
    if is_new_conversation is not None:
        extra["is_new_conversation"] = is_new_conversation
    if path is not None:
        extra["path"] = path
    if backend is not None:
        extra["backend"] = backend
    if latency_ms is not None:
        extra["latency_ms"] = latency_ms
    if status_code is not None:
        extra["status_code"] = status_code
    if error is not None:
        extra["structured_error"] = dict(error)
    if gateway_meta is not None:
        extra["gateway_meta"] = dict(gateway_meta)
    logger.log(level, event, extra=extra)


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line: gateway schema when `event` is set, else legacy shape."""

    def __init__(
        self,
        *,
        timezone: str = "America/New_York",
        extra_fields: Sequence[str] = (),
    ):
        super().__init__()
        self._tz = _load_log_timezone(timezone)
        self._extras = tuple(extra_fields)

    def format(self, record: logging.LogRecord) -> str:
        if getattr(record, "event", None):
            return self._format_gateway(record)
        return self._format_legacy(record)

    @staticmethod
    def _gateway_level(levelname: str) -> str:
        if levelname == "WARNING":
            return "WARN"
        return levelname

    def _format_gateway(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=self._tz).isoformat(),
            "level": self._gateway_level(record.levelname),
            "event": record.event,
            "service": getattr(record, "service", "gateway"),
            "env": getattr(record, "env", "-"),
        }
        for key in _GATEWAY_OPTIONAL_STRINGS:
            val = getattr(record, key, None)
            payload[key] = val if val not in (None, "") else "-"
        if getattr(record, "is_new_conversation", None) is not None:
            payload["is_new_conversation"] = bool(record.is_new_conversation)
        if getattr(record, "latency_ms", None) is not None:
            payload["latency_ms"] = record.latency_ms
        if getattr(record, "status_code", None) is not None:
            payload["status_code"] = record.status_code
        err = getattr(record, "structured_error", None)
        if err is not None:
            payload["error"] = err
        if getattr(record, "gateway_meta", None) is not None:
            payload["gateway_meta"] = record.gateway_meta
        for key in self._extras:
            if key in payload or key in {"ts", "level", "event", "service", "env", "error"}:
                continue
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)

    def _format_legacy(self, record: logging.LogRecord) -> str:
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

    tz = os.environ.get("LOG_TIMEZONE", "America/New_York")
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
    """Flush stdout handlers on shutdown (e.g. container stop)."""
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler):
            h.flush()


def new_request_id() -> str:
    """UUID for ``x-request-id`` when the client does not send one."""
    return str(uuid.uuid4())


class RequestLogAdapter(logging.LoggerAdapter):
    """Prefix log lines with ``[request_id]`` for grep-friendly legacy logs."""

    def process(self, msg, kwargs):
        rid = self.extra.get("request_id", "-")
        return f"[{rid}] {msg}", kwargs
