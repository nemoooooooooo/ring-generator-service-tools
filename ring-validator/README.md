# Ring Validator Service (Tool 3)

Standalone + orchestration-compatible ring validation microservice.

Receives multi-angle screenshots and the Blender Python code that generated a ring, sends them to an LLM (Claude/Gemini) for structural geometry validation, and optionally re-renders with corrected code if defects are found.

## Architecture

```
Screenshots (base64 PNGs) + Code + User Prompt
    │
    ▼
LLM Validation (Claude Opus / Gemini 3 Pro)
    │
    ├─ VALID → Return {is_valid: true}
    │
    └─ INVALID + corrected code
        │
        ▼
      Blender re-render (headless)
        │
        ├─ Success → Return {is_valid: false, regenerated: true, glb_path: "..."}
        └─ Failure → Return {is_valid: true, message: "using original design"}
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/run` | Temporal-compatible sync execution |
| POST | `/jobs` | Async job submission (GPU-style polling) |
| GET | `/jobs/{id}` | Job status (Temporal heartbeat) |
| GET | `/jobs/{id}/result` | Final result |
| DELETE | `/jobs/{id}` | Cancel queued job |
| GET | `/health` | Service health check |
| GET | `/tool/schema` | Tool schema for registry |

## Quick Start

```bash
# Copy environment config
cp .env.example .env
# Edit .env with your API keys

# Copy master_prompt.txt from vibe-designing-3d
cp /path/to/vibe-designing-3d/master_prompt.txt prompts/

# Install dependencies
pip install -r requirements.txt

# Run
python -m app.main
# or
uvicorn app.main:app --host 0.0.0.0 --port 8104
```

## Temporal Integration

Registered as `ring-validate` in `tools.yaml`. Supports:
- Envelope format: `{ "data": {...}, "meta": {...} }`
- Async polling: `POST /jobs` → `GET /jobs/{id}`
- Health check: `GET /health`

## Configuration

All settings use `RING_VAL_` prefix. See `.env.example` for full list.

| Variable | Default | Description |
|----------|---------|-------------|
| `RING_VAL_PORT` | 8104 | Service port |
| `RING_VAL_MAX_CONCURRENT_JOBS` | 2 | Worker pool size |
| `RING_VAL_BLENDER_TIMEOUT_SECONDS` | 300 | Blender re-render timeout |
| `RING_VAL_SYNC_WAIT_TIMEOUT_SECONDS` | 300 | Sync endpoint timeout |
| `ANTHROPIC_API_KEY` | — | Claude API key |
| `GEMINI_API_KEY` | — | Gemini API key |
