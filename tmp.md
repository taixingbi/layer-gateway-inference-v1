curl -sS http://192.168.86.173:30080/v1/models
curl -sS http://192.168.86.176:30080/v1/models



curl http://192.168.86.179:30080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen2.5-7B-Instruct", "messages": [{"role": "user", "content": "how you introduce new york city"}], 
  "gpu-memory-utilization": 0.8,
  "max_tokens": 1000,
  "max-model-len": 8192, 
  "max-num-seqs": 32
  }'



for p in 20 40 60 80 100 120; do
  echo "=== concurrency $p ==="
  seq 1 200 | xargs -I{} -P $p sh -c '
    curl -s -o /dev/null -w "%{http_code}\n" http://192.168.86.179:8010/v1/chat/completions \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"Qwen/Qwen2.5-7B-Instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"introduce new york city\"}],
\"max_tokens\":50}"
  ' | sort | uniq -c
done



curl http://192.168.86.179:8010/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "messages": [{"role":"user","content":"introduce new york city"}],
    "stream": true
  }'




  # `conversation_id`

**What it is:** A thread id for your chat. Send it in the JSON body

**If you skip it or send only blanks:** The server assigns `conv_` + 32 hex chars and sets **`is_new_conversation`: true**. If you send a non-blank id, **`is_new_conversation`** is **false**.

**Where you see it:** JSON response (or first SSE `request_id` event). Every **structured log** line also carries **`conversation_id`** and **`is_new_conversation`**.

## Gateways (outbound design)

This app calls **two HTTP gateways**. Both receive the same **conversation** headers whenever an effective id exists:

| Gateway | Call | Headers (thread) |
|---------|------|-------------------|
| **Inference** | `POST {LLM_GATEWAY_BASE_URL}/…/v1/chat/completions` | `X-Conversation-Id`, `X-Is-New-Conversation` (with `X-Request-Id`, `X-Session-Id`, `X-Trace-Id` when provided) |
| **RAG** | `POST {RAG_HTTP_BASE_URL}/v1/rag/query` | Same thread headers; **plus** `conversation_id` in the JSON body |

So: **one rule for all gateways** — thread id and new-thread flag ride on **`X-Conversation-Id`** / **`X-Is-New-Conversation`**; RAG additionally mirrors **`conversation_id`** in the payload for services that prefer body fields.

**More detail:** [schema-request-response.md](schema-request-response.md) · [gateway-inference.md](gateway-inference.md) · [rag-query.md](rag-query.md)
