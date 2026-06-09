from dataclasses import dataclass
import logging
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

from flask import current_app, has_app_context


QUEUE_NAME = "deployments"
logger = logging.getLogger(__name__)


@dataclass
class QueueAvailability:
    available: bool
    message: str = ""
    redis_url_masked: str = ""
    error: str = ""


@dataclass
class QueueResult:
    queued: bool
    job_id: str = ""
    message: str = ""
    error: str = ""

    @property
    def success(self) -> bool:
        return self.queued


def mask_redis_url(redis_url: str) -> str:
    parsed = urlparse(redis_url or "")
    if not parsed.password:
        return redis_url
    netloc = parsed.hostname or ""
    if parsed.username:
        netloc = f"{parsed.username}:***@{netloc}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _redis_url() -> str:
    return current_app.config.get("REDIS_URL", "redis://localhost:6379/0")


def get_redis_connection():
    from redis import Redis

    return Redis.from_url(_redis_url())


def get_deployment_queue():
    from rq import Queue

    redis_conn = get_redis_connection()
    redis_conn.ping()
    return Queue(QUEUE_NAME, connection=redis_conn)


def check_queue_available() -> QueueAvailability:
    redis_url = _redis_url()
    try:
        connection = get_redis_connection()
        connection.ping()
        return QueueAvailability(
            available=True,
            message="Redis is reachable. Deployments can be enqueued; keep worker.py running to process jobs.",
            redis_url_masked=mask_redis_url(redis_url),
        )
    except Exception as exc:
        logger.warning("Redis queue availability check failed: %s", type(exc).__name__)
        return QueueAvailability(
            available=False,
            message="Background queue is not available. Start Redis/Valkey and worker, then try again.",
            redis_url_masked=mask_redis_url(redis_url),
            error=type(exc).__name__,
        )


def get_job_for_deployment(deployment_id: str, job_id: Optional[str] = None):
    try:
        queue = get_deployment_queue()
    except Exception:
        return None

    if job_id:
        job = queue.fetch_job(job_id)
        if job:
            return job

    for job in _iter_known_jobs(queue):
        if _job_matches_deployment(job, deployment_id):
            return job
    return None


def get_queue_diagnostics(deployment_id: Optional[str] = None, job_id: Optional[str] = None) -> dict[str, Any]:
    redis_url = current_app.config.get("REDIS_URL", "")
    diagnostics = {
        "queue_name": QUEUE_NAME,
        "redis_url": mask_redis_url(redis_url),
        "redis_reachable": False,
        "queue_enabled": True,
        "queued_job_count": 0,
        "started_job_count": 0,
        "failed_job_count": 0,
        "finished_job_count": 0,
        "scheduled_job_count": 0,
        "worker_count": 0,
        "job_found": False,
        "job_id": job_id or "",
        "job_status": "",
        "message": "",
    }

    availability = check_queue_available()
    diagnostics["redis_reachable"] = availability.available
    diagnostics["message"] = availability.message
    if not availability.available:
        return diagnostics

    try:
        queue = get_deployment_queue()
        diagnostics["queued_job_count"] = len(queue)
        diagnostics["started_job_count"] = _registry_count(queue, "started")
        diagnostics["failed_job_count"] = _registry_count(queue, "failed")
        diagnostics["finished_job_count"] = _registry_count(queue, "finished")
        diagnostics["scheduled_job_count"] = _registry_count(queue, "scheduled")
        diagnostics["worker_count"] = _worker_count(queue.connection)
        job = get_job_for_deployment(deployment_id or "", job_id=job_id) if (deployment_id or job_id) else None
        if job:
            diagnostics["job_found"] = True
            diagnostics["job_id"] = job.id
            diagnostics["job_status"] = _safe_job_status(job)
        diagnostics["message"] = "Redis is reachable. Worker count is informational only and does not block enqueue."
    except Exception as exc:
        logger.warning("Queue diagnostics failed: %s", type(exc).__name__)
        diagnostics["redis_reachable"] = False
        diagnostics["message"] = "Background queue is not available. Start Redis/Valkey and worker, then try again."
    return diagnostics


def enqueue_deployment(deployment_id: str) -> QueueResult:
    if not current_app.config.get("BACKGROUND_JOBS_ENABLED"):
        if current_app.config.get("TESTING"):
            return QueueResult(True, f"test-{uuid4().hex}", "Deployment queued in local test/development mode.")

    try:
        from tasks import run_deployment_job

        queue = get_deployment_queue()
        job = queue.enqueue(run_deployment_job, deployment_id)
        result = QueueResult(True, job.id, "Deployment queued successfully. Keep worker.py running to process it.")
        _persist_queue_result(deployment_id, result)
        return result
    except Exception as exc:
        logger.warning("Failed to enqueue deployment job: %s", type(exc).__name__)
        result = QueueResult(
            False,
            "",
            "Background queue is not available. Redis/enqueue failed. Start Redis/Valkey and worker, then try again.",
            type(exc).__name__,
        )
        _persist_queue_result(deployment_id, result)
        return result


def _iter_known_jobs(queue):
    registries = []
    try:
        from rq.registry import DeferredJobRegistry, FailedJobRegistry, FinishedJobRegistry, ScheduledJobRegistry, StartedJobRegistry

        registries = [
            StartedJobRegistry(queue=queue),
            FailedJobRegistry(queue=queue),
            FinishedJobRegistry(queue=queue),
            DeferredJobRegistry(queue=queue),
            ScheduledJobRegistry(queue=queue),
        ]
    except Exception:
        registries = []

    for job in getattr(queue, "jobs", []):
        yield job
    for registry in registries:
        for known_job_id in registry.get_job_ids():
            job = queue.fetch_job(known_job_id)
            if job:
                yield job


def _job_matches_deployment(job, deployment_id: str) -> bool:
    if not deployment_id:
        return False
    return deployment_id in [str(arg) for arg in getattr(job, "args", [])]


def _safe_job_status(job) -> str:
    try:
        status = job.get_status(refresh=True)
    except TypeError:
        status = job.get_status()
    except Exception:
        status = getattr(job, "status", "")
    return str(status or "")


def _registry_count(queue, registry_name: str) -> int:
    try:
        from rq.registry import FailedJobRegistry, FinishedJobRegistry, ScheduledJobRegistry, StartedJobRegistry

        if registry_name == "failed":
            return len(FailedJobRegistry(queue=queue).get_job_ids())
        if registry_name == "started":
            return len(StartedJobRegistry(queue=queue).get_job_ids())
        if registry_name == "finished":
            return len(FinishedJobRegistry(queue=queue).get_job_ids())
        if registry_name == "scheduled":
            return len(ScheduledJobRegistry(queue=queue).get_job_ids())
    except Exception:
        return 0
    return 0


def _worker_count(connection) -> int:
    try:
        from rq import Worker

        return len(Worker.all(connection=connection))
    except Exception:
        return 0


def _persist_queue_result(deployment_id: str, result: QueueResult) -> None:
    if not has_app_context():
        return
    try:
        from datetime import datetime

        from database import db
        from models import DeploymentRecord

        record = db.session.get(DeploymentRecord, deployment_id)
        if not record:
            return
        stored = dict(record.result_json or {})
        stored["status"] = "queued" if result.queued else "queue_unavailable"
        stored.setdefault("deployment", {})["status"] = stored["status"]
        stored["deployment"]["message"] = result.message
        stored["job_id"] = result.job_id
        record.result_json = stored
        record.status = stored["status"]
        record.rq_job_id = result.job_id or None
        record.queued_at = datetime.utcnow() if result.queued else None
        record.last_error = None if result.queued else result.message
        db.session.commit()
    except Exception as exc:
        logger.warning("Could not persist queue result: %s", type(exc).__name__)
