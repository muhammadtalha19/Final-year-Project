from io import BytesIO

import app as app_module
from models import DeploymentRecord, User


VALID_YAML = """
app:
  name: billing-api
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


def _login_client(email="billing@example.com"):
    client = app_module.app.test_client()
    client.post("/register", data={"name": "Billing", "email": email, "password": "secret123"})
    with app_module.app.app_context():
        user = User.query.filter_by(email=email).first()
        user_id = user.id
    return client, user_id


def _result(status="approval_required", cost=15.0):
    return {
        "app": "billing-api",
        "app_type": "api",
        "image": "dockertalha19/fyp-books-api:latest",
        "environment": "production",
        "status": status,
        "deployment_mode": "real",
        "decision": {
            "selection_mode": "manual",
            "manual_provider": "Azure",
            "selected_provider": "Azure",
            "execution_provider": "Azure",
            "reason": "test",
            "evaluated_providers": [
                {
                    "provider": "Azure",
                    "eligible": True,
                    "estimated_cost_usd": cost,
                    "uptime_percent": 99.9,
                    "score": 10,
                }
            ],
        },
        "provider_readiness": {"ready": True, "checks": [], "missing": [], "warnings": []},
        "docker_image_validation": {"valid": True, "errors": [], "warnings": [], "check_type": "syntax_only"},
        "approval": {"app_name": "billing-api"},
        "deployment": {"provider": "Azure", "status": status, "message": "test"},
        "generated_commands": [],
        "public_endpoints": [],
        "health_check": {"result": "skipped", "status": "skipped", "message": "test"},
    }


def _create_record(user_id, status="approval_required", cost=15.0):
    with app_module.app.app_context():
        result = _result(status=status, cost=cost)
        record = DeploymentRecord(user_id=user_id, yaml_content=VALID_YAML, result_json=result)
        record.apply_result(result, yaml_content=VALID_YAML)
        app_module.db.session.add(record)
        app_module.db.session.commit()
        return record.id


def _post_confirm(client, record_id, acknowledged=True):
    data = {"billing_acknowledgement": "yes"} if acknowledged else {}
    return client.post(f"/deployments/{record_id}/confirm", data=data)


def test_real_deploy_blocked_without_billing_acknowledgement(monkeypatch):
    client, user_id = _login_client()
    record_id = _create_record(user_id)
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: _result(status="execution_skipped"))

    response = _post_confirm(client, record_id, acknowledged=False)

    assert response.status_code == 200
    with app_module.app.app_context():
        record = DeploymentRecord.query.get(record_id)
        assert record.status == "blocked_by_billing_ack"


def test_real_deploy_blocked_by_active_quota(monkeypatch):
    client, user_id = _login_client("active-quota@example.com")
    _create_record(user_id, status="deployed")
    record_id = _create_record(user_id)
    monkeypatch.setitem(app_module.app.config, "MAX_ACTIVE_DEPLOYMENTS_PER_USER", 1)
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: _result(status="execution_skipped"))

    response = _post_confirm(client, record_id, acknowledged=True)

    assert response.status_code == 200
    with app_module.app.app_context():
        record = DeploymentRecord.query.get(record_id)
        assert record.status == "blocked_by_quota"


def test_real_deploy_blocked_by_daily_quota(monkeypatch):
    client, user_id = _login_client("daily-quota@example.com")
    _create_record(user_id, status="deployed")
    record_id = _create_record(user_id)
    monkeypatch.setitem(app_module.app.config, "MAX_ACTIVE_DEPLOYMENTS_PER_USER", 5)
    monkeypatch.setitem(app_module.app.config, "MAX_REAL_DEPLOYMENTS_PER_DAY", 1)
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: _result(status="execution_skipped"))

    response = _post_confirm(client, record_id, acknowledged=True)

    assert response.status_code == 200
    with app_module.app.app_context():
        record = DeploymentRecord.query.get(record_id)
        assert record.status == "blocked_by_quota"


def test_real_deploy_blocked_by_platform_cost_limit(monkeypatch):
    client, user_id = _login_client("cost-limit@example.com")
    record_id = _create_record(user_id)
    monkeypatch.setitem(app_module.app.config, "MAX_MONTHLY_COST_LIMIT_USD", 10)
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: _result(status="execution_skipped", cost=15))

    response = _post_confirm(client, record_id, acknowledged=True)

    assert response.status_code == 200
    with app_module.app.app_context():
        record = DeploymentRecord.query.get(record_id)
        assert record.status == "blocked_by_cost_limit"


def test_dry_run_does_not_require_billing_acknowledgement(monkeypatch):
    client, _ = _login_client("dry-run-billing@example.com")
    dry_run = _result(status="dry_run")
    dry_run["deployment_mode"] = "dry_run"
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: dry_run)

    response = client.post(
        "/deploy",
        data={"config_file": (BytesIO(VALID_YAML.encode("utf-8")), "config.yaml"), "cloud_selection": "yaml"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert b"dry_run" in response.data


def test_deleted_deployments_do_not_count_as_active():
    _, user_id = _login_client("active-cleanup@example.com")
    deployed_id = _create_record(user_id, status="deployed")
    _create_record(user_id, status="deleted")

    with app_module.app.app_context():
        assert app_module._deployment_quota_snapshot(user_id)["active_count"] == 1
        record = DeploymentRecord.query.get(deployed_id)
        record.status = "deleted"
        app_module.db.session.commit()
        assert app_module._deployment_quota_snapshot(user_id)["active_count"] == 0
