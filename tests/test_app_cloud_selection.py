from io import BytesIO

import app as app_module


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


def _fake_result(selection):
    return {
        "app": "ui-selection-test",
        "environment": "production",
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

    def fake_deploy(config):
        captured.append(config)
        return _fake_result(config["selection"])

    monkeypatch.setattr(app_module, "deploy_app", fake_deploy)
    app_module.app.config["TESTING"] = True

    response = _post_deploy(app_module.app.test_client(), YAML_WITH_MANUAL_AZURE, "yaml")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "manual", "provider": "Azure"}


def test_auto_dropdown_override_sets_selection_mode_auto(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config: captured.append(config) or _fake_result(config["selection"]))
    app_module.app.config["TESTING"] = True

    response = _post_deploy(app_module.app.test_client(), YAML_WITH_MANUAL_AZURE, "auto")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "auto"}


def test_aws_dropdown_override_sets_manual_aws(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config: captured.append(config) or _fake_result(config["selection"]))
    app_module.app.config["TESTING"] = True

    response = _post_deploy(app_module.app.test_client(), YAML_WITHOUT_SELECTION, "AWS")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "manual", "provider": "AWS"}


def test_azure_dropdown_override_sets_manual_azure(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config: captured.append(config) or _fake_result(config["selection"]))
    app_module.app.config["TESTING"] = True

    response = _post_deploy(app_module.app.test_client(), YAML_WITHOUT_SELECTION, "Azure")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "manual", "provider": "Azure"}


def test_gcp_dropdown_override_sets_manual_gcp(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config: captured.append(config) or _fake_result(config["selection"]))
    app_module.app.config["TESTING"] = True

    response = _post_deploy(app_module.app.test_client(), YAML_WITHOUT_SELECTION, "GCP")

    assert response.status_code == 200
    assert captured[0]["selection"] == {"mode": "manual", "provider": "GCP"}


def test_existing_yaml_manual_selection_still_works_with_yaml_option(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config: captured.append(config) or _fake_result(config["selection"]))
    app_module.app.config["TESTING"] = True

    response = _post_deploy(app_module.app.test_client(), YAML_WITH_MANUAL_AZURE, "yaml")

    assert response.status_code == 200
    assert captured[0]["selection"]["mode"] == "manual"
    assert captured[0]["selection"]["provider"] == "Azure"
