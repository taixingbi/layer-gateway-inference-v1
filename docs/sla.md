# Layer Gateway SLA / SLO

This document defines a practical SLA/SLO baseline for `layer-gateway-inference-v1`.

## 1) Scope

The SLA applies to gateway API endpoints:

- `POST /v1/chat/completions`
- `GET /healthz`
- `GET /metrics`

The SLA covers only gateway behavior. It does not guarantee upstream model quality/content.

## 2) Service Level Objective (SLO)

### Availability SLO

- Monthly availability target: **99.9%** for `POST /v1/chat/completions`.
- Availability means request is served without gateway-side failure.

Gateway-side failure includes:

- `5xx` returned by gateway due to queue/scheduler/proxy failure
- timeout before a successful upstream response

### Latency SLO

- P95 end-to-end latency (`gateway_request_latency_ms`): **<= 2500 ms** over 5-minute windows under normal load.
- P99 end-to-end latency (`gateway_request_latency_ms`): **<= 5000 ms** over 5-minute windows under normal load.

### Queue SLO

- `gateway_queue_age_ms` should remain **< queue_max_age_ms** during steady state.
- `gateway_rejections_total{reason="queue_full"}` and `{reason="queue_age"}` should be near zero during normal operation.

## 3) Error Budget

For 99.9% monthly availability, allowed failure budget is approximately:

- 0.1% of total monthly requests, or
- ~43.2 minutes/month equivalent downtime

If budget burn is high, prioritize:

- reducing retries caused by unhealthy backends
- lowering queue pressure
- draining unstable nodes

## 4) How to Measure

Use `/metrics` with Prometheus.

Key metrics:

- `gateway_requests_total`
- `gateway_request_errors_total{backend=...}`
- `gateway_request_retries_total`
- `gateway_request_latency_ms`
- `gateway_queue_depth`
- `gateway_queue_age_ms`
- `gateway_rejections_total{reason=...}`
- `gateway_backend_error_rate{backend=...}`
- `gateway_backend_circuit_state{backend=...}`

Suggested PromQL examples:

```promql
# Request rate
sum(rate(gateway_requests_total[5m]))
```

```promql
# Gateway-visible error rate proxy
sum(rate(gateway_request_errors_total[5m])) / sum(rate(gateway_requests_total[5m]))
```

```promql
# P95 latency
histogram_quantile(0.95, sum by (le) (rate(gateway_request_latency_ms_bucket[5m])))
```

```promql
# Queue age
max(gateway_queue_age_ms)
```

```promql
# Rejections by reason
sum by (reason) (rate(gateway_rejections_total[5m]))
```

## 5) Alerting Baseline

Critical alerts:

- Availability burn: estimated error ratio > 1% for 5 minutes
- Queue age saturation: `gateway_queue_age_ms` > `queue_max_age_ms` for 5 minutes
- No healthy backend: all backends in `open` circuit state

Warning alerts:

- Retry surge: `rate(gateway_request_retries_total[5m])` significantly above baseline
- Rising backend error signal: `gateway_backend_error_rate` sustained above threshold

## 6) Operational Notes

- `trace_id`, `request_id`, and `session_id` are for log correlation, not metric labels.
- Keep metric label cardinality low (do not add request/session IDs as labels).
- When a backend is unstable, set `drained: true` in config to remove it from new scheduling.

## 7) Exclusions

The SLA excludes:

- planned maintenance windows
- upstream provider/network outages outside gateway control
- user-caused invalid requests (`4xx`)
