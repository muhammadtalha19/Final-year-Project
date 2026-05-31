from dataclasses import dataclass
from uuid import uuid4

from flask import current_app


@dataclass
class QueueResult:
    queued: bool
    job_id: str = ""
    message: str = ""


def enqueue_deployment(deployment_id: str) -> QueueResult:
    if not current_app.config.get("BACKGROUND_JOBS_ENABLED"):
        return QueueResult(True, f"test-{uuid4().hex}", "Deployment queued in local test/development mode.")

    try:
        from redis import Redis
        from rq import Queue

        from tasks import run_deployment_job

        redis_conn = Redis.from_url(current_app.config["REDIS_URL"])
        job = Queue("deployments", connection=redis_conn).enqueue(run_deployment_job, deployment_id)
        return QueueResult(True, job.id, "Deployment queued for background worker.")
    except Exception as exc:
        return QueueResult(False, "", f"Deployment queue unavailable: {exc}")
