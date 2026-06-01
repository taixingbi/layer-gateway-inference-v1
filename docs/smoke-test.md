# Gateway Smoke Test

Use this quick checklist after startup or deploy to verify core gateway behavior.

## Prerequisites

- Gateway is running and reachable
- At least one backend in `config.yaml` is reachable by the gateway

Set your base URL:

```bash
export GATEWAY_URL="http://127.0.0.1:8010"
```

## 1) Liveness (`/health`)

```bash
curl -sS "$GATEWAY_URL/health"
```

Expected response:

```json
{"status":"ok"}
```

## 2) Readiness (`/ready`)

```bash
curl -i -sS "$GATEWAY_URL/ready"
```

Expected when all backends in `config.yaml` respond `GET /health` with 200:

- `HTTP/1.1 200 OK`
- Body:

```json
{
  "status": "ready",
  "healthy_backends": 2,
  "total_backends": 2,
  "backends": {
    "gpu-node-1": "healthy",
    "gpu-node-2": "healthy"
  }
}
```

If not ready, endpoint returns `503` with `"status": "not_ready"` (missing app state, closed HTTP client, or any backend unhealthy).

## 3) Version (`/version`)

```bash
curl -sS "$GATEWAY_URL/version" | jq .
```

Expected fields: `service`, `version`, `git_sha`, `git_branch`, `build_time`, `image`, `environment`.

## 4) Metrics (`/metrics`)

```bash
curl -sS "$GATEWAY_URL/metrics" | rg "gateway_requests_total|gateway_queue_depth|gateway_dispatch_total"
```

Expected: one or more matching metric lines.

## 5) Optional: quick correlation-ID check in logs

Send a request and then check logs for the same ids:

```bash
curl -sS "$GATEWAY_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: smoke-req-2" \
  -H "X-Trace-Id: smoke-trace-2" \
  -H "X-Session-Id: smoke-session-2" \
  -d '{"model":"Qwen/Qwen2.5-7B-Instruct","messages":[{"role":"user","content":"ping"}]}'
```

Then verify log lines include:

- `request_id=smoke-req-2`
- `trace_id=smoke-trace-2`
- `session_id=smoke-session-2`

## 5) Conversation id (body)

Omit `conversation_id` to let the gateway assign `conv_` + 32 hex. The gateway sets `is_new_conversation: true` in the **merged JSON response** (non-stream), **leading SSE event** (stream), and **`x-is-new-conversation`** response header—not in structured logs. Response headers include `x-conversation-id` and `x-is-new-conversation`.

```bash
curl -sS "$GATEWAY_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen2.5-7B-Instruct","messages":[{"role":"user","content":"ping"}]}'
```

Reuse an existing thread id:

```bash
curl -sS "$GATEWAY_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen2.5-7B-Instruct","messages":[{"role":"user","content":"follow up"}],"conversation_id":"my-thread-1"}'
```

## 6) k3s smoke examples

These are direct examples against a k3s-exposed gateway service.

Basic request:

```bash
curl http://192.168.86.179:30180/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen2.5-7B-Instruct", "messages":
      [{"role": "user", "content": "where is jersey city"}],
      "max_tokens": 50}'
```

Request with correlation headers:

```bash
curl http://192.168.86.179:30180/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: request-id-1" \
  -H "X-Trace-Id: trace-id-1" \
  -H "X-Session-Id: session-id-1" \
  -d '{
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "messages": [
      {"role": "user", "content": "where is jersey city"}
    ],
    "max_tokens": 50,
    "temperature": 0.7
  }'
```

Streaming request:

```bash
curl -N http://192.168.86.179:30180/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: request-id-stream-1" \
  -H "X-Trace-Id: trace-id-stream-1" \
  -H "X-Session-Id: session-id-stream-1" \
  -d '{
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "messages": [
      {"role": "user", "content": "tell me 3 facts about jersey city"}
    ],
    "max_tokens": 80,
    "temperature": 0.7,
    "stream": true
  }'
```
