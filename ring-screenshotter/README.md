# Ring Screenshotter Service (Tool 2)

Standalone FastAPI microservice for multi-angle GLB screenshot rendering via headless Blender, designed to run both:

- as an independent service, and
- as a Temporal tool inside `temporal-agentic-pipeline`.

It replicates the exact screenshot pipeline from the original `vibe-designing-3d` client-side `captureValidationScreenshots()` function, moved server-side with 1:1 visual parity.

---

## What This Service Does

- Accepts a GLB file (local path, HTTP URL, or Azure CAS artifact reference).
- Launches headless Blender with a generated Python script.
- Renders 8 multi-angle screenshots with studio lighting matching the original Three.js scene.
- Returns base64 PNG data URIs (`data:image/png;base64,...`) for each angle.
- Supports both sync (`/run`) and async (`/jobs`) execution contracts for orchestration compatibility.

---

## Visual Parity Notes

The renderer reproduces the exact rendering environment from `vibe-designing-3d/index.html`:

| Parameter | Original (Three.js) | Blender Replica |
|---|---|---|
| Camera FOV | `PerspectiveCamera(30, ...)` | 30° perspective |
| Camera angles | 8 angles: front, back, left, right, top, bottom, angle1, angle2 | Identical positions and lookAt(0,0,0) |
| Model scaling | `2.5 / maxDim`, no re-centering | Same. Blender origin preserved |
| Geometry | `geometry.applyMatrix4(child.matrixWorld)` | `bmesh.transform(obj.matrix_world)` bake |
| Material | `MeshPhysicalMaterial` — color `0xd4d4d8`, metalness 0.85, roughness 0.2, clearcoat 0.15, reflectivity 0.8 | Principled BSDF with matching values |
| Scene lights (persistent) | 5 lights from `setupEnvironment()` including colored bottom-fill and side-rim | All 5 replicated as Sun lamps with correct colors |
| Scene lights (temporary) | 4 lights from `captureValidationScreenshots()` | All 4 replicated |
| Ambient | `AmbientLight(0.6)` + `AmbientLight(0.4)` | World background strength (combined) |
| Tone mapping | `ACESFilmicToneMapping`, exposure 1.2, `SRGBColorSpace` | Filmic view transform, Medium High Contrast, EV +0.263, sRGB display |
| Background | Dark radial gradient (`#1a1a2e` → `#060610`) | Dark world background for camera rays, brighter studio env for reflections |
| HDRI reflections | `studio_small_08_1k.hdr` environment map | Light Path node separation: studio-like reflection environment |
| Render engine | WebGL real-time | EEVEE (64 TAA samples, GTAO enabled) |

---

## Repo Layout

```text
app/
  main.py                 # FastAPI app + routes + static UI mount
  config.py               # Settings and env parsing (RING_SS_ prefix)
  schemas.py              # API request/response models
  job_manager.py          # Bounded queue + workers + TTL cleanup
  core/
    renderer.py           # Blender script generator + render orchestration
shared/
  payloads.py             # Temporal-style envelope unwrap
  files.py                # File helpers (ensure_dir, sha256, safe_name)
  logging.py              # Logging setup
  blender_exec.py         # Blender subprocess execution + async wrapper
  artifact_resolver.py    # CAS/Azure/local file path resolution + caching
scripts/
  render_screenshots.py   # CLI script for standalone Blender testing
ui/                       # Browser test console
data/
  renders/                # Rendered screenshot outputs
  artifact_cache/         # Downloaded CAS artifacts (cached by SHA-256)
```

---

## Prerequisites

- Python 3.12+
- Blender 5.x executable (headless rendering, no GPU required — uses EEVEE CPU)
- Linux host
- For Temporal integration: `AZURE_ACCOUNT_NAME` and `AZURE_ACCOUNT_KEY` to resolve CAS artifacts

---

## Local Development

### 1) Install dependencies

```bash
cd /home/nimra/ring-generator-service-tools/ring-screenshotter
pip install -r requirements.txt
```

Optional but recommended for Azure CAS support:

```bash
pip install azure-storage-blob
```

### 2) Configure environment

```bash
cp .env.example .env
```

Set at minimum:

- `RING_SS_BLENDER_EXECUTABLE` (if Blender is not on PATH)
- For Temporal integration, add to `.env`:
  ```
  AZURE_ACCOUNT_NAME=<your-account>
  AZURE_ACCOUNT_KEY=<your-key>
  ```

### 3) Run service

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8103
```

Open:

- Swagger: `http://127.0.0.1:8103/docs`
- Health: `http://127.0.0.1:8103/health`
- Test UI: `http://127.0.0.1:8103/test`

---

## Test UI

The built-in UI (`/test`) supports:

- GLB file upload or path input
- Standalone sync run (`POST /run`)
- Standalone async run (`POST /jobs` + polling)
- Temporal mode (calls Temporal backend `/run/{workflow}` + `/status/{id}` + `/result/{id}`)
- 8-image screenshot gallery with click-to-enlarge lightbox
- Raw request/response/result payload inspection
- Input/output schema viewer (auto-fetched from `/tool/schema`)

---

## API Usage

### 1) Sync execution (`POST /run`)

#### Plain payload

```bash
curl -X POST http://127.0.0.1:8103/run \
  -H "Content-Type: application/json" \
  -d '{
    "glb_path": "/path/to/model.glb",
    "resolution": 1024
  }'
```

#### Temporal-style envelope payload

```bash
curl -X POST http://127.0.0.1:8103/run \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "glb_path": "/path/to/model.glb",
      "resolution": 512
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

### 2) Async execution (`POST /jobs`)

#### Submit

```bash
curl -X POST http://127.0.0.1:8103/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "glb_path": "/path/to/model.glb",
    "resolution": 1024
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

#### Poll status

```bash
curl http://127.0.0.1:8103/jobs/<job_id>
```

Returns `JobRecordView` with `status`, `progress`, `detail`, `result`.

#### Poll result state machine

```bash
curl http://127.0.0.1:8103/jobs/<job_id>/result
```

Returns one of:

- `{"status":"queued","progress":...}`
- `{"status":"running","progress":...,"detail":"..."}`
- `{"status":"succeeded","result":{...}}`
- `{"status":"failed","error":"...","result":...}`
- `{"status":"cancelled"}`

#### Cancel queued job

```bash
curl -X DELETE http://127.0.0.1:8103/jobs/<job_id>
```

Running jobs are not force-cancelled for safety (Blender subprocess must finish or timeout).

### 3) Upload GLB via test UI

```bash
curl -X POST http://127.0.0.1:8103/upload-glb \
  -F "file=@/path/to/ring.glb"
```

Returns `{"glb_path": "/absolute/path/to/cached/file.glb", "size": 12345}`.

### 4) Health & schema

```bash
curl http://127.0.0.1:8103/health
curl http://127.0.0.1:8103/tool/schema
```

`/health` returns:

```json
{
  "status": "ok",
  "service": "ring-screenshotter-service",
  "queue_size": 0,
  "active_jobs": 0,
  "blender_exists": true,
  "max_concurrent_jobs": 2
}
```

`/tool/schema` returns full Pydantic JSON Schema for both input and output models.

---

## GLB Path Resolution

The `glb_path` field accepts three formats:

| Format | Example | Behavior |
|---|---|---|
| Local path | `/home/nimra/.../model.glb` | Used directly (standalone mode) |
| HTTP(S) URL | `https://example.com/model.glb` | Downloaded and SHA-256 cached |
| Azure CAS dict | `{"uri": "azure://container/blob", "sha256": "..."}` | Resolved to SAS-signed HTTPS URL, downloaded and cached |

When the Temporal pipeline sends a payload, `normalise_payload` converts local paths to Azure CAS references. The artifact resolver handles this transparently — it generates a time-limited SAS token from the Azure account key and downloads the blob.

Cache is stored in `data/artifact_cache/<sha256>.glb`. Subsequent requests for the same hash skip the download entirely.

---

## Core Configuration

Environment variables (prefix `RING_SS_` unless noted):

| Variable | Default | Description |
|---|---|---|
| `RING_SS_HOST` | `0.0.0.0` | Bind address |
| `RING_SS_PORT` | `8103` | Listen port |
| `RING_SS_LOG_LEVEL` | `INFO` | Log level |
| `RING_SS_BLENDER_EXECUTABLE` | auto-detected | Path to Blender binary |
| `RING_SS_BLENDER_TIMEOUT_SECONDS` | `300` | Max seconds per Blender render job |
| `RING_SS_DEFAULT_RESOLUTION` | `1024` | Default screenshot resolution (px) |
| `RING_SS_MAX_CONCURRENT_JOBS` | auto (up to 4) | Parallel Blender worker count |
| `RING_SS_MAX_QUEUE_SIZE` | `64` | Max pending jobs before rejecting |
| `RING_SS_SYNC_WAIT_TIMEOUT_SECONDS` | `180` | Timeout for `/run` sync endpoint |
| `RING_SS_FINISHED_JOB_TTL_SECONDS` | `1800` | Completed job record retention (30 min) |
| `RING_SS_CLEANUP_INTERVAL_SECONDS` | `30` | Cleanup sweep frequency |
| `RING_SS_MAX_JOB_RECORDS` | `2000` | Max completed job records in memory |
| `RING_SS_API_KEY` | none | Optional service-level auth |

Non-prefixed keys (for Azure CAS integration):

| Variable | Default | Description |
|---|---|---|
| `AZURE_ACCOUNT_NAME` | `snapwear` | Azure Storage account name |
| `AZURE_ACCOUNT_KEY` | none | Azure Storage account key (enables SAS-signed downloads) |
| `BLENDER_PATH` / `BLENDER_EXEC` | — | Fallback aliases for Blender path |

---

## Docker Deployment

The included Dockerfile installs Blender 5.0 and runs the app on port `8103`.

### Build

```bash
docker build -t ring-screenshotter-service:latest .
```

### Run

```bash
docker run --rm -p 8103:8103 \
  --env-file .env \
  -v "$(pwd)/data:/service/data" \
  ring-screenshotter-service:latest
```

Recommended:

- Mount `/service/data` to persistent storage (render outputs + artifact cache).
- Pass secrets (`AZURE_ACCOUNT_KEY`, `RING_SS_API_KEY`) via runtime env/secret manager.
- Add container healthcheck against `/health`.

---

## Temporal Integration (temporal-agentic-pipeline)

This service is compatible with Temporal's payload envelope and async GPU-style polling activity (`gpu_job_stream`).

### How it works

1. Temporal's `DynamicWorkflow` routes `ring-screenshot` to `gpu_job_stream` (because `gpu: true` in tools.yaml).
2. `gpu_job_stream` calls `POST /jobs` with the envelope payload.
3. It polls `GET /jobs/{job_id}` until `status` is `succeeded` or `failed`.
4. On success, extracts `result` containing all 8 screenshots as data URIs.
5. `normalise_payload` may CAS-ify the result (uploads large base64 blobs to Azure).

### 1) Tool definition in `tools.yaml`

In `temporal-agentic-pipeline/src/resources/tools.yaml`:

```yaml
ring-screenshot:
  url: http://127.0.0.1:8103
  version: "1.0.0"
  gpu: true
  deterministic: true
  cost_per_call: 5
  input_schema:
    type: object
    properties:
      glb_path: { type: string }
      resolution: { type: integer }
      session_id: { type: string }
  output_schema:
    type: object
    properties:
      success: { type: boolean }
      screenshots:
        type: array
        items:
          type: object
          properties:
            name: { type: string }
            data_uri: { type: string }
      num_angles: { type: integer }
      resolution: { type: integer }
      render_elapsed: { type: number }
      glb_path: { type: string }
```

### 2) DAG definitions in `dags.yaml`

In `temporal-agentic-pipeline/src/resources/dags.yaml`:

```yaml
# Standalone screenshot
ring_screenshot_only:
  - { tool: ring-screenshot, after: [] }

# Chained: generate ring → screenshot
ring_generate_with_screenshots:
  - { tool: ring-generate, after: [] }
  - tool: ring-screenshot
    after: [ring-generate]
    map:
      glb_path: "ring-generate.glb_path"
      session_id: "ring-generate.session_id"
```

The `map` block wires `ring-generate`'s output `glb_path` and `session_id` as input to `ring-screenshot`.

### 3) Restart Temporal API + worker

Both planner and registry read YAML at startup. Restart after edits.

```bash
# API (from temporal-agentic-pipeline/)
.venv/bin/uvicorn src.server:app --host 0.0.0.0 --port 8000

# Worker (separate terminal)
.venv/bin/python -m src.worker
```

### 4) Auth and billing requirements

Temporal backend requires valid auth context. For backend testing use API key flow:

- `X-API-Key: <tenant_api_key>`
- `X-On-Behalf-Of: <external_user_id>`

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

# --- Flow A: Screenshot only (via Temporal) ---

# 3a) Start screenshot-only workflow
START_RESP=$(curl -s -X POST "$TEMPORAL_URL/run/ring_screenshot_only" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -H "X-On-Behalf-Of: testuser1" \
  -d '{
    "payload": {
      "glb_path": "/path/to/model.glb",
      "resolution": 1024
    },
    "return_nodes": ["ring-screenshot"]
  }')
echo "$START_RESP" | python3 -m json.tool
WF_ID=$(echo "$START_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['workflow_id'])")

# 4a) Poll status
sleep 10
curl -s "$TEMPORAL_URL/status/$WF_ID" \
  -H "X-API-Key: $API_KEY" \
  -H "X-On-Behalf-Of: testuser1" | python3 -m json.tool

# 5a) Get result (blocking)
curl -s "$TEMPORAL_URL/result/$WF_ID" \
  -H "X-API-Key: $API_KEY" \
  -H "X-On-Behalf-Of: testuser1" | python3 -m json.tool

# --- Flow B: Generate + Screenshot chain (via Temporal) ---

# 3b) Start chained workflow
START_RESP=$(curl -s -X POST "$TEMPORAL_URL/run/ring_generate_with_screenshots" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -H "X-On-Behalf-Of: testuser1" \
  -d '{
    "payload": {
      "prompt": "A vintage art deco ring with channel-set baguette diamonds",
      "llm_name": "claude",
      "max_retries": 3,
      "max_cost_usd": 5.0
    },
    "return_nodes": ["ring-generate", "ring-screenshot"]
  }')
echo "$START_RESP" | python3 -m json.tool
WF_ID=$(echo "$START_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['workflow_id'])")

# 4b) Poll status (repeat every ~10s)
curl -s "$TEMPORAL_URL/status/$WF_ID" \
  -H "X-API-Key: $API_KEY" \
  -H "X-On-Behalf-Of: testuser1" | python3 -m json.tool

# 5b) Get final result (blocking)
curl -s "$TEMPORAL_URL/result/$WF_ID" \
  -H "X-API-Key: $API_KEY" \
  -H "X-On-Behalf-Of: testuser1" | python3 -m json.tool

# 6) Audit cost breakdown
curl -s "$TEMPORAL_URL/credits/audit/$WF_ID" \
  -H "X-API-Key: $API_KEY" \
  -H "X-On-Behalf-Of: testuser1" | python3 -m json.tool
```

---

## CAS Artifact Flow (Azure Integration)

When running under Temporal, the payload normalization pipeline converts large binary values to Azure Blob CAS references before they reach the tool. This means `glb_path` arrives as:

```json
{
  "uri": "azure://agentic-artifacts/hashed/9e8152e27e73919a82de7773352c1a008a388350a23f42f8435adec7dc8c2552",
  "sha256": "9e8152e27e73919a82de7773352c1a008a388350a23f42f8435adec7dc8c2552",
  "type": "application/octet-stream",
  "bytes": 1726812
}
```

The `artifact_resolver` handles this by:

1. Checking the local cache (`data/artifact_cache/<sha256>.glb`).
2. If miss, converting `azure://container/blob` → `https://{account}.blob.core.windows.net/{container}/{blob}?{sas_token}`.
3. Downloading via HTTPS with a 30-minute SAS token.
4. Verifying SHA-256 integrity.
5. Caching locally for subsequent requests.

The SAS token is generated using `azure-storage-blob` SDK if available, or via a manual HMAC-SHA256 fallback. Both require `AZURE_ACCOUNT_KEY` in the environment.

---

## Concurrency Model

- Workers: `RING_SS_MAX_CONCURRENT_JOBS` Blender subprocesses run in parallel (default: `min(4, cpu_count // 2)`).
- Queue: `RING_SS_MAX_QUEUE_SIZE` pending jobs buffered (default: 64). Exceeding this rejects with "Job queue is full".
- Each Blender render runs in a separate subprocess offloaded to a thread pool (doesn't block the async event loop).
- Job records live in memory with TTL-based cleanup every `RING_SS_CLEANUP_INTERVAL_SECONDS`.
- Temporal's `gpu_job_stream` heartbeats are served by `GET /jobs/{id}` which returns `progress` and `status` fields.

---

## Operational Notes

- Queue backpressure: if queue is full, submit returns error (`Job queue is full, retry later`).
- Job retention: completed jobs removed after `RING_SS_FINISHED_JOB_TTL_SECONDS` (default 30 min), capped at `RING_SS_MAX_JOB_RECORDS`.
- Each render produces 8 PNG files at the configured resolution. At 1024px, each screenshot is ~600-800KB as base64 data URI. Total response payload is ~6-7MB.
- The `deterministic: true` flag in tools.yaml means Temporal will cache results for identical inputs (same `glb_path` hash + resolution). Repeated calls with the same GLB skip the render entirely.
- Rendered files are stored in `data/renders/render_<id>/` and not automatically cleaned up (only job records are TTL'd). Add a cron or extend cleanup for disk management.
- `/health` includes readiness signals: Blender existence, queue stats, active jobs, max concurrency.

---

## Troubleshooting

### `Request URL has an unsupported protocol 'azure://'`

The `AZURE_ACCOUNT_NAME` and `AZURE_ACCOUNT_KEY` environment variables are missing from the screenshotter's `.env`. These are required for the artifact resolver to generate signed download URLs when receiving CAS references from Temporal.

### `Invalid token format` from Temporal backend

You are sending a placeholder JWT. Use API key flow (`X-API-Key` + `X-On-Behalf-Of`) for backend testing.

### `Required tools are unavailable or unhealthy`

- Ensure screenshotter is running on port 8103.
- Verify `http://127.0.0.1:8103/health` returns 200 with `blender_exists: true`.
- Restart Temporal API and worker after YAML changes.

### Blender not found

Set `RING_SS_BLENDER_EXECUTABLE` or `BLENDER_PATH` correctly. Recheck `/health` — `blender_exists` must be `true`.

### Blender timeout

- Default timeout is 300s. Increase `RING_SS_BLENDER_TIMEOUT_SECONDS` for very complex models.
- EEVEE renders 8 screenshots at 1024px in ~3-5s for typical ring models. Timeouts suggest Blender failed to import the GLB or a script error.

### Screenshots look wrong

- Verify the GLB file is valid (try opening in Blender GUI).
- The renderer expects mesh objects in the GLB. Empty scenes or non-mesh objects (cameras, lights) are filtered out.
- Check render logs in `data/renders/render_<id>/` — the generated `render_script.py` and Blender stdout/stderr are preserved.

### Job stuck in running

- Check service logs for Blender subprocess timeouts.
- Running jobs cannot be cancelled via API (Blender subprocess must finish or timeout).
- If stuck permanently, restart the service — all in-memory job records are lost.

---

## Security Notes

- Do not commit `AZURE_ACCOUNT_KEY` or `RING_SS_API_KEY` to version control.
- The `.env` file is gitignored. Use `.env.example` as a template.
- For exposed deployments, always set `RING_SS_API_KEY` and route through an authenticated gateway.
- SAS tokens generated by the artifact resolver expire after 30 minutes and are read-only.
