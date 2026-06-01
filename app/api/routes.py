"""HTTP API: chat completions, health/ready probes, and Prometheus metrics."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from app.backends.probe import not_ready_payload, probe_backends, ready_payload
from app.build_info import version_payload
from app.core.config import GatewayConfig
from app.core.conversation import resolve_conversation_id, strip_conversation_fields
from app.core.logging import log_gateway_event, new_request_id
from app.core.types import BackendTarget, PendingRequest, RejectionReason
from app.metrics.prometheus import (
    gateway_fallback_requests_total,
    gateway_requests_total,
    observe_rejection,
)
from app.metrics.sync import sync_backend_gauges
from app.proxy.client import proxy_chat_completion
from app.queue.admission_queue import AdmissionQueue, QueueFullError
from app.scheduler.classifier import classify_chat_body
from app.scheduler.dispatcher import ScheduleError

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: process is up."""
    return {"status": "ok"}


@router.get("/version")
def version() -> dict[str, str]:
    """Service identity and build metadata (APP_VERSION, GIT_*, BUILD_*, ENVIRONMENT)."""
    return version_payload()


@router.get("/ready")
async def ready(request: Request) -> Response:
    """Readiness: app state OK, then probe each configured vLLM backend GET /health."""
    required_state = ("cfg", "registry", "queue", "http")
    missing = [name for name in required_state if not hasattr(request.app.state, name)]
    if missing:
        detail = not_ready_payload(reason="missing_state", missing=missing)
        return Response(
            content=json.dumps(detail),
            status_code=503,
            media_type="application/json",
        )

    client = request.app.state.http
    if getattr(client, "is_closed", False):
        detail = not_ready_payload(reason="http_client_closed")
        return Response(
            content=json.dumps(detail),
            status_code=503,
            media_type="application/json",
        )

    backend_status = await probe_backends(request.app.state.cfg.backends, client)
    body, status_code = ready_payload(backend_status)
    return Response(
        content=json.dumps(body),
        status_code=status_code,
        media_type="application/json",
    )


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    """Prometheus scrape: registry snapshot + latest in-memory backend gauges."""
    from app.metrics.prometheus import metrics_response

    body, ctype = metrics_response()
    sync_backend_gauges(request.app.state.registry)
    return Response(content=body, media_type=ctype)


@router.api_route("/v1/chat/completions", methods=["POST"])
async def chat_completions(request: Request) -> Response:
    """OpenAI-compatible chat: validate, enqueue, wait for dispatch, proxy to vLLM."""
    rid = request.headers.get("x-request-id") or new_request_id()
    trace_id = request.headers.get("x-trace-id") or request.headers.get("X-Trace-Id")
    session_id = request.headers.get("x-session-id") or request.headers.get("X-Session-Id")
    path = request.url.path or "/v1/chat/completions"
    cfg = request.app.state.cfg
    fallback_enabled = cfg.openai_fallback.enabled
    registry = request.app.state.registry
    queue: AdmissionQueue = request.app.state.queue
    client: httpx.AsyncClient = request.app.state.http

    body = await request.body()
    if not body:
        log_gateway_event(
            logger,
            logging.WARN,
            "request_rejected",
            request_id=rid,
            trace_id=trace_id,
            session_id=session_id,
            path=path,
            gateway_meta={"openai_fallback_enabled": fallback_enabled},
            error={
                "type": "ValidationError",
                "message": "empty body",
                "code": "empty_body",
                "retryable": False,
            },
        )
        raise HTTPException(status_code=400, detail="empty body")

    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        log_gateway_event(
            logger,
            logging.WARN,
            "request_rejected",
            request_id=rid,
            trace_id=trace_id,
            session_id=session_id,
            path=path,
            gateway_meta={"openai_fallback_enabled": fallback_enabled},
            error={
                "type": "ValidationError",
                "message": str(e),
                "code": "invalid_json",
                "retryable": False,
            },
        )
        raise HTTPException(status_code=400, detail=f"invalid json: {e}") from e

    try:
        _validate_minimal_chat(data)
    except HTTPException as e:
        log_gateway_event(
            logger,
            logging.WARN,
            "request_rejected",
            request_id=rid,
            trace_id=trace_id,
            session_id=session_id,
            path=path,
            gateway_meta={"openai_fallback_enabled": fallback_enabled},
            error={
                "type": "ValidationError",
                "message": str(e.detail),
                "code": "invalid_chat_payload",
                "retryable": False,
            },
        )
        raise

    conversation_id, is_new_conversation = resolve_conversation_id(data)
    stripped = strip_conversation_fields(data)
    body = json.dumps(stripped, ensure_ascii=False).encode("utf-8")

    log_gateway_event(
        logger,
        logging.INFO,
        "request_received",
        request_id=rid,
        trace_id=trace_id,
        session_id=session_id,
        conversation_id=conversation_id,
        path=path,
        gateway_meta={"openai_fallback_enabled": fallback_enabled},
    )

    classify = classify_chat_body(body)
    log_gateway_event(
        logger,
        logging.INFO,
        "request_classified",
        request_id=rid,
        trace_id=trace_id,
        session_id=session_id,
        conversation_id=conversation_id,
        path=path,
        gateway_meta={
            "openai_fallback_enabled": fallback_enabled,
            "request_class": classify.req_class.value,
            "stream": classify.stream,
            "est_tokens": classify.est_tokens,
        },
    )

    dispatch_future = asyncio.get_running_loop().create_future()
    q = f"?{request.url.query}" if request.url.query else ""
    pending = PendingRequest(
        request_id=rid,
        conversation_id=conversation_id,
        is_new_conversation=is_new_conversation,
        enqueued_at_monotonic=time.monotonic(),
        classify=classify,
        body=body,
        path=path,
        query=q,
        client_headers={k: v for k, v in request.headers.items() if isinstance(v, str)},
        dispatch_future=dispatch_future,
    )

    gateway_requests_total.inc()

    try:
        await queue.enqueue(pending)
    except QueueFullError:
        fallback = _fallback_target(cfg)
        if fallback:
            log_gateway_event(
                logger,
                logging.WARN,
                "request_dispatched",
                request_id=rid,
                trace_id=trace_id,
                session_id=session_id,
                conversation_id=conversation_id,
                path=path,
                backend=fallback.name,
                gateway_meta={
                    "openai_fallback_enabled": fallback_enabled,
                    "reason": "queue_full_fallback",
                    "provider": "openai",
                },
            )
            gateway_fallback_requests_total.labels(provider="openai").inc()
            return await proxy_chat_completion(
                client=client,
                cfg=cfg,
                registry=registry,
                pending=pending,
                initial=fallback,
                rid=rid,
                trace_id=trace_id,
                session_id=session_id,
            )

        observe_rejection(RejectionReason.QUEUE_FULL)
        log_gateway_event(
            logger,
            logging.WARN,
            "request_rejected",
            request_id=rid,
            trace_id=trace_id,
            session_id=session_id,
            conversation_id=conversation_id,
            path=path,
            gateway_meta={"openai_fallback_enabled": fallback_enabled},
            error={
                "type": "QueueFull",
                "message": "admission queue at capacity",
                "code": RejectionReason.QUEUE_FULL.value,
                "retryable": True,
            },
        )
        raise HTTPException(
            status_code=503,
            detail={"reason": str(RejectionReason.QUEUE_FULL.value), "request_id": rid},
        ) from None

    log_gateway_event(
        logger,
        logging.INFO,
        "request_enqueued",
        request_id=rid,
        trace_id=trace_id,
        session_id=session_id,
        conversation_id=conversation_id,
        path=path,
        gateway_meta={"openai_fallback_enabled": fallback_enabled},
    )

    wait_s = cfg.scheduler.queue_max_age_ms / 1000.0
    try:
        target: BackendTarget = await asyncio.wait_for(dispatch_future, timeout=wait_s)
    except TimeoutError:
        pending.cancelled.set()
        fallback = _fallback_target(cfg)
        if fallback:
            log_gateway_event(
                logger,
                logging.WARN,
                "request_dispatched",
                request_id=rid,
                trace_id=trace_id,
                session_id=session_id,
                conversation_id=conversation_id,
                path=path,
                backend=fallback.name,
                gateway_meta={
                    "openai_fallback_enabled": fallback_enabled,
                    "reason": "queue_age_fallback",
                    "provider": "openai",
                },
            )
            gateway_fallback_requests_total.labels(provider="openai").inc()
            return await proxy_chat_completion(
                client=client,
                cfg=cfg,
                registry=registry,
                pending=pending,
                initial=fallback,
                rid=rid,
                trace_id=trace_id,
                session_id=session_id,
            )

        observe_rejection(RejectionReason.QUEUE_AGE)
        log_gateway_event(
            logger,
            logging.WARN,
            "request_rejected",
            request_id=rid,
            trace_id=trace_id,
            session_id=session_id,
            conversation_id=conversation_id,
            path=path,
            gateway_meta={"openai_fallback_enabled": fallback_enabled},
            error={
                "type": "QueueTimeout",
                "message": "dispatch wait exceeded queue_max_age_ms",
                "code": RejectionReason.QUEUE_AGE.value,
                "retryable": True,
            },
        )
        raise HTTPException(
            status_code=503,
            detail={"reason": str(RejectionReason.QUEUE_AGE.value), "request_id": rid},
        ) from None
    except ScheduleError as e:
        fallback = _fallback_target(cfg)
        if fallback:
            log_gateway_event(
                logger,
                logging.WARN,
                "request_dispatched",
                request_id=rid,
                trace_id=trace_id,
                session_id=session_id,
                conversation_id=conversation_id,
                path=path,
                backend=fallback.name,
                gateway_meta={
                    "openai_fallback_enabled": fallback_enabled,
                    "reason": "no_backend_fallback",
                    "provider": "openai",
                },
            )
            gateway_fallback_requests_total.labels(provider="openai").inc()
            return await proxy_chat_completion(
                client=client,
                cfg=cfg,
                registry=registry,
                pending=pending,
                initial=fallback,
                rid=rid,
                trace_id=trace_id,
                session_id=session_id,
            )

        observe_rejection(RejectionReason.NO_BACKEND)
        # request_rejected for queue age is logged in dispatcher._reject
        raise HTTPException(
            status_code=503,
            detail={
                "reason": str(RejectionReason.NO_BACKEND.value),
                "message": str(e),
                "request_id": rid,
            },
        ) from e

    return await proxy_chat_completion(
        client=client,
        cfg=cfg,
        registry=registry,
        pending=pending,
        initial=target,
        rid=rid,
        trace_id=trace_id,
        session_id=session_id,
    )


def _validate_minimal_chat(data: dict[str, Any]) -> None:
    forbidden_correlation_fields = (
        "request_id",
        "trace_id",
        "session_id",
        "request-id",
        "trace-id",
        "session-id",
    )
    present_forbidden = [k for k in forbidden_correlation_fields if k in data]
    if present_forbidden:
        raise HTTPException(
            status_code=400,
            detail=(
                "request_id/trace_id/session_id must be sent as headers "
                "(x-request-id, x-trace-id, x-session-id), not in request body"
            ),
        )

    if "model" not in data or not data["model"]:
        raise HTTPException(status_code=400, detail="model is required")
    msgs = data.get("messages")
    if not isinstance(msgs, list) or len(msgs) < 1:
        raise HTTPException(status_code=400, detail="messages must be a non-empty array")


def _fallback_target(cfg: GatewayConfig) -> BackendTarget | None:
    fb = cfg.openai_fallback
    if not fb.enabled:
        return None
    return BackendTarget(name=fb.backend_name, base_url=fb.base_url.rstrip("/"))
