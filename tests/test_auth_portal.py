from io import BytesIO

import app as app_module
from portal_models import DeploymentRecord, User, db


VALID_YAML = b"""
app:
  name: portal-app
  environment: production
deployment:
  type: container
  image: nginx
  port: 80
requirements:
  max_monthly_cost_usd: 20
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
"""


def _register(client, email="user@example.com", name="User"):
    return client.post(
        "/register",
        data={"name": name, "email": email, "password": "secret123"},
        follow_redirects=True,
    )


def _login(client, email="user@example.com", password="secret123"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _fake_result(status="dry_run", provider="GCP"):
    return {
        "app": "portal-app",
        "app_type": "api",
        "image": "nginx",
        "environment": "production",
        "status": status,
        "deployment_mode": "dry_run" if status == "dry_run" else "real",
        "validation_errors": [],
        "warnings": [],
        "decision": {
            "selection_mode": "manual",
            "manual_provider": provider,
            "recommended_provider": provider,
            "selected_provider": provider,
            "execution_provider": provider,
            "reason": "test",
            "evaluated_providers": [],
        },
        "provider_readiness": {},
        "docker_image_validation": {"valid": True, "check_type": "syntax_only", "checks": []},
        "bootstrap_plan": {},
        "approval": {"required": status == "approval_required", "warning": "confirm"},
        "deployment": {"provider": provider, "status": status},
        "deployment_steps": [],
        "generated_commands": [],
        "public_endpoints": [],
        "health_check": {"result": "skipped", "status": "skipped", "message": "test", "attempts": 0},
        "diagnostics": {},
    }


def _create_record(user_id, app_name):
    result = _fake_result()
    result["app"] = app_name
    record = DeploymentRecord(user_id=user_id, yaml_content=VALID_YAML.decode("utf-8"), result_json=result)
    record.apply_result(result, yaml_content=record.yaml_content)
    db.session.add(record)
    db.session.commit()
    return record.id


def test_register_user_success():
    client = app_module.app.test_client()

    response = _register(client)

    assert response.status_code == 200
    with app_module.app.app_context():
        user = User.query.filter_by(email="user@example.com").first()
        assert user is not None
        assert user.password_hash != "secret123"


def test_duplicate_email_rejected():
    client = app_module.app.test_client()
    _register(client)
    client.get("/logout")

    response = _register(client)

    assert response.status_code == 400
    assert b"already exists" in response.data


def test_login_success_and_failure_and_logout():
    client = app_module.app.test_client()
    _register(client)
    client.get("/logout")

    failed = _login(client, password="wrong")
    assert failed.status_code == 401
    assert b"Invalid email or password" in failed.data

    success = _login(client)
    assert success.status_code == 200
    assert b"Dashboard" in success.data

    logout = client.get("/logout", follow_redirects=True)
    assert logout.status_code == 200
    assert b"Create Account" in logout.data


def test_protected_route_redirects_anonymous_user():
    response = app_module.app.test_client().get("/dashboard")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_user_sees_only_own_deployments():
    client = app_module.app.test_client()
    _register(client, "one@example.com", "One")
    with app_module.app.app_context():
        user_one = User.query.filter_by(email="one@example.com").first()
        user_two = User(name="Two", email="two@example.com", password_hash="hash")
        db.session.add(user_two)
        db.session.commit()
        _create_record(user_one.id, "owned-app")
        _create_record(user_two.id, "other-app")

    response = client.get("/deployments")

    assert b"owned-app" in response.data
    assert b"other-app" not in response.data


def test_user_cannot_view_report_or_delete_another_users_deployment(monkeypatch):
    called = {"cleanup": False}
    client = app_module.app.test_client()
    _register(client, "owner@example.com", "Owner")
    with app_module.app.app_context():
        other = User(name="Other", email="other@example.com", password_hash="hash")
        db.session.add(other)
        db.session.commit()
        other_record_id = _create_record(other.id, "other-app")

    monkeypatch.setattr(
        app_module,
        "cleanup_deployment_record",
        lambda record: called.update(cleanup=True) or {"status": "deleted", "message": "deleted"},
    )

    assert client.get(f"/deployments/{other_record_id}").status_code == 404
    assert client.get(f"/deployment-report/{other_record_id}").status_code == 404
    assert client.post(f"/deployments/{other_record_id}/delete").status_code == 404
    assert called["cleanup"] is False


def test_logged_in_user_can_submit_yaml_and_record_is_saved(monkeypatch):
    captured = []
    client = app_module.app.test_client()
    _register(client)

    def fake_deploy(config, **kwargs):
        captured.append(config)
        return _fake_result(provider=config["selection"]["provider"])

    monkeypatch.setattr(app_module, "deploy_app", fake_deploy)
    response = client.post(
        "/deploy/new",
        data={
            "config_file": (BytesIO(VALID_YAML), "config.yaml"),
            "cloud_selection": "AWS",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "manual", "provider": "AWS"}
    with app_module.app.app_context():
        user = User.query.filter_by(email="user@example.com").first()
        record = DeploymentRecord.query.filter_by(user_id=user.id).first()
        assert record is not None
        assert record.user_id == user.id


def test_approval_required_is_stored_and_confirm_uses_post(monkeypatch):
    calls = []
    client = app_module.app.test_client()
    _register(client)

    def fake_deploy(config, **kwargs):
        calls.append(kwargs)
        return _fake_result(status="approval_required" if not kwargs.get("confirm_real_deployment") else "deployed")

    monkeypatch.setattr(app_module, "deploy_app", fake_deploy)
    response = client.post(
        "/deploy/new",
        data={
            "config_file": (BytesIO(VALID_YAML), "config.yaml"),
            "cloud_selection": "GCP",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    with app_module.app.app_context():
        record = DeploymentRecord.query.first()
        assert record.status == "approval_required"
        deployment_id = record.id

    assert client.get(f"/deployments/{deployment_id}/confirm").status_code == 405
    confirm = client.post(f"/deployments/{deployment_id}/confirm")
    assert confirm.status_code == 200
    assert calls[-1]["confirm_real_deployment"] is True
    with app_module.app.app_context():
        assert db.session.get(DeploymentRecord, deployment_id).status == "deployed"


def test_dashboard_and_detail_pages_return_200():
    client = app_module.app.test_client()
    _register(client)
    with app_module.app.app_context():
        user = User.query.filter_by(email="user@example.com").first()
        deployment_id = _create_record(user.id, "detail-app")

    assert client.get("/dashboard").status_code == 200
    assert client.get("/deployments").status_code == 200
    assert client.get(f"/deployments/{deployment_id}").status_code == 200
