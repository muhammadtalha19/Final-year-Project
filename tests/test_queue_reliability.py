from io import BytesIO

import app as app_module
import queue_utils
from models import AuditLog, DeploymentRecord, User
from queue_utils import QueueResult


VALID_YAML = """
app:
  name: queue-api
  environment: production
selection:
  mode: manual
  provider: Azure
deployment:
  type: container
  image: dockertalha19/fyp-books-api:latest
  port: 8000
requirements:
  max_monthly_cost_usd: 30
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
"""


def _register(client, email="queue@example.com"):
    client.post("/register", data={"name": "Queue User", "email": email, "password": "secret123"})
    with app_module.app.app_context():
        return User.query.filter_by(email=email).first().id


def _result(status="approval_required", provider="Azure", deployment_provider=None, mode="real"):
    return {
        "app": "queue-api",
        "app_type": "api",
        "image": "dockertalha19/fyp-books-api:latest",
        "environment": "production",
        "status": status,
        "deployment_mode": mode,
        "billing_acknowledged": status in {"queued", "queue_lost", "failed"},
        "decision": {
            "selection_mode": "manual",
            "manual_provider": provider,
            "recommended_provider": provider,
            "selected_provider": provider,
            "execution_provider": provider,
            "reason": "manual provider selected for test",
            "evaluated_providers": [
                {
                    "provider": provider,
                    "eligible": True,
                    "estimated_cost_usd": 15,
                    "uptime_percent": 99.9,
                    "score": 10,
                }
            ],
        },
        "cloud_account": {"connected": True, "provider": provider, "message": "connected"},
        "provider_readiness": {"ready": True, "checks": [], "missing": [], "warnings": []},
        "docker_image_validation": {"valid": True, "errors": [], "warnings": [], "check_type": "syntax_only"},
        "approval": {"app_name": "queue-api"} if status == "approval_required" else {},
        "deployment": {
            "provider": deployment_provider or provider,
            "status": status,
            "message": "test deployment message",
        },
        "generated_commands": [],
        "public_endpoints": [],
        "health_check": {"result": "skipped", "status": "skipped", "message": "skipped"},
    }


def _create_record(user_id, status="approval_required", provider="Azure", mode="real"):
    result = _result(status=status, provider=provider, mode=mode)
    record = DeploymentRecord(user_id=user_id, yaml_content=VALID_YAML, result_json=result)
    record.apply_result(result, yaml_content=VALID_YAML)
    app_module.db.session.add(record)
    app_module.db.session.commit()
    return record.id


class FakeRedis:
    def ping(self):
        return True


class FakeJob:
    id = "rq-job-1"

    def get_status(self, refresh=True):
        return "queued"


class FakeQueue:
    def __init__(self):
        self.connection = FakeRedis()
        self.jobs = []
        self.enqueued = []

    def __len__(self):
        return 0

    def enqueue(self, task, deployment_id):
        self.enqueued.append((task.__name__, deployment_id))
        return FakeJob()

    def fetch_job(self, job_id):
        return None


def test_queue_name_and_diagnostics_are_safe(monkeypatch):
    assert queue_utils.QUEUE_NAME == "deployments"
    with app_module.app.app_context():
        monkeypatch.setitem(app_module.app.config, "REDIS_URL", "redis://user:secret-password@localhost:6379/0")
        monkeypatch.setitem(app_module.app.config, "BACKGROUND_JOBS_ENABLED", False)
        monkeypatch.setattr(queue_utils, "get_redis_connection", lambda: FakeRedis())
        monkeypatch.setattr(queue_utils, "get_deployment_queue", lambda: FakeQueue())
        monkeypatch.setattr(queue_utils, "_worker_count", lambda connection: 0)
        diagnostics = queue_utils.get_queue_diagnostics()

    assert diagnostics["queue_name"] == "deployments"
    assert diagnostics["redis_reachable"] is True
    assert diagnostics["worker_count"] == 0
    assert "secret-password" not in str(diagnostics)


def test_confirm_enqueues_when_redis_reachable_even_without_visible_worker(monkeypatch):
    client = app_module.app.test_client()
    user_id = _register(client, "reachable-no-worker@example.com")
    with app_module.app.app_context():
        record_id = _create_record(user_id)

    fake_queue = FakeQueue()
    monkeypatch.setitem(app_module.app.config, "TESTING", False)
    monkeypatch.setitem(app_module.app.config, "BACKGROUND_JOBS_ENABLED", False)
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: _result(status="execution_skipped"))
    monkeypatch.setattr(queue_utils, "get_redis_connection", lambda: FakeRedis())
    monkeypatch.setattr(queue_utils, "get_deployment_queue", lambda: fake_queue)
    monkeypatch.setattr(queue_utils, "_worker_count", lambda connection: 0)

    response = client.post(f"/deployments/{record_id}/confirm", data={"billing_acknowledgement": "yes"})

    assert response.status_code == 200
    assert b"QUEUED" in response.data
    with app_module.app.app_context():
        record = app_module.db.session.get(DeploymentRecord, record_id)
        assert record.status == "queued"
        assert record.rq_job_id == "rq-job-1"
        assert record.last_error is None
    assert fake_queue.enqueued == [("run_deployment_job", record_id)]


def test_confirm_enqueue_stores_rq_job_id(monkeypatch):
    client = app_module.app.test_client()
    user_id = _register(client, "store-job@example.com")
    with app_module.app.app_context():
        record_id = _create_record(user_id)

    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: _result(status="execution_skipped"))
    monkeypatch.setattr(app_module, "enqueue_deployment", lambda deployment_id: QueueResult(True, "job-123", "queued"))

    response = client.post(f"/deployments/{record_id}/confirm", data={"billing_acknowledgement": "yes"})

    assert response.status_code == 200
    with app_module.app.app_context():
        record = app_module.db.session.get(DeploymentRecord, record_id)
        assert record.status == "queued"
        assert record.rq_job_id == "job-123"
        assert record.queued_at is not None


def test_missing_redis_blocks_real_deployment_without_queueing(monkeypatch):
    client = app_module.app.test_client()
    user_id = _register(client, "redis-down@example.com")
    with app_module.app.app_context():
        record_id = _create_record(user_id)

    monkeypatch.setitem(app_module.app.config, "TESTING", False)
    monkeypatch.setitem(app_module.app.config, "BACKGROUND_JOBS_ENABLED", True)
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: _result(status="execution_skipped"))
    monkeypatch.setattr(
        queue_utils,
        "get_redis_connection",
        lambda: (_ for _ in ()).throw(ConnectionError("redis down")),
    )
    monkeypatch.setattr(
        app_module,
        "enqueue_deployment",
        lambda deployment_id: (_ for _ in ()).throw(AssertionError("should not enqueue when Redis is unavailable")),
    )

    response = client.post(f"/deployments/{record_id}/confirm", data={"billing_acknowledgement": "yes"})

    assert response.status_code == 200
    assert b"QUEUE UNAVAILABLE" in response.data
    with app_module.app.app_context():
        record = app_module.db.session.get(DeploymentRecord, record_id)
        assert record.status == "queue_unavailable"
        assert not record.rq_job_id


def test_enqueue_exception_sets_queue_unavailable_without_leaking_secrets(monkeypatch, caplog):
    client = app_module.app.test_client()
    user_id = _register(client, "enqueue-fails@example.com")
    with app_module.app.app_context():
        record_id = _create_record(user_id)

    class FailingQueue(FakeQueue):
        def enqueue(self, task, deployment_id):
            raise RuntimeError("redis://user:top-secret@localhost:6379/0")

    monkeypatch.setitem(app_module.app.config, "TESTING", False)
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: _result(status="execution_skipped"))
    monkeypatch.setattr(queue_utils, "get_redis_connection", lambda: FakeRedis())
    monkeypatch.setattr(queue_utils, "get_deployment_queue", lambda: FailingQueue())

    response = client.post(f"/deployments/{record_id}/confirm", data={"billing_acknowledgement": "yes"})

    assert response.status_code == 200
    assert b"QUEUE UNAVAILABLE" in response.data
    assert b"top-secret" not in response.data
    assert "top-secret" not in caplog.text
    with app_module.app.app_context():
        record = app_module.db.session.get(DeploymentRecord, record_id)
        assert record.status == "queue_unavailable"
        assert record.rq_job_id is None
        assert "top-secret" not in (record.last_error or "")


def test_status_endpoint_syncs_missing_job_to_queue_lost(monkeypatch):
    client = app_module.app.test_client()
    user_id = _register(client, "lost-job@example.com")
    with app_module.app.app_context():
        record_id = _create_record(user_id, status="queued")
        record = app_module.db.session.get(DeploymentRecord, record_id)
        record.rq_job_id = "missing-job"
        app_module.db.session.commit()

    monkeypatch.setattr(
        app_module,
        "get_queue_diagnostics",
        lambda *args, **kwargs: {
            "queue_name": "deployments",
            "redis_reachable": True,
            "queued_job_count": 0,
            "failed_job_count": 0,
            "job_found": False,
            "job_id": "missing-job",
            "job_status": "",
            "message": "Background queue is reachable.",
        },
    )

    response = client.get(f"/deployments/{record_id}/status")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "queue_lost"
    assert payload["status_label"] == "QUEUE LOST"
    with app_module.app.app_context():
        record = app_module.db.session.get(DeploymentRecord, record_id)
        assert record.status == "queued"


def test_status_polling_does_not_enqueue_or_mutate_record(monkeypatch):
    client = app_module.app.test_client()
    user_id = _register(client, "poll-readonly@example.com")
    with app_module.app.app_context():
        record_id = _create_record(user_id, status="queued")
        record = app_module.db.session.get(DeploymentRecord, record_id)
        record.rq_job_id = "poll-job"
        app_module.db.session.commit()

    monkeypatch.setattr(
        app_module,
        "enqueue_deployment",
        lambda deployment_id: (_ for _ in ()).throw(AssertionError("status polling must not enqueue")),
    )
    monkeypatch.setattr(
        app_module,
        "get_queue_diagnostics",
        lambda *args, **kwargs: {
            "queue_name": "deployments",
            "redis_reachable": True,
            "queued_job_count": 0,
            "failed_job_count": 0,
            "job_found": False,
            "job_id": "poll-job",
            "job_status": "",
            "message": "Background queue is reachable.",
        },
    )

    response = client.get(f"/deployments/{record_id}/status")

    assert response.status_code == 200
    assert response.get_json()["status"] == "queue_lost"
    with app_module.app.app_context():
        record = app_module.db.session.get(DeploymentRecord, record_id)
        assert record.status == "queued"
        assert record.rq_job_id == "poll-job"


def test_status_endpoint_does_not_show_queue_unavailable_as_queued():
    client = app_module.app.test_client()
    user_id = _register(client, "queue-unavailable-status@example.com")
    with app_module.app.app_context():
        record_id = _create_record(user_id, status="queue_unavailable")

    response = client.get(f"/deployments/{record_id}/status")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "queue_unavailable"
    assert payload["status_label"] == "QUEUE UNAVAILABLE"
    assert payload["public_url"] is None


def test_requeue_is_owner_only_and_records_audit_event(monkeypatch):
    owner_client = app_module.app.test_client()
    owner_id = _register(owner_client, "requeue-owner@example.com")
    other_client = app_module.app.test_client()
    _register(other_client, "requeue-other@example.com")
    with app_module.app.app_context():
        record_id = _create_record(owner_id, status="queue_lost")

    assert other_client.post(f"/deployments/{record_id}/requeue").status_code == 404

    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: _result(status="execution_skipped"))
    monkeypatch.setattr(app_module, "enqueue_deployment", lambda deployment_id: QueueResult(True, "job-new", "queued"))

    response = owner_client.post(f"/deployments/{record_id}/requeue")

    assert response.status_code == 200
    with app_module.app.app_context():
        record = app_module.db.session.get(DeploymentRecord, record_id)
        assert record.status == "queued"
        assert record.rq_job_id == "job-new"
        assert AuditLog.query.filter_by(action="deployment_requeued", entity_id=record_id).first() is not None


def test_requeue_requires_explicit_post():
    client = app_module.app.test_client()
    user_id = _register(client, "requeue-post-only@example.com")
    with app_module.app.app_context():
        record_id = _create_record(user_id, status="queue_lost")

    assert client.get(f"/deployments/{record_id}/requeue").status_code == 405


def test_requeue_does_not_enqueue_when_provider_safety_flag_blocks(monkeypatch):
    client = app_module.app.test_client()
    user_id = _register(client, "requeue-safety@example.com")
    with app_module.app.app_context():
        record_id = _create_record(user_id, status="queue_lost")

    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: _result(status="blocked_by_safety_flag"))
    monkeypatch.setattr(
        app_module,
        "enqueue_deployment",
        lambda deployment_id: (_ for _ in ()).throw(AssertionError("blocked_by_safety_flag must not enqueue")),
    )

    response = client.post(f"/deployments/{record_id}/requeue")

    assert response.status_code == 200
    with app_module.app.app_context():
        record = app_module.db.session.get(DeploymentRecord, record_id)
        assert record.status == "blocked_by_safety_flag"


def test_deployed_and_deleted_records_cannot_be_requeued():
    client = app_module.app.test_client()
    user_id = _register(client, "no-requeue@example.com")
    with app_module.app.app_context():
        deployed_id = _create_record(user_id, status="deployed")
        deleted_id = _create_record(user_id, status="deleted")

    assert client.post(f"/deployments/{deployed_id}/requeue").status_code == 302
    assert client.post(f"/deployments/{deleted_id}/requeue").status_code == 302
    with app_module.app.app_context():
        assert app_module.db.session.get(DeploymentRecord, deployed_id).status == "deployed"
        assert app_module.db.session.get(DeploymentRecord, deleted_id).status == "deleted"


def test_repeated_confirm_does_not_duplicate_jobs(monkeypatch):
    client = app_module.app.test_client()
    user_id = _register(client, "confirm-idempotent@example.com")
    with app_module.app.app_context():
        record_id = _create_record(user_id)

    calls = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: _result(status="execution_skipped"))

    def fake_enqueue(deployment_id):
        calls.append(deployment_id)
        return QueueResult(True, "job-once", "queued")

    monkeypatch.setattr(app_module, "enqueue_deployment", fake_enqueue)

    first = client.post(f"/deployments/{record_id}/confirm", data={"billing_acknowledgement": "yes"})
    second = client.post(f"/deployments/{record_id}/confirm", data={"billing_acknowledgement": "yes"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == [record_id]
    with app_module.app.app_context():
        record = app_module.db.session.get(DeploymentRecord, record_id)
        assert record.status == "queued"
        assert record.rq_job_id == "job-once"


def test_confirm_does_not_enqueue_blocked_deployed_deleted_or_active_records(monkeypatch):
    client = app_module.app.test_client()
    user_id = _register(client, "confirm-guard@example.com")
    with app_module.app.app_context():
        blocked_id = _create_record(user_id, status="blocked_by_safety_flag")
        deployed_id = _create_record(user_id, status="deployed")
        deleted_id = _create_record(user_id, status="deleted")
        queued_id = _create_record(user_id, status="queued")
        running_id = _create_record(user_id, status="running")
        for record_id, job_id in [(queued_id, "queued-job"), (running_id, "running-job")]:
            record = app_module.db.session.get(DeploymentRecord, record_id)
            record.rq_job_id = job_id
        app_module.db.session.commit()

    monkeypatch.setattr(
        app_module,
        "enqueue_deployment",
        lambda deployment_id: (_ for _ in ()).throw(AssertionError("confirm guard should prevent enqueue")),
    )
    monkeypatch.setattr(
        app_module,
        "deploy_app",
        lambda config, **kwargs: (_ for _ in ()).throw(AssertionError("confirm guard should prevent preflight")),
    )

    for record_id in [blocked_id, deployed_id, deleted_id, queued_id, running_id]:
        response = client.post(f"/deployments/{record_id}/confirm", data={"billing_acknowledgement": "yes"})
        assert response.status_code == 200


def test_result_ui_uses_final_provider_over_deployment_metadata():
    client = app_module.app.test_client()
    user_id = _register(client, "provider-ui@example.com")
    result = _result(status="dry_run", provider="Azure", deployment_provider="GCP", mode="dry_run")
    with app_module.app.app_context():
        record = DeploymentRecord(user_id=user_id, yaml_content=VALID_YAML, result_json=result)
        record.apply_result(result, yaml_content=VALID_YAML)
        app_module.db.session.add(record)
        app_module.db.session.commit()
        record_id = record.id

    response = client.get(f"/deployments/{record_id}")

    assert response.status_code == 200
    assert b"<span class=\"label\">Selected Provider</span><strong>Azure</strong>" in response.data
    assert b"<span class=\"label\">Requested</span><strong>Azure</strong>" in response.data


def test_dry_run_works_without_redis(monkeypatch):
    client = app_module.app.test_client()
    _register(client, "dry-without-redis@example.com")
    monkeypatch.setitem(app_module.app.config, "BACKGROUND_JOBS_ENABLED", True)
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: _result(status="dry_run", mode="dry_run"))
    monkeypatch.setattr(
        app_module,
        "get_queue_diagnostics",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry-run should not check Redis")),
    )

    response = client.post(
        "/deploy/new",
        data={"config_file": (BytesIO(VALID_YAML.encode("utf-8")), "config.yaml"), "cloud_selection": "yaml"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert b"DRY RUN" in response.data


def test_worker_and_enqueue_use_deployments_queue():
    import worker

    assert queue_utils.QUEUE_NAME == "deployments"
    assert worker.listen == ["deployments"]
