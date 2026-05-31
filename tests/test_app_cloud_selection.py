from io import BytesIO

import app as app_module
from models import DeploymentRecord, User
from queue_utils import QueueResult


YAML_WITH_MANUAL_AZURE = b"""
app:
  name: ui-selection-test
  environment: production
selection:
  mode: manual
  provider: Azure
deployment:
  type: container
  image: nginx:latest
  port: 80
requirements:
  max_monthly_cost_usd: 20
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
"""


YAML_WITHOUT_SELECTION = b"""
app:
  name: ui-selection-test
  environment: production
deployment:
  type: container
  image: nginx:latest
  port: 80
requirements:
  max_monthly_cost_usd: 20
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
"""


def _login_client():
    client = app_module.app.test_client()
    client.post(
        "/register",
        data={"name": "Tester", "email": "tester@example.com", "password": "secret123"},
    )
    return client


def _post_deploy(client, yaml_bytes, cloud_selection):
    return client.post(
        "/deploy",
        data={
            "config_file": (BytesIO(yaml_bytes), "config.yaml"),
            "cloud_selection": cloud_selection,
        },
        content_type="multipart/form-data",
    )


def _fake_result(selection, status="dry_run"):
    return {
        "app": "ui-selection-test",
        "app_type": "api",
        "image": "nginx:latest",
        "environment": "production",
        "status": status,
        "deployment_mode": "real" if status == "approval_required" else "dry_run",
        "validation_errors": [],
        "warnings": [],
        "decision": {
            "selection_mode": selection.get("mode", "auto"),
            "manual_provider": selection.get("provider"),
            "recommended_provider": "GCP",
            "selected_provider": selection.get("provider") or "GCP",
            "execution_provider": selection.get("provider") or "GCP",
            "reason": "test",
            "evaluated_providers": [],
        },
        "provider_readiness": {"ready": True, "checks": [], "missing": [], "warnings": []},
        "docker_image_validation": {"valid": True, "errors": [], "warnings": [], "check_type": "syntax_only"},
        "bootstrap_plan": {},
        "approval": {"app_name": "ui-selection-test"} if status == "approval_required" else {},
        "diagnostics": {},
        "deployment": {"status": status, "message": "test"},
        "deployment_steps": [],
        "generated_commands": [],
        "public_endpoints": [],
        "health_check": {"result": "skipped", "status": "skipped", "message": "test"},
    }


def test_use_yaml_selection_preserves_yaml_selection_block(monkeypatch):
    captured = []

    def fake_deploy(config, **kwargs):
        captured.append(config)
        return _fake_result(config["selection"])

    monkeypatch.setattr(app_module, "deploy_app", fake_deploy)
    response = _post_deploy(_login_client(), YAML_WITH_MANUAL_AZURE, "yaml")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "manual", "provider": "Azure"}


def test_auto_dropdown_override_sets_selection_mode_auto(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: captured.append(config) or _fake_result(config["selection"]))

    response = _post_deploy(_login_client(), YAML_WITH_MANUAL_AZURE, "auto")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "auto"}


def test_aws_dropdown_override_sets_manual_aws(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: captured.append(config) or _fake_result(config["selection"]))

    response = _post_deploy(_login_client(), YAML_WITHOUT_SELECTION, "AWS")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "manual", "provider": "AWS"}


def test_azure_dropdown_override_sets_manual_azure(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: captured.append(config) or _fake_result(config["selection"]))

    response = _post_deploy(_login_client(), YAML_WITHOUT_SELECTION, "Azure")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "manual", "provider": "Azure"}


def test_gcp_dropdown_override_sets_manual_gcp(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: captured.append(config) or _fake_result(config["selection"]))

    response = _post_deploy(_login_client(), YAML_WITHOUT_SELECTION, "GCP")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "manual", "provider": "GCP"}


def test_existing_yaml_manual_selection_still_works_with_yaml_option(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: captured.append(config) or _fake_result(config["selection"]))

    response = _post_deploy(_login_client(), YAML_WITH_MANUAL_AZURE, "yaml")

    assert response.status_code == 200
    assert captured[0]["selection"]["mode"] == "manual"
    assert captured[0]["selection"]["provider"] == "Azure"


def test_confirm_real_deployment_route_is_post_only_and_uses_saved_yaml(monkeypatch):
    captured = []

    def fake_deploy(config, **kwargs):
        captured.append((config, kwargs))
        return _fake_result(config["selection"])

    monkeypatch.setattr(app_module, "deploy_app", fake_deploy)
    monkeypatch.setattr(app_module, "enqueue_deployment", lambda deployment_id: QueueResult(True, "job-1", "queued"))
    client = _login_client()
    with app_module.app.app_context():
        user = User.query.filter_by(email="tester@example.com").first()
        record = DeploymentRecord(
            user_id=user.id,
            yaml_content=YAML_WITH_MANUAL_AZURE.decode("utf-8"),
            result_json=_fake_result({"mode": "manual", "provider": "Azure"}, "approval_required"),
        )
        record.apply_result(record.result_json, yaml_content=record.yaml_content)
        app_module.db.session.add(record)
        app_module.db.session.commit()
        record_id = record.id

    assert client.get(f"/deployments/{record_id}/confirm").status_code == 405
    response = client.post(
        f"/deployments/{record_id}/confirm",
        data={"billing_acknowledgement": "yes"},
    )

    assert response.status_code == 200
    assert b"queued" in response.data
    assert captured[0][0]["selection"] == {"mode": "manual", "provider": "Azure"}
    assert captured[0][1]["confirm_real_deployment"] is True
    assert captured[0][1]["execute"] is False
