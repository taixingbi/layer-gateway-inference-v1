# Conversation ID and new-conversation flag

This gateway assigns a **thread id** for each chat completion call and surfaces it in logs, upstream headers, and client responses.

## Request body (`conversation_id`)

Send an optional string field **`conversation_id`** in the JSON body of `POST /v1/chat/completions` (OpenAI-compatible payload).

| Client sends | Effective `conversation_id` | `is_new_conversation` |
| --- | --- | --- |
| Field missing, or blank after trim | `conv_` + 32 hex characters | `true` |
| Non-blank string | That value (trimmed) | `false` |

The gateway strips **`conversation_id`** and any client **`is_new_conversation`** from the JSON **before** proxying to vLLM or OpenAI fallback, so upstream OpenAI-compatible APIs do not receive unknown fields.

Implementation: [`app/core/conversation.py`](../app/core/conversation.py), wired in [`app/api/routes.py`](../app/api/routes.py).

## Upstream headers (to the model server)

On every proxied request the gateway sets:

- `x-conversation-id`: effective conversation id
- `x-is-new-conversation`: `true` or `false`

These are in addition to forwarded client `x-*` headers (for example `x-request-id`, `x-trace-id`, `x-session-id`).

Implementation: [`app/proxy/client.py`](../app/proxy/client.py) (`_inject_thread_headers`).

## Client response

### Non-streaming (`stream: false`)

On **successful** responses whose body parses as a JSON **object**, the gateway **merges** into that object:

- `conversation_id`
- `is_new_conversation`

Response headers also include `x-conversation-id` and `x-is-new-conversation`. If the upstream body is not JSON (or not an object), the body is passed through unchanged; headers are still set when possible.

### Streaming (`stream: true`)

Before any upstream Server-Sent Event chunks, the gateway emits one synthetic line:

```text
data: {"object":"gateway.conversation","conversation_id":"...","is_new_conversation":...}

```

(two newlines follow, per SSE). Clients that only understand OpenAI chunk types may **ignore** events where `object` is `gateway.conversation`.

Response headers include `x-conversation-id` and `x-is-new-conversation`.

## Structured logs

Chat-path gateway events (for example `request_received`, `request_classified`, `proxy_start`, `proxy_response`, scheduler `request_dispatched`) include **`conversation_id`** (string; missing values in non-chat lines appear as `"-"` in JSON logs). The **`is_new_conversation`** flag is **not** included in structured logs; it is only exposed on HTTP responses (merged JSON, SSE prefix, and `x-is-new-conversation` header).

See also [request-trace-session-ids.md](request-trace-session-ids.md) for header-based correlation ids.
