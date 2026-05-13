# layer-gateway-inference-v1

🚀 GPU-Aware Routing Gateway for vLLM (k3s)

A lightweight FastAPI-based gateway that provides request-level, GPU-aware routing for vLLM inference running on a k3s multi-GPU cluster.

This project upgrades default Kubernetes Service routing (connection-level, random) into a smart, load-aware routing layer optimized for LLM inference.

🧠 Why this exists

Kubernetes Services provide:

connection-level load balancing

But GPU inference (vLLM) needs:

request-level + load-aware routing

Without this, you get:

uneven GPU utilization
bursty traffic (wave patterns)
higher p95/p99 latency
inefficient batching
🏗️ Architecture
Client
  ↓
FastAPI Gateway (this project)
  ├─ auth / validation
  ├─ load-aware routing
  ├─ retry + timeout
  ├─ circuit breaker
  └─ metrics
  ↓
Backend Pool (vLLM pods)
  ├─ gpu-node-1
  └─ gpu-node-2
  ↓
vLLM
  └─ continuous batching → GPU execution
⚙️ Key Features
✅ Request-level routing
Avoids Kubernetes connection stickiness
Distributes traffic per request (not per TCP connection)
✅ Load-aware scheduling

Routes to backend with lowest:

inflight requests
queue latency
TTFT (time-to-first-token)
error rate
✅ Circuit breaker
isolates failing GPU nodes
prevents cascading latency
✅ Retry & timeout
safe retry on transient failure
avoids hanging requests
✅ Backend health tracking
passive (errors, latency)
optional active (/health)
✅ Works with vLLM batching
does NOT replace batching
improves which backend receives requests
🔥 Routing Strategy

Each backend is scored:

score =
  inflight * 10
+ queue_p95_ms / 50
+ ttft_p95_ms / 50
+ error_rate * 100

Gateway selects:

lowest score backend
📊 Why better than k3s Service
Feature	k3s Service	This Gateway
Routing level	Connection	Request
Load awareness	❌ None	✅ Yes
GPU-aware	❌ No	✅ Yes
Retry	❌ No	✅ Yes
Circuit breaker	❌ No	✅ Yes
Latency optimization	❌ No	✅ Yes
🧩 Example Flow
Request arrives
   ↓
Classify (chat / embed / large)
   ↓
Filter healthy backends
   ↓
Compute score
   ↓
Select best backend
   ↓
Proxy request → vLLM
   ↓
Update metrics
📦 Backend Config

Example:

backends:
  - name: gpu-node-1
    url: http://192.168.86.173:30080
  - name: gpu-node-2
    url: http://192.168.86.176:30080
🧪 Running
1. Start vLLM on each GPU node
vllm serve Qwen/Qwen2.5-7B-Instruct \
  --host 0.0.0.0 \
  --port 8000 \
  --gpu-memory-utilization 0.7 \
  --max-num-seqs 32
2. Build a local virtualenv and install the gateway (on the host where you run it)
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

The gateway writes **structured JSON** (one object per line) to **standard output**. In Kubernetes, a log agent such as **Grafana Alloy** (often as a DaemonSet) can tail pod logs and forward them to **Loki** without any in-process Loki client. Optional `LOG_TIMEZONE` (IANA name, default `America/New_York`) controls the `ts` field; values `EST` / `EDT` are treated as US Eastern. Slim images ship the zone database via the `tzdata` dependency; see `.env.example`.

Optional overload fallback is supported via `openai_fallback` in `config.yaml` (model defaults to `gpt-4o-mini`). When enabled, set `OPENAI_API_KEY` in `.env`.

3. Run gateway
uvicorn app.main:app --host 0.0.0.0 --port 8010
4. Set gateway URL
export GATEWAY_URL="http://192.168.86.179:8010"
5. Send request
curl "$GATEWAY_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "messages": [{"role":"user","content":"Hello"}]
  }'

With correlation headers:

```bash
curl -sS "$GATEWAY_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: smoke-req-1" \
  -H "X-Trace-Id: smoke-trace-1" \
  -H "X-Session-Id: smoke-session-1" \
  -d '{
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "messages": [{"role":"user","content":"hello from smoke test"}],
    "max_tokens": 32
  }'
```

Optional JSON field **`conversation_id`**: thread id for the chat; omitted or blank values get a generated `conv_…` id. See [docs/conversation-id.md](docs/conversation-id.md).

If you see **504** with `connect` / *connection attempts failed*, the gateway could not reach the URLs in `config.yaml`. This repo expects two NodePort (or equivalent) endpoints, e.g. `http://192.168.86.173:30080` and `http://192.168.86.176:30080` — adjust to your LAN. Verify with `curl -sS http://192.168.86.173:30080/v1/models` (and the second node).

## Docker

Build and run locally (ensure **backend URLs** in the mounted `config.yaml` reach vLLM from inside the container — use the same LAN NodePort URLs as on the host, e.g. `http://192.168.86.173:30080`, not `127.0.0.1` unless the model server listens on the bridge.)

```bash
docker build -t layer-gateway-inference-v1 .
docker run --rm -p 8010:8010 \
  -v "$(pwd)/config.yaml:/app/config.yaml:ro" \
  --env-file .env \
  layer-gateway-inference-v1
```

You can pass **`.env`** for optional vars such as `LOG_TIMEZONE` or `ENV` (see `.env.example`). Omit `--env-file .env` if the defaults are enough.

Or with Compose:

```bash
docker compose up -d --build
```

Uncomment the `volumes` entry in `docker-compose.yml` when you need a host-specific `config.yaml`.

### Pull and run from Docker Hub

On the target host, keep a **`config.yaml`** (backend NodePort URLs, etc.) in the directory you run from, and optionally **`.env`**, then:

```bash
ssh tb@192.168.86.179
sudo docker pull taixingbi/layer-gateway-inference-v1:latest
sudo docker rm -f gateway-inference
sudo docker run -d --restart unless-stopped \
  --name gateway-inference \
  -p 8010:8010 \
  -v "$(pwd)/config.yaml:/app/config.yaml:ro" \
  --env-file .env \
  taixingbi/layer-gateway-inference-v1:latest
```

### test with k3s

Moved to `docs/smoke-test.md` under **6) k3s smoke examples**.

### CI: publish to Docker Hub on `main`

Same pattern as [layer-gateway-embed-v1](https://github.com/taixingbi/layer-gateway-embed-v1): workflow `.github/workflows/docker-push.yml` runs on every push to **`main`** (and manual **workflow_dispatch**). Add repository secrets **`DOCKERHUB_USERNAME`** and **`DOCKERHUB_TOKEN`**. Images are tagged `latest` and `${{ github.sha }}`.

⚡ Performance Benefits

Compared to default k3s routing:

↓ p95 latency (10–30%)
↑ GPU utilization
↓ queue spikes
smoother throughput (no “wave pattern”)
better batching efficiency
🧠 Design Principles
1. Separate responsibilities
Kubernetes → scheduling & lifecycle
Gateway → routing decisions
vLLM → batching & GPU execution
2. Keep gateway lightweight
no heavy queue (unless needed)
no duplication of vLLM batching
only routing intelligence
3. Optimize for GPU, not CPU

Routing decisions consider:

queue pressure
KV cache pressure
request size
🔮 Future Improvements
🔁 dynamic backend discovery via Kubernetes API
📊 Prometheus + Grafana integration
🧠 GPU utilization–aware routing
🧵 session affinity (chat continuity)
☁️ hybrid routing (local GPU + cloud fallback)
🧪 A/B testing / canary routing

