"""
Async job manager for the ring validation pipeline.

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
from typing import Any, Callable

from .config import ValidatorSettings
from .core.validation_pipeline import validate_ring
from .schemas import ValidateJobStatus, ValidateRequest, ValidateResult, JobRecordView

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class JobRecord:
    id: str
    request: ValidateRequest
    status: ValidateJobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: int = 0
    detail: str = ""
    result: ValidateResult | None = None
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
                "llm_name": self.request.llm_name,
                "num_screenshots": len(self.request.screenshots),
                "has_code": bool(self.request.code),
                "session_id": self.request.session_id,
            },
            result=self.result,
            error=self.error,
        )


class ValidateJobManager:
    def __init__(self, settings: ValidatorSettings, master_prompt: str):
        self.settings = settings
        self.master_prompt = master_prompt
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.max_queue_size)
        self.jobs: dict[str, JobRecord] = {}
        self._workers: list[asyncio.Task] = []
        self._cleanup_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def startup(self) -> None:
        worker_count = self.settings.max_concurrent_jobs
        for idx in range(worker_count):
            self._workers.append(
                asyncio.create_task(self._worker_loop(idx), name=f"ring-val-worker-{idx}")
            )
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(), name="ring-val-cleanup")
        logger.info("ring_val_job_manager_started workers=%s", worker_count)

    async def shutdown(self) -> None:
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        if self._cleanup_task:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
            self._cleanup_task = None

    async def submit(self, request: ValidateRequest, job_id: str | None = None) -> JobRecord:
        async with self._lock:
            if self.queue.full():
                raise RuntimeError("Job queue is full, retry later")

            _id = job_id or request.request_id or str(uuid.uuid4())
            if _id in self.jobs:
                raise RuntimeError(f"Duplicate job_id: {_id}")

            record = JobRecord(
                id=_id,
                request=request,
                status=ValidateJobStatus.queued,
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
        if record.status == ValidateJobStatus.queued:
            record.status = ValidateJobStatus.cancelled
            record.finished_at = _utc_now()
            record.done_event.set()
            return record
        if record.status in {
            ValidateJobStatus.succeeded,
            ValidateJobStatus.failed,
            ValidateJobStatus.cancelled,
        }:
            return record
        raise RuntimeError("Running jobs cannot be force-cancelled safely")

    def _make_progress_callback(self, record: JobRecord) -> Callable[[str, int], None]:
        def _cb(stage: str, pct: int) -> None:
            record.progress = pct
            record.detail = stage
        return _cb

    async def _worker_loop(self, idx: int) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                record = self.jobs.get(job_id)
                if not record or record.status == ValidateJobStatus.cancelled:
                    continue

                record.status = ValidateJobStatus.running
                record.started_at = _utc_now()
                record.progress = 5
                record.detail = "Starting validation pipeline..."

                try:
                    result = await validate_ring(
                        request=record.request,
                        master_prompt=self.master_prompt,
                        sessions_dir=self.settings.sessions_dir,
                        blender_executable=str(self.settings.blender_executable),
                        blender_timeout=self.settings.blender_timeout_seconds,
                        anthropic_api_key=self.settings.anthropic_api_key,
                        gemini_api_key=self.settings.gemini_api_key,
                        gemini_model=self.settings.gemini_model,
                        progress_callback=self._make_progress_callback(record),
                    )
                    record.result = result
                    record.status = ValidateJobStatus.succeeded
                    record.progress = 100
                    record.detail = (
                        "Validation complete — regenerated" if result.regenerated
                        else "Validation complete"
                    )

                except Exception as exc:
                    record.status = ValidateJobStatus.failed
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
                    ValidateJobStatus.succeeded,
                    ValidateJobStatus.failed,
                    ValidateJobStatus.cancelled,
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
                    ValidateJobStatus.succeeded,
                    ValidateJobStatus.failed,
                    ValidateJobStatus.cancelled,
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
