"""Durable rescue-image cleanup worker.

Deletion is intentionally performed only after the source row transaction has
committed.  Leases and a generation fence let another worker reclaim a job
after a crash without an old worker being able to overwrite the newer result.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time

from sqlalchemy import and_, or_, select

from ..config import settings
from ..database import DataSessionLocal
from ..models import data as model_data
from ..features.rescue import storage as rescue_storage

logger = logging.getLogger(__name__)


async def _claim_jobs(owner: str, limit: int = 20) -> list[tuple[int, str, int, str | None]]:
    now = int(time.time())
    lease_until = now + max(10, int(getattr(settings, "FILE_CLEANUP_LEASE_SECONDS", 60)))
    claimed: list[tuple[int, str, int, str | None]] = []
    async with DataSessionLocal() as db:
        query = (
            select(model_data.FileCleanupJob)
            .where(
                or_(
                    and_(model_data.FileCleanupJob.status == "PENDING", model_data.FileCleanupJob.run_after <= now),
                    and_(model_data.FileCleanupJob.status == "RUNNING", model_data.FileCleanupJob.lease_until < now),
                )
            )
            .order_by(model_data.FileCleanupJob.run_after.asc(), model_data.FileCleanupJob.id.asc())
            .limit(limit)
        )
        rows = (await db.execute(query.with_for_update(skip_locked=True))).scalars().all()
        for job in rows:
            job.status = "RUNNING"
            job.attempts = int(job.attempts or 0) + 1
            job.lease_owner = owner
            job.lease_until = lease_until
            job.lease_generation = int(job.lease_generation or 0) + 1
            job.updated_at = now
            claimed.append((int(job.id), owner, int(job.lease_generation), job.image_storage_key))
        if rows:
            await db.commit()
    return claimed


async def _finish_job(job_id: int, owner: str, generation: int, status: str, error_code: str | None = None) -> None:
    now = int(time.time())
    async with DataSessionLocal() as db:
        job = await db.get(model_data.FileCleanupJob, job_id, with_for_update=True)
        if not job or job.lease_owner != owner or int(job.lease_generation or 0) != int(generation):
            return
        if status == "DONE":
            job.status = "DONE"
            job.run_after = now
        else:
            max_attempts = max(1, int(getattr(settings, "FILE_CLEANUP_MAX_ATTEMPTS", 12)))
            if int(job.attempts or 0) >= max_attempts:
                job.status = "FAILED"
                job.run_after = now
            else:
                job.status = "PENDING"
                job.run_after = now + min(3600, 2 ** min(int(job.attempts or 1), 10))
        job.lease_owner = None
        job.lease_until = None
        job.updated_at = now
        job.last_error_code = error_code
        await db.commit()


async def run_file_cleanup_daemon() -> None:
    owner = secrets.token_hex(12)
    interval = max(2.0, float(getattr(settings, "FILE_CLEANUP_INTERVAL_SECONDS", 10.0)))
    while True:
        try:
            jobs = await _claim_jobs(owner)
            for job_id, lease_owner, generation, storage_key in jobs:
                try:
                    path = rescue_storage.resolve_image_path(storage_key or "")
                    if path is not None and path.exists():
                        path.unlink()
                    await _finish_job(job_id, lease_owner, generation, "DONE")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Rescue cleanup job %s deferred: %s", job_id, exc)
                    await _finish_job(job_id, lease_owner, generation, "RETRY", type(exc).__name__)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Rescue cleanup worker degraded: %s", exc)
            await asyncio.sleep(interval)
