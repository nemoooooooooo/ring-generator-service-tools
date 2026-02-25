"""
Async job manager for the ring edit pipeline.

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

from .config import RingEditSettings
from .core.edit_pipeline import edit_ring
from .schemas import EditJobStatus, EditRequest, EditResult, JobRecordView

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class JobRecord:
    id: str
    request: EditRequest
    status: EditJobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: int = 0
    detail: str = ""
    result: EditResult | None = None
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
                "operation": self.request.operation,
                "edit_instruction": (self.request.edit_instruction or "")[:100],
                "target_module": self.request.target_module,
                "part_description": (self.request.part_description or "")[:100],
                "llm_name": self.request.llm_name,
            },
            result=self.result,
            error=self.error,
        )


class EditJobManager:
    def __init__(
        self,
        settings: RingEditSettings,
        system_prompt: str,
        part_regen_template: str,
    ):
        self.settings = settings
        self.system_prompt = system_prompt
        self.part_regen_template = part_regen_template
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.max_queue_size)
        self.jobs: dict[str, JobRecord] = {}
        self._workers: list[asyncio.Task] = []
        self._cleanup_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def startup(self) -> None:
        worker_count = self.settings.max_concurrent_jobs
        for idx in range(worker_count):
            self._workers.append(
                asyncio.create_task(self._worker_loop(idx), name=f"ring-edit-worker-{idx}")
            )
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(), name="ring-edit-cleanup")
        logger.info("ring_edit_job_manager_started workers=%s", worker_count)

    async def shutdown(self) -> None:
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        if self._cleanup_task:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
            self._cleanup_task = None

    async def submit(self, request: EditRequest, job_id: str | None = None) -> JobRecord:
        async with self._lock:
            if self.queue.full():
                raise RuntimeError("Job queue is full, retry later")

            _id = job_id or request.request_id or str(uuid.uuid4())
            if _id in self.jobs:
                raise RuntimeError(f"Duplicate job_id: {_id}")

            record = JobRecord(
                id=_id,
                request=request,
                status=EditJobStatus.queued,
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
        if record.status == EditJobStatus.queued:
            record.status = EditJobStatus.cancelled
            record.finished_at = _utc_now()
            record.done_event.set()
            return record
        if record.status in {
            EditJobStatus.succeeded,
            EditJobStatus.failed,
            EditJobStatus.cancelled,
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
                record.detail = "LLM generating modified code (streaming)..."
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
                if not record or record.status == EditJobStatus.cancelled:
                    continue

                record.status = EditJobStatus.running
                record.started_at = _utc_now()
                record.progress = 5
                record.detail = f"Starting {record.request.operation} pipeline..."

                try:
                    result = await edit_ring(
                        request=record.request,
                        system_prompt=self.system_prompt,
                        part_regen_template=self.part_regen_template,
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
                        record.status = EditJobStatus.succeeded
                        record.progress = 100
                        record.detail = f"{record.request.operation} complete (v{result.version})"
                    else:
                        record.status = EditJobStatus.failed
                        record.error = {
                            "message": f"Ring {record.request.operation} failed after all retries",
                            "status_code": 500,
                        }
                        record.progress = 100
                        record.detail = "Failed after retries"

                except Exception as exc:
                    record.status = EditJobStatus.failed
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
                    EditJobStatus.succeeded,
                    EditJobStatus.failed,
                    EditJobStatus.cancelled,
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
                    EditJobStatus.succeeded,
                    EditJobStatus.failed,
                    EditJobStatus.cancelled,
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
