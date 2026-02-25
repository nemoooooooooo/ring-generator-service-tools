# Ring Editor Service (Tool 4)

Standalone FastAPI microservice for editing existing 3D rings (edit / regen-part / add-part), designed to run both:

- as an independent service, and
- as a Temporal tool inside `temporal-agentic-pipeline`.

It receives the current ring's Blender Python code, modifies it via LLM based on the requested operation, re-renders via Blender with auto-retry, and returns an updated GLB file.

---

## What This Service Does

- Accepts existing ring code + an edit instruction.
- Supports **3 operations**:
  - **`edit`** — Modify the existing ring (full or smart/targeted edit).
  - **`regen-part`** — Completely rebuild one module (e.g. the band or prongs).
  - **`add-part`** — Add a brand-new component to the ring.
- Calls selected LLM (`claude`, `claude-sonnet`, `claude-opus`, `gemini`) to generate modified Blender Python code.
- Runs Blender headless to export GLB.
- On Blender errors, retries with LLM-assisted code fixing (spatial report included).
- Accepts optional `spatial_report` from the validated ring to give the LLM geometry context.
- Tracks token/cost usage and retry logs.
- Stores per-session artifacts (`model.glb`, `session.json`) in `data/sessions/<session_id>/`.
- Exposes both sync (`/run`) and async (`/jobs`) execution contracts for orchestration compatibility.

---

## The 3 Operations

### 1. `edit` — Modify Existing Ring

Edit the ring by providing a natural language instruction. Optionally target a specific module for a "smart edit" that only changes one function.

| Field | Required | Description |
|---|---|---|
| `edit_instruction` | Yes | What to change (e.g. "make the band thicker") |
| `target_module` | No | If set, only this function is modified (smart edit) |

**Example:** "Make the prongs thinner and more elegant" targeting `build_head_and_prongs`.

### 2. `regen-part` — Rebuild a Module

Completely rewrite one `build_*` function from scratch. All other functions remain byte-for-byte identical.

| Field | Required | Description |
|---|---|---|
| `target_module` | Yes | Which function to rebuild (e.g. `build_shank`) |
| `part_description` | No | Description of desired result |

**Example:** Regen `build_refined_shank_with_channel` with "twisted rope-style band with micro-pave diamonds".

### 3. `add-part` — Add New Component

Add a brand-new `build_*` function to the ring. All existing functions remain untouched.

| Field | Required | Description |
|---|---|---|
| `part_description` | Yes | What new part to add |

**Example:** "Add a second thin decorative band with milgrain edge below the main band".

---

## Repo Layout

```text
app/
  main.py                 # FastAPI app + routes
  config.py               # Settings and env parsing
  schemas.py              # API request/response models
  job_manager.py          # Bounded queue + workers + TTL cleanup
  core/
    edit_pipeline.py      # End-to-end edit orchestration
    llm_client.py         # Claude/Gemini adapters
    blender_runner.py     # Headless Blender execution
    prompt_builder.py     # Edit/regen/add/fix prompt builders
    code_processor.py     # Code extraction + module splice helpers
shared/
  payloads.py             # Temporal-style envelope unwrap
  artifact_uploader.py    # Azure CAS upload
  files.py                # File helpers
  logging.py              # Logging setup
prompts/
  master_prompt.txt       # Core system prompt
  part_regen_prompt.txt   # Part regeneration template
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
cd ring-generator-service-tools/ring-editor
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
- `RING_EDIT_BLENDER_EXECUTABLE` (if Blender is not on PATH)

### 3) Run service

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8004
```

Open:

- Swagger: `http://127.0.0.1:8004/docs`
- Health: `http://127.0.0.1:8004/health`

---

## API Usage

### 1) Sync execution (`POST /run`)

#### Edit operation (smart edit targeting one module)

```bash
curl -X POST http://127.0.0.1:8004/run \
  -H "Content-Type: application/json" \
  -d '{
    "operation": "edit",
    "code": "<current blender python code>",
    "modules": ["clean_scene", "build_shank", "build_head", "build_ring"],
    "spatial_report": "<spatial report from validator/generator>",
    "edit_instruction": "Make the band thicker and add a comfort fit",
    "target_module": "build_shank",
    "llm_name": "gemini"
  }'
```

#### Regen-part operation

```bash
curl -X POST http://127.0.0.1:8004/run \
  -H "Content-Type: application/json" \
  -d '{
    "operation": "regen-part",
    "code": "<current blender python code>",
    "modules": ["clean_scene", "build_shank", "build_head", "build_ring"],
    "spatial_report": "<spatial report>",
    "target_module": "build_shank",
    "part_description": "Gorgeous twisted rope-style band with micro-pave diamonds",
    "llm_name": "gemini"
  }'
```

#### Add-part operation

```bash
curl -X POST http://127.0.0.1:8004/run \
  -H "Content-Type: application/json" \
  -d '{
    "operation": "add-part",
    "code": "<current blender python code>",
    "modules": ["clean_scene", "build_shank", "build_head", "build_ring"],
    "spatial_report": "<spatial report>",
    "part_description": "A thin decorative band with milgrain edge below the main band",
    "llm_name": "gemini"
  }'
```

#### Temporal-style envelope payload

```bash
curl -X POST http://127.0.0.1:8004/run \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "operation": "edit",
      "code": "...",
      "edit_instruction": "make the band wider"
    },
    "meta": {
      "trace_id": "abc123"
    }
  }'
```

### 2) Async execution (`POST /jobs`)

#### Submit

```bash
curl -X POST http://127.0.0.1:8004/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "operation": "regen-part",
    "code": "<code>",
    "target_module": "build_head_and_prongs",
    "part_description": "6-prong tiffany setting",
    "llm_name": "gemini"
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
curl http://127.0.0.1:8004/jobs/<job_id>
```

#### Poll result

```bash
curl http://127.0.0.1:8004/jobs/<job_id>/result
```

Returns one of:

- `{"status":"queued","progress":...}`
- `{"status":"running","progress":...,"detail":"..."}`
- `{"status":"succeeded","result":{...}}`
- `{"status":"failed","error":"...","result":...}`
- `{"status":"cancelled"}`

#### Cancel queued job

```bash
curl -X DELETE http://127.0.0.1:8004/jobs/<job_id>
```

### 3) Session artifacts

- GLB: `GET /sessions/{session_id}/model.glb`
- Metadata: `GET /sessions/{session_id}`

---

## Request Schema

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `operation` | `"edit"` / `"regen-part"` / `"add-part"` | Yes | — | Which operation to perform |
| `code` | string | Yes | — | Current Blender Python code |
| `modules` | list[string] | No | `[]` | Current module names |
| `spatial_report` | string | No | `""` | Spatial report from validated ring (geometry context for LLM) |
| `edit_instruction` | string | Required for `edit` | `""` | What to change |
| `target_module` | string | Required for `regen-part` | `""` | Which `build_*` function to target |
| `part_description` | string | Required for `add-part` | `""` | Description of new part |
| `llm_name` | string | No | `"gemini"` | LLM to use: `claude`, `claude-sonnet`, `claude-opus`, `gemini` |
| `session_id` | string | No | auto-generated | Session ID for tracking |
| `current_version` | int | No | `1` | Current version number |
| `max_retries` | int | No | from config | Max Blender retry attempts |
| `max_cost_usd` | float | No | from config | Cost budget cap |

## Response Schema

| Field | Type | Description |
|---|---|---|
| `success` | bool | Whether the operation succeeded |
| `session_id` | string | Session ID |
| `glb_path` | object | CAS artifact ref or local path |
| `code` | string | Updated Blender Python code |
| `modules` | list[string] | Updated module list |
| `operation` | string | Which operation was performed |
| `description` | string | Human-readable summary |
| `version` | int | New version number |
| `spatial_report` | string | Blender spatial report of the new ring |
| `retry_log` | list | Retry attempt details |
| `needs_validation` | bool | Whether the result should go through ring-validator |
| `cost_summary` | object | Token counts, cost breakdown |
| `llm_used` | string | Which LLM model was used |
| `blender_elapsed` | float | Blender execution time (seconds) |
| `glb_size` | int | GLB file size (bytes) |

---

## Core Configuration

Environment variables (prefix `RING_EDIT_`):

- `RING_EDIT_HOST` (default `0.0.0.0`)
- `RING_EDIT_PORT` (default `8004`)
- `RING_EDIT_LOG_LEVEL` (default `INFO`)
- `RING_EDIT_BLENDER_EXECUTABLE` (optional, auto-detected if absent)
- `RING_EDIT_BLENDER_TIMEOUT_SECONDS` (default `300`)
- `RING_EDIT_MAX_ERROR_RETRIES` (default `3`)
- `RING_EDIT_MAX_COST_PER_REQUEST_USD` (default `5.0`)
- `RING_EDIT_MAX_CONCURRENT_JOBS` (default auto: up to 4)
- `RING_EDIT_MAX_QUEUE_SIZE` (default `64`)
- `RING_EDIT_SYNC_WAIT_TIMEOUT_SECONDS` (default `600`)
- `RING_EDIT_FINISHED_JOB_TTL_SECONDS` (default `3600`)
- `RING_EDIT_API_KEY` (optional service-level API key)

Non-prefixed keys used directly by settings:

- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `BLENDER_PATH` / `BLENDER_EXEC` (fallback aliases)

---

## Docker Deployment

The included Dockerfile installs Blender 5.0 and runs the app on port `8004`.

### Build

```bash
docker build -t ring-editor-service:latest .
```

### Run

```bash
docker run --rm -p 8004:8004 \
  --env-file .env \
  -v "$(pwd)/data:/service/data" \
  ring-editor-service:latest
```

---

## Pipeline Position

In the full ring pipeline, ring-editor sits after validation:

```
ring-generator (8102)  →  ring-screenshotter (8002)  →  ring-validator (8003)
                                                              │
                                                              ▼
                                                        ring-editor (8004)
                                                              │
                                                              ▼
                                                  ring-screenshotter → ring-validator
                                                        (re-validate edited ring)
```

The Temporal DAG orchestrates which service to call. The ring-editor is stateless — it receives all needed state (`code`, `modules`, `spatial_report`) in the request and returns the updated result.

---

## Security Notes

- Do not commit real API keys in `.env`.
- If keys were exposed accidentally, rotate them immediately.
- For exposed deployments, set `RING_EDIT_API_KEY` and route through an authenticated gateway.
