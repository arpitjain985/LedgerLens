"""
Manages background job lifecycle: create -> update progress -> complete/fail.

Used by the upload router to run PDF parsing + classification + anomaly
detection in the background while the client polls for status, instead of
blocking the HTTP request (this directly addresses Section 4's "can take
several minutes or fail during processing" problem).
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Job

logger = logging.getLogger(__name__)


def create_job(db: Session, job_type: str, statement_id: Optional[str] = None) -> Job:
    job = Job(job_type=job_type, statement_id=statement_id, status="queued", progress_percent=0)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_progress(db: Session, job_id: str, percent: int, message: str) -> None:
    job = db.get(Job, job_id)
    if not job:
        # Not a normal case -- if this fires, the caller is writing to a
        # different database than the one the job was created in (this
        # exact bug was found and fixed in the Phase 2 test fixtures, where
        # the background task and the request handler were pointed at two
        # different DBs). Log it loudly rather than silently continuing.
        logger.warning("update_progress: job %s not found -- possible DB session mismatch", job_id)
        return
    job.status = "processing"
    job.progress_percent = percent
    job.progress_message = message
    job.updated_at = datetime.utcnow()
    db.commit()


def mark_completed(db: Session, job_id: str, statement_id: Optional[str] = None) -> None:
    job = db.get(Job, job_id)
    if not job:
        logger.warning("mark_completed: job %s not found -- possible DB session mismatch", job_id)
        return
    job.status = "completed"
    job.progress_percent = 100
    job.progress_message = "Completed"
    if statement_id:
        job.statement_id = statement_id
    job.completed_at = datetime.utcnow()
    job.updated_at = datetime.utcnow()
    db.commit()


def mark_failed(db: Session, job_id: str, user_message: str, detail: str = "") -> None:
    job = db.get(Job, job_id)
    if not job:
        logger.warning("mark_failed: job %s not found -- possible DB session mismatch", job_id)
        return
    job.status = "failed"
    job.error_message = user_message
    job.error_detail = detail
    job.updated_at = datetime.utcnow()
    db.commit()
