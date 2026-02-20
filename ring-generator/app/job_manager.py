"""
Async job manager for the ring generation pipeline.

Provides:
  - Bounded work queue with configurable concurrency
  - Per-job progress tracking (compatible with Temporal polling)
  - TTL-based cleanup of completed job records
  - Thread-safe submit / get / cancel / wait operations
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .config import RingGenSettings
from .core.pipeline import generate_ring
from .schemas import GenerateJobStatus, GenerateRequest, GenerateResult, JobRecordView

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class JobRecord:
    id: str
    request: GenerateRequest
    status: GenerateJobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: int = 0
    detail: str = ""
    result: GenerateResult | None = None
    error: dict[str, Any] | None = None
    done_event: asyncio.Event = field(default_factory=asyncio.Event)

    def as_view(self) -> JobRecordView:
        return JobRecordView(
            id=self.id,
            status=self.status,
            created_at=self.created_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
            progress=self.progress,
            detail=self.detail,
            request_summary={
                "prompt": (self.request.prompt or "")[:100],
                "llm_name": self.request.llm_name,
                "has_image": bool(self.request.image_b64),
            },
            result=self.result,
            error=self.error,
        )


class GenerateJobManager:
    def __init__(self, settings: RingGenSettings, system_prompt: str):
        self.settings = settings
        self.system_prompt = system_prompt
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.max_queue_size)
        self.jobs: dict[str, JobRecord] = {}
        self._workers: list[asyncio.Task] = []
        self._cleanup_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def startup(self) -> None:
        worker_count = self.settings.max_concurrent_jobs
        for idx in range(worker_count):
            self._workers.append(
                asyncio.create_task(self._worker_loop(idx), name=f"ring-gen-worker-{idx}")
            )
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(), name="ring-gen-cleanup")
        logger.info("ring_gen_job_manager_started workers=%s", worker_count)

    async def shutdown(self) -> None:
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        if self._cleanup_task:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
            self._cleanup_task = None

    async def submit(self, request: GenerateRequest, job_id: str | None = None) -> JobRecord:
        async with self._lock:
            if self.queue.full():
                raise RuntimeError("Job queue is full, retry later")

            _id = job_id or request.request_id or str(uuid.uuid4())
            if _id in self.jobs:
                raise RuntimeError(f"Duplicate job_id: {_id}")

            record = JobRecord(
                id=_id,
                request=request,
                status=GenerateJobStatus.queued,
                created_at=_utc_now(),
            )
            self.jobs[_id] = record
            self.queue.put_nowait(_id)
            return record

    async def wait_for_completion(self, job_id: str, timeout_seconds: int) -> JobRecord:
        record = await self.get(job_id)
        try:
            await asyncio.wait_for(record.done_event.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            raise RuntimeError(f"Job '{job_id}' did not finish within {timeout_seconds}s")
        return await self.get(job_id)

    async def get(self, job_id: str) -> JobRecord:
        record = self.jobs.get(job_id)
        if not record:
            raise KeyError(f"Job not found: {job_id}")
        return record

    async def cancel(self, job_id: str) -> JobRecord:
        record = await self.get(job_id)
        if record.status == GenerateJobStatus.queued:
            record.status = GenerateJobStatus.cancelled
            record.finished_at = _utc_now()
            record.done_event.set()
            return record
        if record.status in {
            GenerateJobStatus.succeeded,
            GenerateJobStatus.failed,
            GenerateJobStatus.cancelled,
        }:
            return record
        raise RuntimeError("Running jobs cannot be force-cancelled safely")

    def _make_progress_callback(self, record: JobRecord) -> Callable[[str, int, int], None]:
        import time
        _llm_start = [0.0]

        def _cb(stage: str, attempt: int, max_attempts: int) -> None:
            if stage == "llm_started":
                _llm_start[0] = time.time()
                record.progress = 5
                record.detail = "LLM generating Blender code (streaming)..."
            elif stage == "llm_done":
                elapsed = time.time() - _llm_start[0] if _llm_start[0] else 0
                record.progress = 18
                record.detail = f"LLM done ({elapsed:.1f}s). Preparing Blender..."
            elif stage == "blender":
                record.progress = 20 + int(60 * (attempt - 1) / max(max_attempts, 1))
                record.detail = f"Running Blender (attempt {attempt}/{max_attempts})"
            elif stage == "fixing":
                record.progress = 20 + int(60 * (attempt - 1) / max(max_attempts, 1))
                record.detail = f"Attempt {attempt} failed, asking LLM to fix..."
            else:
                record.detail = stage
        return _cb

    async def _worker_loop(self, idx: int) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                record = self.jobs.get(job_id)
                if not record or record.status == GenerateJobStatus.cancelled:
                    continue

                record.status = GenerateJobStatus.running
                record.started_at = _utc_now()
                record.progress = 5
                record.detail = "Starting pipeline..."

                try:
                    result = await generate_ring(
                        request=record.request,
                        system_prompt=self.system_prompt,
                        sessions_dir=self.settings.sessions_dir,
                        blender_executable=str(self.settings.blender_executable),
                        blender_timeout=self.settings.blender_timeout_seconds,
                        anthropic_api_key=self.settings.anthropic_api_key,
                        gemini_api_key=self.settings.gemini_api_key,
                        gemini_model=self.settings.gemini_model,
                        max_retries=self.settings.max_error_retries,
                        max_cost_usd=self.settings.max_cost_per_request_usd,
                        progress_callback=self._make_progress_callback(record),
                    )
                    record.result = result
                    if result.success:
                        record.status = GenerateJobStatus.succeeded
                        record.progress = 100
                        record.detail = "Generation complete"
                    else:
                        record.status = GenerateJobStatus.failed
                        record.error = {
                            "message": "Ring generation failed after all retries",
                            "status_code": 500,
                        }
                        record.progress = 100
                        record.detail = "Failed after retries"

                except Exception as exc:
                    record.status = GenerateJobStatus.failed
                    record.error = {"message": str(exc), "status_code": 500}
                    record.progress = 100
                    record.detail = f"Error: {str(exc)[:200]}"
                    logger.exception("Worker %d: job %s failed", idx, job_id)

                finally:
                    record.finished_at = _utc_now()
                    record.done_event.set()

            finally:
                self.queue.task_done()

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.cleanup_interval_seconds)
            now = _utc_now()
            ttl = timedelta(seconds=self.settings.finished_job_ttl_seconds)

            expired = [
                jid
                for jid, job in self.jobs.items()
                if job.status in {
                    GenerateJobStatus.succeeded,
                    GenerateJobStatus.failed,
                    GenerateJobStatus.cancelled,
                }
                and job.finished_at
                and now - job.finished_at > ttl
            ]
            for jid in expired:
                self.jobs.pop(jid, None)

            completed_ids = [
                jid
                for jid, job in self.jobs.items()
                if job.status in {
                    GenerateJobStatus.succeeded,
                    GenerateJobStatus.failed,
                    GenerateJobStatus.cancelled,
                }
            ]
            overflow = max(0, len(completed_ids) - self.settings.max_job_records)
            if overflow > 0:
                completed_sorted = sorted(
                    completed_ids,
                    key=lambda i: self.jobs[i].finished_at or self.jobs[i].created_at,
                )
                for jid in completed_sorted[:overflow]:
                    self.jobs.pop(jid, None)
