from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from app.core.logging import new_request_id
from app.core.types import BackendTarget, PendingRequest, RejectionReason
from app.metrics.prometheus import gateway_requests_total, observe_rejection
from app.metrics.sync import sync_backend_gauges
from app.proxy.client import proxy_chat_completion
from app.queue.admission_queue import AdmissionQueue, QueueFullError
from app.scheduler.classifier import classify_chat_body
from app.scheduler.dispatcher import ScheduleError

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    from app.metrics.prometheus import metrics_response

    body, ctype = metrics_response()
    sync_backend_gauges(request.app.state.registry)
    return Response(content=body, media_type=ctype)


@router.api_route("/v1/chat/completions", methods=["POST"])
async def chat_completions(request: Request) -> Response:
    rid = request.headers.get("x-request-id") or new_request_id()
    cfg = request.app.state.cfg
    registry = request.app.state.registry
    queue: AdmissionQueue = request.app.state.queue
    client: httpx.AsyncClient = request.app.state.http

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty body")

    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"invalid json: {e}") from e

    _validate_minimal_chat(data)

    classify = classify_chat_body(body)

    dispatch_future = asyncio.get_running_loop().create_future()
    q = f"?{request.url.query}" if request.url.query else ""
    pending = PendingRequest(
        request_id=rid,
        enqueued_at_monotonic=time.monotonic(),
        classify=classify,
        body=body,
        path=request.url.path or "/v1/chat/completions",
        query=q,
        client_headers={k: v for k, v in request.headers.items() if isinstance(v, str)},
        dispatch_future=dispatch_future,
    )

    gateway_requests_total.inc()

    try:
        await queue.enqueue(pending)
    except QueueFullError:
        observe_rejection(RejectionReason.QUEUE_FULL)
        raise HTTPException(
            status_code=503,
            detail={"reason": str(RejectionReason.QUEUE_FULL.value), "request_id": rid},
        ) from None

    wait_s = cfg.scheduler.queue_max_age_ms / 1000.0
    try:
        target: BackendTarget = await asyncio.wait_for(dispatch_future, timeout=wait_s)
    except TimeoutError:
        pending.cancelled.set()
        observe_rejection(RejectionReason.QUEUE_AGE)
        raise HTTPException(
            status_code=503,
            detail={"reason": str(RejectionReason.QUEUE_AGE.value), "request_id": rid},
        ) from None
    except ScheduleError as e:
        observe_rejection(RejectionReason.NO_BACKEND)
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
    )


def _validate_minimal_chat(data: dict[str, Any]) -> None:
    if "model" not in data or not data["model"]:
        raise HTTPException(status_code=400, detail="model is required")
    msgs = data.get("messages")
    if not isinstance(msgs, list) or len(msgs) < 1:
        raise HTTPException(status_code=400, detail="messages must be a non-empty array")
