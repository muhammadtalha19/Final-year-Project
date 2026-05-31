from io import BytesIO

import app as app_module
from portal_models import DeploymentRecord, User, db


YAML_WITH_MANUAL_AZURE = b"""
app:
  name: ui-selection-test
  environment: production
selection:
  mode: manual
  provider: Azure
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


YAML_WITHOUT_SELECTION = b"""
app:
  name: ui-selection-test
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


def _post_deploy(client, yaml_bytes, cloud_selection):
    return client.post(
        "/deploy",
        data={
            "config_file": (BytesIO(yaml_bytes), "config.yaml"),
            "cloud_selection": cloud_selection,
        },
        content_type="multipart/form-data",
    )


def _login(client, email="ui@example.com"):
    return client.post(
        "/register",
        data={"name": "UI Tester", "email": email, "password": "secret123"},
        follow_redirects=True,
    )


def _fake_result(selection):
    return {
        "app": "ui-selection-test",
        "environment": "production",
        "app_type": "api",
        "image": "nginx",
        "status": "dry_run",
        "deployment_mode": "dry_run",
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
        "deployment": {"status": "dry_run"},
        "deployment_steps": [],
        "generated_commands": [],
        "public_endpoints": [],
        "health_check": {"status": "skipped", "message": "test"},
    }


def test_use_yaml_selection_preserves_yaml_selection_block(monkeypatch):
    captured = []

    def fake_deploy(config, **kwargs):
        captured.append(config)
        return _fake_result(config["selection"])

    monkeypatch.setattr(app_module, "deploy_app", fake_deploy)
    client = app_module.app.test_client()
    _login(client)

    response = _post_deploy(client, YAML_WITH_MANUAL_AZURE, "yaml")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "manual", "provider": "Azure"}


def test_auto_dropdown_override_sets_selection_mode_auto(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: captured.append(config) or _fake_result(config["selection"]))
    client = app_module.app.test_client()
    _login(client)

    response = _post_deploy(client, YAML_WITH_MANUAL_AZURE, "auto")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "auto"}


def test_aws_dropdown_override_sets_manual_aws(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: captured.append(config) or _fake_result(config["selection"]))
    client = app_module.app.test_client()
    _login(client)

    response = _post_deploy(client, YAML_WITHOUT_SELECTION, "AWS")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "manual", "provider": "AWS"}


def test_azure_dropdown_override_sets_manual_azure(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: captured.append(config) or _fake_result(config["selection"]))
    client = app_module.app.test_client()
    _login(client)

    response = _post_deploy(client, YAML_WITHOUT_SELECTION, "Azure")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "manual", "provider": "Azure"}


def test_gcp_dropdown_override_sets_manual_gcp(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: captured.append(config) or _fake_result(config["selection"]))
    client = app_module.app.test_client()
    _login(client)

    response = _post_deploy(client, YAML_WITHOUT_SELECTION, "GCP")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "manual", "provider": "GCP"}


def test_existing_yaml_manual_selection_still_works_with_yaml_option(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: captured.append(config) or _fake_result(config["selection"]))
    client = app_module.app.test_client()
    _login(client)

    response = _post_deploy(client, YAML_WITH_MANUAL_AZURE, "yaml")

    assert response.status_code == 200
    assert captured[0]["selection"]["mode"] == "manual"
    assert captured[0]["selection"]["provider"] == "Azure"


def test_confirm_real_deployment_route_uses_posted_config_payload(monkeypatch):
    captured = []

    def fake_deploy(config, **kwargs):
        captured.append((config, kwargs))
        return _fake_result(config["selection"])

    monkeypatch.setattr(app_module, "deploy_app", fake_deploy)
    client = app_module.app.test_client()
    _login(client)
    with app_module.app.app_context():
        user = User.query.filter_by(email="ui@example.com").first()
        record = DeploymentRecord(
            user_id=user.id,
            yaml_content=YAML_WITH_MANUAL_AZURE.decode("utf-8"),
            result_json=_fake_result({"mode": "manual", "provider": "Azure"}),
        )
        record.apply_result(record.result_json, yaml_content=record.yaml_content)
        db.session.add(record)
        db.session.commit()
        deployment_id = record.id

    response = client.post(f"/deployments/{deployment_id}/confirm")

    assert response.status_code == 200
    assert captured[0][0]["selection"] == {"mode": "manual", "provider": "Azure"}
    assert captured[0][1]["confirm_real_deployment"] is True
