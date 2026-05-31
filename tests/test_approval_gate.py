import yaml

import orchestrator
from config_schema import validate_config
from providers.azure_mock import AzureMockProvider


def _manual_azure_config(image="dockertalha19/fyp-books-api:latest"):
    return validate_config(
        yaml.safe_load(
            f"""
            app:
              name: approval-test
              environment: production
            selection:
              mode: manual
              provider: Azure
            deployment:
              type: container
              image: {image}
              port: 80
            requirements:
              max_monthly_cost_usd: 20
              min_uptime_percent: 99.9
              preferred_region: asia
              public_access: true
            """
        )
    )


def _enable_real_azure(monkeypatch):
    monkeypatch.setenv("ENABLE_REAL_DEPLOYMENT", "true")
    monkeypatch.setenv("ALLOW_AZURE_DEPLOYMENT", "true")
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "fyp-rg")
    monkeypatch.setenv("AZURE_LOCATION", "eastus")
    monkeypatch.setenv("AZURE_CONTAINERAPP_ENV", "fyp-env")


def test_real_azure_deployment_without_confirmation_requires_approval(monkeypatch):
    called = {"deploy": False}
    _enable_real_azure(monkeypatch)

    def fail_if_called(self, config):
        called["deploy"] = True
        raise AssertionError("deploy should wait for approval")

    monkeypatch.setattr(AzureMockProvider, "deploy", fail_if_called)

    result = orchestrator.deploy_app(_manual_azure_config())

    assert result["status"] == "approval_required"
    assert result["deployment"]["status"] == "approval_required"
    assert result["approval"]["required"] is True
    assert called["deploy"] is False


def test_real_azure_deployment_with_confirmation_calls_mocked_deploy(monkeypatch):
    called = {"deploy": False}
    _enable_real_azure(monkeypatch)

    def fake_deploy(self, config):
        called["deploy"] = True
        return {
            "provider": "Azure",
            "status": "deployed",
            "message": "mock deployed",
            "generated_commands": [],
            "service_endpoints": [],
        }

    monkeypatch.setattr(AzureMockProvider, "deploy", fake_deploy)

    result = orchestrator.deploy_app(_manual_azure_config(), confirm_real_deployment=True)

    assert result["status"] == "deployed"
    assert called["deploy"] is True


def test_readiness_failure_blocks_real_deployment_even_with_confirmation(monkeypatch):
    called = {"deploy": False}
    _enable_real_azure(monkeypatch)
    monkeypatch.delenv("AZURE_CONTAINERAPP_ENV", raising=False)

    def fail_if_called(self, config):
        called["deploy"] = True
        raise AssertionError("deploy should not run when readiness fails")

    monkeypatch.setattr(AzureMockProvider, "deploy", fail_if_called)

    result = orchestrator.deploy_app(_manual_azure_config(), confirm_real_deployment=True)

    assert result["status"] == "provider_not_ready"
    assert result["deployment"]["status"] == "provider_not_ready"
    assert "AZURE_CONTAINERAPP_ENV" in result["provider_readiness"]["missing"]
    assert called["deploy"] is False


def test_placeholder_image_blocks_real_deployment(monkeypatch):
    called = {"deploy": False}
    _enable_real_azure(monkeypatch)

    def fail_if_called(self, config):
        called["deploy"] = True
        raise AssertionError("deploy should not run when image validation fails")

    monkeypatch.setattr(AzureMockProvider, "deploy", fail_if_called)

    result = orchestrator.deploy_app(
        _manual_azure_config("YOUR_DOCKERHUB_USERNAME/app:latest"),
        confirm_real_deployment=True,
    )

    assert result["status"] == "image_validation_failed"
    assert result["docker_image_validation"]["valid"] is False
    assert called["deploy"] is False


def test_dry_run_does_not_require_approval(monkeypatch):
    called = {"deploy": False}
    monkeypatch.setenv("ENABLE_REAL_DEPLOYMENT", "false")
    monkeypatch.setenv("ALLOW_AZURE_DEPLOYMENT", "true")

    def fail_if_called(self, config):
        called["deploy"] = True
        raise AssertionError("dry-run should not call deploy")

    monkeypatch.setattr(AzureMockProvider, "deploy", fail_if_called)

    result = orchestrator.deploy_app(_manual_azure_config())

    assert result["status"] == "dry_run"
    assert result["approval"] == {}
    assert called["deploy"] is False
