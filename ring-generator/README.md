# Ring Generator Service (Tool 1)

Standalone FastAPI microservice for ring generation (prompt/image -> LLM -> Blender -> GLB), designed to run both:

- as an independent service, and
- as a Temporal tool inside `temporal-agentic-pipeline`.

It preserves the core generation/retry behavior from the original `vibe-designing-3d` flow while adding production-style job queueing, async polling, and operational controls.

---

## What This Service Does

- Accepts text prompt and/or reference image.
- Calls selected LLM (`claude`, `claude-sonnet`, `claude-opus`, `gemini`) to generate Blender Python code.
- Runs Blender headless to export GLB.
- On Blender errors, retries with LLM-assisted code fixing.
- Tracks token/cost usage and retry logs.
- Stores per-session artifacts (`model.glb`, `session.json`, `ring_script.py`) in `data/sessions/<session_id>/`.
- Exposes both sync (`/run`) and async (`/jobs`) execution contracts for orchestration compatibility.

---

## Repo Layout

```text
app/
  main.py                 # FastAPI app + routes
  config.py               # Settings and env parsing
  schemas.py              # API request/response models
  job_manager.py          # Bounded queue + workers + TTL cleanup
  core/
    pipeline.py           # End-to-end generation orchestration
    llm_client.py         # Claude/Gemini adapters
    blender_runner.py     # Headless Blender execution
    prompt_builder.py     # Prompt/fix prompt builders
    code_processor.py     # Code extraction/preprocessing helpers
shared/
  payloads.py             # Temporal-style envelope unwrap
  files.py                # File helpers
  logging.py              # Logging setup
prompts/master_prompt.txt # Core generation system prompt
ui/                       # Browser test console
data/sessions/            # Generated outputs
```

---

## Prerequisites

- Python 3.12+
- Blender executable (5.x recommended)
- At least one LLM provider key:
  - `ANTHROPIC_API_KEY` for Claude
  - `GEMINI_API_KEY` for Gemini
- Linux host with enough CPU/RAM for Blender subprocesses

---

## Local Development

### 1) Install dependencies

```bash
cd /home/nimra/ring-generator-service-tools/ring-generator
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Configure environment

```bash
cp .env.example .env
```

Set at minimum:

- `ANTHROPIC_API_KEY` and/or `GEMINI_API_KEY`
- `RING_GEN_BLENDER_EXECUTABLE` (if Blender is not on PATH)

### 3) Run service

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8102
```

Open:

- Swagger: `http://127.0.0.1:8102/docs`
- Health: `http://127.0.0.1:8102/health`
- Test UI: `http://127.0.0.1:8102/test`

---

## Test UI

The built-in UI (`/test`) supports:

- Standalone sync run (`POST /run`)
- Standalone async run (`POST /jobs` + polling)
- Temporal mode (calls Temporal backend `/run/{workflow}` + `/status/{id}` + `/result/{id}`)
- Raw request/response/result payload inspection
- 3D GLB preview in-browser

---

## API Usage

## 1) Sync execution (`POST /run`)

### Plain payload

```bash
curl -X POST http://127.0.0.1:8102/run \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A vintage art deco ring with channel-set baguette diamonds",
    "llm_name": "claude",
    "max_retries": 3,
    "max_cost_usd": 5.0
  }'
```

### Temporal-style envelope payload

```bash
curl -X POST http://127.0.0.1:8102/run \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "prompt": "A minimal solitaire ring",
      "llm_name": "gemini"
    },
    "meta": {
      "trace_id": "abc123"
    }
  }'
```

If envelope-wrapped, response is wrapped as:

```json
{ "result": { "...": "..." } }
```

## 2) Async execution (`POST /jobs`)

### Submit

```bash
curl -X POST http://127.0.0.1:8102/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A bold signet ring",
    "llm_name": "claude-sonnet"
  }'
```

Response:

```json
{
  "job_id": "....",
  "status": "queued",
  "status_url": "/jobs/<job_id>",
  "result_url": "/jobs/<job_id>/result"
}
```

### Poll status

```bash
curl http://127.0.0.1:8102/jobs/<job_id>
```

### Poll result state machine

```bash
curl http://127.0.0.1:8102/jobs/<job_id>/result
```

Returns one of:

- `{"status":"queued","progress":...}`
- `{"status":"running","progress":...,"detail":"..."}`
- `{"status":"succeeded","result":{...}}`
- `{"status":"failed","error":"...","result":...}`
- `{"status":"cancelled"}`

### Cancel queued job

```bash
curl -X DELETE http://127.0.0.1:8102/jobs/<job_id>
```

Note: running jobs are not force-cancelled for safety.

## 3) Session artifacts

- GLB: `GET /sessions/{session_id}/model.glb`
- Metadata: `GET /sessions/{session_id}`

---

## Core Configuration

Environment variables (prefix `RING_GEN_` unless noted):

- `RING_GEN_HOST` (default `0.0.0.0`)
- `RING_GEN_PORT` (default `8102`)
- `RING_GEN_LOG_LEVEL` (default `INFO`)
- `RING_GEN_BLENDER_EXECUTABLE` (optional, auto-detected if absent)
- `RING_GEN_BLENDER_TIMEOUT_SECONDS` (default `300`)
- `RING_GEN_MAX_ERROR_RETRIES` (default `3`)
- `RING_GEN_MAX_COST_PER_REQUEST_USD` (default `5.0`)
- `RING_GEN_MAX_CONCURRENT_JOBS` (default auto: up to 4)
- `RING_GEN_MAX_QUEUE_SIZE` (default `64`)
- `RING_GEN_SYNC_WAIT_TIMEOUT_SECONDS` (default `600`)
- `RING_GEN_FINISHED_JOB_TTL_SECONDS` (default `3600`)
- `RING_GEN_CLEANUP_INTERVAL_SECONDS` (default `30`)
- `RING_GEN_MAX_JOB_RECORDS` (default `2000`)
- `RING_GEN_API_KEY` (optional service-level API key)

Non-prefixed keys used directly by settings:

- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `BLENDER_PATH` / `BLENDER_EXEC` (fallback aliases)

---

## Docker Deployment

The included Dockerfile installs Blender 5.0 and runs the app on port `8102`.

### Build

```bash
docker build -t ring-generator-service:latest .
```

### Run

```bash
docker run --rm -p 8102:8102 \
  --env-file .env \
  -v "$(pwd)/data:/service/data" \
  ring-generator-service:latest
```

Recommended:

- Mount `/service/data` to persistent storage.
- Pass secrets via runtime env/secret manager, not baked into image.
- Add container healthcheck against `/health`.

---

## Temporal Integration (temporal-agentic-pipeline)

This service is compatible with Temporal's payload envelope and async GPU-style polling activity.

### 1) Add tool in `tools.yaml`

In `temporal-agentic-pipeline/src/resources/tools.yaml`:

```yaml
ring-generate:
  url: http://127.0.0.1:8102
  version: "1.0.0"
  gpu: true
  deterministic: false
  cost_per_call: 50
  input_schema:
    type: object
    properties:
      prompt: { type: string }
      image_b64: { type: string }
      image_mime: { type: string }
      llm_name: { type: string }
      max_retries: { type: integer }
      max_cost_usd: { type: number }
  output_schema:
    type: object
    properties:
      success: { type: boolean }
      session_id: { type: string }
      glb_path: { type: string }
      needs_validation: { type: boolean }
```

### 2) Add DAG in `dags.yaml`

In `temporal-agentic-pipeline/src/resources/dags.yaml`:

```yaml
ring_generate_only:
  - { tool: ring-generate, after: [] }
```

### 3) Restart Temporal API + worker

Important: both planner and registry read YAML at startup. Restart after edits.

```bash
# API
uvicorn src.server:app --reload --port 8000

# Worker (separate terminal)
python -m src.worker
```

### 4) Auth and billing requirements

Temporal backend requires valid auth context. For backend testing use API key flow:

- `X-API-Key: <tenant_api_key>`
- `X-On-Behalf-Of: <external_user_id>`

If `X-On-Behalf-Of` is missing for `/run/{workflow}`, backend returns a billing/user-context error.

### 5) End-to-end curl sequence

```bash
# CONFIG
TEMPORAL_URL="http://127.0.0.1:8000"
ADMIN_SECRET="dev_secret"

# 1) Create tenant (one-time)
TENANT_RESP=$(curl -s -X POST "$TEMPORAL_URL/admin/tenants" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: $ADMIN_SECRET" \
  -d '{"name":"ring-test-tenant"}')
echo "$TENANT_RESP" | python3 -m json.tool
API_KEY=$(echo "$TENANT_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['api_key'])")

# 2) Top up user wallet
curl -s -X POST "$TEMPORAL_URL/credits/topup?user_external_id=testuser1&amount=1000" \
  -H "X-API-Key: $API_KEY" | python3 -m json.tool

# 3) Start workflow
START_RESP=$(curl -s -X POST "$TEMPORAL_URL/run/ring_generate_only" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -H "X-On-Behalf-Of: testuser1" \
  -d '{
    "payload": {
      "prompt": "A vintage art deco ring with channel-set baguette diamonds",
      "llm_name": "claude"
    },
    "return_nodes": ["ring-generate"]
  }')
echo "$START_RESP" | python3 -m json.tool
WF_ID=$(echo "$START_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['workflow_id'])")

# 4) Poll status
curl -s "$TEMPORAL_URL/status/$WF_ID" \
  -H "X-API-Key: $API_KEY" | python3 -m json.tool

# 5) Get final result
curl -s "$TEMPORAL_URL/result/$WF_ID" \
  -H "X-API-Key: $API_KEY" | python3 -m json.tool
```

---

## Operational Notes

- Queue backpressure: if queue is full, submit returns an error (`Job queue is full, retry later`).
- Job retention:
  - completed jobs are removed after TTL (`RING_GEN_FINISHED_JOB_TTL_SECONDS`)
  - additional cap via `RING_GEN_MAX_JOB_RECORDS`
- Cost cap applies per request and can be overridden per payload (`max_cost_usd`).
- `needs_validation` is `false` for Opus-family models (`llm_name` containing `opus`), `true` otherwise.
- `/health` includes readiness signals:
  - Blender binary existence
  - prompt loaded
  - provider key availability
  - queue and active-job stats

---

## Troubleshooting

### `Invalid token format` from Temporal backend

You are sending placeholder/invalid JWT in `Authorization`. Use API key flow (`X-API-Key` + `X-On-Behalf-Of`) for backend testing.

### `Required tools are unavailable or unhealthy`

- Ensure ring service is running on configured URL.
- Verify `http://127.0.0.1:8102/health` returns 200.
- Restart Temporal API/worker after YAML changes.

### Blender not found

Set `RING_GEN_BLENDER_EXECUTABLE` or `BLENDER_PATH` correctly and recheck `/health` (`blender_exists` must be `true`).

### Job stuck in running

- Check service logs for Blender timeout or LLM provider errors.
- Increase `RING_GEN_BLENDER_TIMEOUT_SECONDS` if geometry is complex.
- Confirm queue/worker settings (`RING_GEN_MAX_CONCURRENT_JOBS`) are appropriate for host resources.

---

## Security Notes

- Do not commit real API keys in `.env`.
- If keys were exposed accidentally, rotate them immediately.
- For exposed deployments, set `RING_GEN_API_KEY` and route through an authenticated gateway.

