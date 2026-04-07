from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, generate_latest

from app.core.types import RejectionReason

CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

gateway_requests_total = Counter(
    "gateway_requests_total",
    "Total routed inference requests",
)
gateway_request_errors_total = Counter(
    "gateway_request_errors_total",
    "Total failed requests",
    ["backend"],
)
gateway_request_retries_total = Counter(
    "gateway_request_retries_total",
    "Retries to alternate backend",
)
gateway_queue_depth = Gauge(
    "gateway_queue_depth",
    "Admission queue depth",
)
gateway_queue_age_ms = Gauge(
    "gateway_queue_age_ms",
    "Age of oldest queued item (ms)",
)
gateway_dispatch_total = Counter(
    "gateway_dispatch_total",
    "Dispatches per backend",
    ["backend"],
)
gateway_backend_inflight = Gauge(
    "gateway_backend_inflight",
    "Inflight requests per backend",
    ["backend"],
)
gateway_backend_ewma_ttft_ms = Gauge(
    "gateway_backend_ewma_ttft_ms",
    "EWMA time-to-first-token (ms)",
    ["backend"],
)
gateway_backend_ewma_e2e_ms = Gauge(
    "gateway_backend_ewma_e2e_ms",
    "EWMA end-to-end latency (ms)",
    ["backend"],
)
gateway_backend_error_rate = Gauge(
    "gateway_backend_error_rate",
    "Rolling error rate estimate",
    ["backend"],
)
gateway_backend_circuit_state = Gauge(
    "gateway_backend_circuit_state",
    "Circuit state (0=closed,1=half_open,2=open)",
    ["backend"],
)
gateway_rejections_total = Counter(
    "gateway_rejections_total",
    "Rejections by reason",
    ["reason"],
)

request_latency_ms = Histogram(
    "gateway_request_latency_ms",
    "End-to-end proxy latency",
    buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000),
)


def metrics_response() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST


def observe_rejection(reason: RejectionReason) -> None:
    gateway_rejections_total.labels(reason=str(reason.value)).inc()
