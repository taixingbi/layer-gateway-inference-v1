"""HTTP proxy to vLLM backends: non-stream/stream, retries, health and latency updates."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import HTTPException, Response
from starlette.responses import StreamingResponse

from app.backends import health as health_mod
from app.backends.registry import BackendRegistry
from app.core.config import GatewayConfig
from app.core.types import BackendTarget, ClassifyResult, PendingRequest, RequestClass
from app.core.logging import log_gateway_event
from app.metrics import prometheus as prom
from app.scheduler import scoring

logger = logging.getLogger(__name__)

_SAFE_HEADER = frozenset(
    {
        "content-type",
        "authorization",
        "accept",
        "user-agent",
        "openai-organization",
        "openai-project",
    }
)


def _filter_headers(h: dict[str, str]) -> dict[str, str]:
    """Forward safe client headers only (allowlist + ``x-*`` custom headers)."""
    out: dict[str, str] = {}
    for k, v in h.items():
        lk = k.lower()
        if lk in _SAFE_HEADER or lk.startswith("x-"):
            out[lk] = v
    return out


def _release_dispatch(
    registry: BackendRegistry,
    backend_name: str,
    classify: ClassifyResult,
) -> None:
    """Decrement gateway-side inflight (and large_inflight) when a dispatch ends."""
    st = registry.get(backend_name)
    if not st:
        return
    st.inflight = max(0, st.inflight - 1)
    if classify.req_class in (RequestClass.LARGE_CHAT, RequestClass.STREAMING_LONG):
        st.large_inflight = max(0, st.large_inflight - 1)


def _pick_retry_target(
    registry: BackendRegistry,
    cfg: GatewayConfig,
    classify: ClassifyResult,
    avoid: str,
) -> BackendTarget | None:
    """Pick another healthy backend for retry; bumps inflight on the new target."""
    eligible = [
        s
        for s in registry.all_states()
        if s.name != avoid and registry.is_healthy_for_schedule(s)
    ]
    chosen = scoring.pick_backend(eligible, cfg.routing, classify.req_class)
    if chosen is None:
        return None
    health_mod.on_request_start(chosen, registry.health_config())
    chosen.inflight += 1
    if classify.req_class in (RequestClass.LARGE_CHAT, RequestClass.STREAMING_LONG):
        chosen.large_inflight += 1
    chosen.record_dispatch()
    prom.gateway_dispatch_total.labels(backend=chosen.name).inc()
    return BackendTarget(name=chosen.name, base_url=chosen.base_url)


async def _non_stream_once(
    client: httpx.AsyncClient,
    url: str,
    body: bytes,
    headers: dict[str, str],
    timeout: httpx.Timeout,
) -> httpx.Response:
    """Single blocking POST; full body buffered in memory."""
    return await client.post(url, content=body, headers=headers, timeout=timeout)


def _should_retry_status(code: int, cfg: GatewayConfig) -> bool:
    """True if HTTP status is listed in config ``retry.retryable_statuses``."""
    return code in set(cfg.retry.retryable_statuses)


def _transport_error_detail(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect"
    return type(exc).__name__


def _upstream_unreachable_detail(
    rid: str, attempts: list[dict[str, Any]]
) -> dict[str, Any]:
    """JSON body for 504 after repeated connect/timeout failures."""
    return {
        "message": "upstream timeout or connection error",
        "request_id": rid,
        "attempts": attempts,
        "hint": "Verify vLLM is running and config.yaml backend urls match (e.g. curl http://HOST:PORT/v1/models).",
    }


def _transport_error_payload(exc: Exception, backend: str) -> dict[str, Any]:
    """Structured error dict for logs (transport failures)."""
    kind = _transport_error_detail(exc)
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "code": kind,
        "retryable": True,
    }


async def proxy_chat_completion(
    *,
    client: httpx.AsyncClient,
    cfg: GatewayConfig,
    registry: BackendRegistry,
    pending: PendingRequest,
    initial: BackendTarget,
    rid: str,
    trace_id: str | None = None,
    session_id: str | None = None,
) -> Response | StreamingResponse:
    """Proxy to vLLM with retries; updates health, metrics, and structured logs."""
    timeout = httpx.Timeout(cfg.server.request_timeout_ms / 1000.0)
    headers = _filter_headers(pending.client_headers)
    path = pending.path or "/v1/chat/completions"
    query = pending.query or ""

    target = initial
    attempts = 0
    last_error: Exception | None = None
    transport_attempts: list[dict[str, Any]] = []

    while attempts < cfg.retry.max_attempts:
        attempts += 1
        st = registry.get(target.name)
        url = f"{target.base_url}{path}{query}"
        t0 = time.monotonic()
        log_gateway_event(
            logger,
            logging.INFO,
            "proxy_start",
            request_id=rid,
            trace_id=trace_id,
            session_id=session_id,
            path=path,
            backend=target.name,
            gateway_meta={"attempt": attempts},
        )

        try:
            if pending.classify.stream:
                return await _proxy_streaming(
                    client=client,
                    registry=registry,
                    pending=pending,
                    target=target,
                    url=url,
                    headers=headers,
                    timeout=timeout,
                    rid=rid,
                    trace_id=trace_id,
                    session_id=session_id,
                    transport_attempts=transport_attempts,
                )

            resp = await _non_stream_once(
                client, url, body=pending.body, headers=headers, timeout=timeout
            )
            e2e_ms = (time.monotonic() - t0) * 1000

            if resp.status_code < 400:
                if st:
                    health_mod.on_success(st, registry.health_config())
                    st.update_success(ttft_ms=min(e2e_ms, 10_000.0), e2e_ms=e2e_ms)
                _release_dispatch(registry, target.name, pending.classify)
                prom.request_latency_ms.observe(e2e_ms)
                log_gateway_event(
                    logger,
                    logging.INFO,
                    "proxy_response",
                    request_id=rid,
                    trace_id=trace_id,
                    session_id=session_id,
                    path=path,
                    backend=target.name,
                    latency_ms=e2e_ms,
                    status_code=resp.status_code,
                )
                return Response(
                    content=resp.content, status_code=resp.status_code, headers=dict(resp.headers)
                )

            retryable = resp.status_code >= 500 or _should_retry_status(resp.status_code, cfg)
            if st:
                if resp.status_code >= 500:
                    health_mod.on_failure(st, registry.health_config())
                st.update_failure()
            prom.gateway_request_errors_total.labels(backend=target.name).inc()

            if attempts < cfg.retry.max_attempts and retryable:
                prom.gateway_request_retries_total.inc()
                log_gateway_event(
                    logger,
                    logging.WARN,
                    "proxy_retry",
                    request_id=rid,
                    trace_id=trace_id,
                    session_id=session_id,
                    path=path,
                    backend=target.name,
                    status_code=resp.status_code,
                    gateway_meta={"reason": "upstream_status", "attempt": attempts},
                )
                _release_dispatch(registry, target.name, pending.classify)
                nxt = _pick_retry_target(registry, cfg, pending.classify, avoid=target.name)
                if nxt:
                    target = nxt
                    continue

            _release_dispatch(registry, target.name, pending.classify)
            log_gateway_event(
                logger,
                logging.INFO,
                "proxy_response",
                request_id=rid,
                trace_id=trace_id,
                session_id=session_id,
                path=path,
                backend=target.name,
                latency_ms=e2e_ms,
                status_code=resp.status_code,
            )
            return Response(
                content=resp.content, status_code=resp.status_code, headers=dict(resp.headers)
            )

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_error = e
            transport_attempts.append(
                {
                    "backend": target.name,
                    "url": url,
                    "kind": _transport_error_detail(e),
                    "detail": str(e),
                }
            )
            prom.gateway_request_errors_total.labels(backend=target.name).inc()
            if st:
                health_mod.on_failure(st, registry.health_config())
                st.update_failure()
            log_gateway_event(
                logger,
                logging.WARN,
                "proxy_transport_error",
                request_id=rid,
                trace_id=trace_id,
                session_id=session_id,
                path=path,
                backend=target.name,
                error=_transport_error_payload(e, target.name),
            )
            if attempts < cfg.retry.max_attempts:
                prom.gateway_request_retries_total.inc()
                log_gateway_event(
                    logger,
                    logging.WARN,
                    "proxy_retry",
                    request_id=rid,
                    trace_id=trace_id,
                    session_id=session_id,
                    path=path,
                    backend=target.name,
                    gateway_meta={"reason": "transport", "attempt": attempts},
                )
                _release_dispatch(registry, target.name, pending.classify)
                nxt = _pick_retry_target(registry, cfg, pending.classify, avoid=target.name)
                if nxt:
                    target = nxt
                    continue
            _release_dispatch(registry, target.name, pending.classify)
            log_gateway_event(
                logger,
                logging.ERROR,
                "proxy_final_failure",
                request_id=rid,
                trace_id=trace_id,
                session_id=session_id,
                path=path,
                backend=target.name,
                error={
                    "type": type(e).__name__,
                    "message": str(e),
                    "code": _transport_error_detail(e),
                    "retryable": False,
                },
            )
            raise HTTPException(
                status_code=504,
                detail=_upstream_unreachable_detail(rid, transport_attempts),
            ) from e

    _release_dispatch(registry, target.name, pending.classify)
    log_gateway_event(
        logger,
        logging.ERROR,
        "proxy_final_failure",
        request_id=rid,
        trace_id=trace_id,
        session_id=session_id,
        path=path,
        backend=target.name,
        error={
            "type": "RetryExhausted",
            "message": str(last_error or "retry exhausted"),
            "code": "retry_exhausted",
            "retryable": False,
        },
    )
    raise HTTPException(
        status_code=502,
        detail={
            "message": str(last_error or "retry exhausted"),
            "request_id": rid,
            "attempts": transport_attempts,
        },
    )


async def _proxy_streaming(
    *,
    client: httpx.AsyncClient,
    registry: BackendRegistry,
    pending: PendingRequest,
    target: BackendTarget,
    url: str,
    headers: dict[str, str],
    timeout: httpx.Timeout,
    rid: str,
    trace_id: str | None,
    session_id: str | None,
    transport_attempts: list[dict[str, Any]],
) -> StreamingResponse:
    """Stream response bytes; release inflight after the client finishes reading."""
    path = pending.path or "/v1/chat/completions"
    t0_req = time.monotonic()
    st = registry.get(target.name)
    try:
        req = client.build_request(
            "POST",
            url,
            headers=headers,
            content=pending.body,
            timeout=timeout,
        )
        resp = await client.send(req, stream=True)
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        transport_attempts.append(
            {
                "backend": target.name,
                "url": url,
                "kind": _transport_error_detail(e),
                "detail": str(e),
            }
        )
        if st:
            health_mod.on_failure(st, registry.health_config())
            st.update_failure()
        prom.gateway_request_errors_total.labels(backend=target.name).inc()
        _release_dispatch(registry, target.name, pending.classify)
        log_gateway_event(
            logger,
            logging.WARN,
            "proxy_transport_error",
            request_id=rid,
            trace_id=trace_id,
            session_id=session_id,
            path=path,
            backend=target.name,
            error=_transport_error_payload(e, target.name),
        )
        log_gateway_event(
            logger,
            logging.ERROR,
            "proxy_final_failure",
            request_id=rid,
            trace_id=trace_id,
            session_id=session_id,
            path=path,
            backend=target.name,
            error={
                "type": type(e).__name__,
                "message": str(e),
                "code": _transport_error_detail(e),
                "retryable": False,
            },
        )
        raise HTTPException(
            status_code=504,
            detail=_upstream_unreachable_detail(rid, transport_attempts),
        ) from e

    ttft_ms = (time.monotonic() - t0_req) * 1000

    if resp.status_code >= 400:
        body = await resp.aread()
        await resp.aclose()
        if st:
            if resp.status_code >= 500:
                health_mod.on_failure(st, registry.health_config())
            st.update_failure()
        prom.gateway_request_errors_total.labels(backend=target.name).inc()
        _release_dispatch(registry, target.name, pending.classify)
        log_gateway_event(
            logger,
            logging.INFO,
            "proxy_response",
            request_id=rid,
            trace_id=trace_id,
            session_id=session_id,
            path=path,
            backend=target.name,
            latency_ms=ttft_ms,
            status_code=resp.status_code,
        )
        return Response(content=body, status_code=resp.status_code)

    if st:
        health_mod.on_success(st, registry.health_config())
        st.update_success(ttft_ms=ttft_ms, e2e_ms=ttft_ms)

    log_gateway_event(
        logger,
        logging.INFO,
        "proxy_response",
        request_id=rid,
        trace_id=trace_id,
        session_id=session_id,
        path=path,
        backend=target.name,
        latency_ms=ttft_ms,
        status_code=resp.status_code,
        gateway_meta={"streaming": True, "phase": "headers"},
    )

    first_byte = [True]

    async def wrapped() -> AsyncIterator[bytes]:
        total_t0 = time.monotonic()
        try:
            async for chunk in resp.aiter_bytes():
                if chunk:
                    if first_byte[0]:
                        first_byte[0] = False
                        ttfb_ms = (time.monotonic() - t0_req) * 1000
                        log_gateway_event(
                            logger,
                            logging.INFO,
                            "stream_first_byte",
                            request_id=rid,
                            trace_id=trace_id,
                            session_id=session_id,
                            path=path,
                            backend=target.name,
                            latency_ms=ttfb_ms,
                            status_code=resp.status_code,
                        )
                    yield chunk
        finally:
            await resp.aclose()
            e2e = (time.monotonic() - total_t0) * 1000
            if st:
                st.update_success(ttft_ms=None, e2e_ms=e2e)
            _release_dispatch(registry, target.name, pending.classify)
            prom.request_latency_ms.observe(e2e)
            log_gateway_event(
                logger,
                logging.INFO,
                "stream_complete",
                request_id=rid,
                trace_id=trace_id,
                session_id=session_id,
                path=path,
                backend=target.name,
                latency_ms=e2e,
                status_code=resp.status_code,
            )

    out_headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in ("transfer-encoding", "connection", "content-length", "server")
    }
    return StreamingResponse(
        wrapped(),
        status_code=resp.status_code,
        headers=dict(out_headers),
        media_type=out_headers.get("content-type"),
    )
