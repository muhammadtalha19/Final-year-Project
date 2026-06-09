import subprocess

import yaml

import orchestrator
from config_schema import validate_config
from pricing.models import PriceEstimate
from providers.azure_mock import AzureMockProvider
from providers.aws_provider import AWSProvider


def _config(max_cost=20, min_uptime=99.9, public_access=True):
    return validate_config(
        yaml.safe_load(
            f"""
            app:
              name: dry-run-app
              environment: production
            deployment:
              type: container
              image: nginx
              port: 8080
              replicas: 1
            requirements:
              max_monthly_cost_usd: {max_cost}
              min_uptime_percent: {min_uptime}
              preferred_region: asia
              public_access: {str(public_access).lower()}
            """
        )
    )


def _manual_config(provider, max_cost=20, min_uptime=99.9, public_access=True):
    return validate_config(
        yaml.safe_load(
            f"""
            app:
              name: manual-{provider.lower()}-app
              environment: production
            selection:
              mode: manual
              provider: {provider}
            deployment:
              type: container
              image: nginx
              port: 8080
              replicas: 1
            requirements:
              max_monthly_cost_usd: {max_cost}
              min_uptime_percent: {min_uptime}
              preferred_region: asia
              public_access: {str(public_access).lower()}
            """
        )
    )


def _price_estimates(aws=18.0, gcp=12.0, azure=15.0):
    return {
        "AWS": PriceEstimate("AWS", aws, None, "fallback", "test"),
        "GCP": PriceEstimate("GCP", gcp, None, "fallback", "test"),
        "Azure": PriceEstimate("Azure", azure, None, "fallback", "test"),
    }


def test_gcp_selected_generates_gcp_dry_run_command(monkeypatch):
    monkeypatch.setenv("GCP_REGION", "asia-south1")
    monkeypatch.setenv("GCP_PLATFORM", "managed")

    result = orchestrator.deploy_app(_config())
    command = result["generated_commands"][0]["command"]

    assert result["status"] == "dry_run"
    assert result["decision"]["selected_provider"] == "GCP"
    assert result["decision"]["execution_provider"] == "GCP"
    assert command[:4] == ["gcloud", "run", "deploy", "dry-run-app"]
    assert "--image" in command
    assert "nginx" in command
    assert "--allow-unauthenticated" in command
    assert "gcloud run deploy dry-run-app" in result["generated_commands"][0]["command_string"]


def test_azure_selected_generates_azure_dry_run_command(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no az in dry-run")))
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "fyp-rg")
    monkeypatch.setenv("AZURE_CONTAINERAPP_ENV", "fyp-env")
    monkeypatch.setattr(orchestrator, "get_price_estimates", lambda config: _price_estimates(gcp=30.0))

    result = orchestrator.deploy_app(_config())
    command = result["generated_commands"][0]["command"]

    assert result["status"] == "dry_run"
    assert result["decision"]["selected_provider"] == "Azure"
    assert result["decision"]["execution_provider"] == "Azure"
    assert command[:3] == ["az", "containerapp", "create"]
    assert "--resource-group" in command
    assert "fyp-rg" in command
    assert "--environment" in command
    assert "fyp-env" in command
    assert "--ingress" in command
    assert "external" in command


def test_aws_selected_generates_aws_dry_run_plan(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "eu-north-1")
    monkeypatch.setenv("AWS_INSTANCE_TYPE", "t3.micro")
    monkeypatch.setattr(AWSProvider, "_client", lambda self: (_ for _ in ()).throw(AssertionError("no boto3 in dry-run")))

    result = orchestrator.deploy_app(_config(max_cost=20, min_uptime=99.99))
    deployment = result["deployment"]

    assert result["status"] == "dry_run"
    assert result["decision"]["selected_provider"] == "AWS"
    assert result["decision"]["execution_provider"] == "AWS"
    assert deployment["provider"] == "AWS"
    assert deployment["deployment_type"] == "EC2_DOCKER"
    assert deployment["image"] == "nginx"
    assert deployment["port"] == 8080
    assert deployment["region"] == "eu-north-1"
    assert deployment["instance_type"] == "t3.micro"
    assert deployment["status"] == "dry_run"


def test_enable_real_deployment_false_prevents_real_deployment(monkeypatch):
    called = {"deploy": False}

    def fail_if_called(self, config):
        called["deploy"] = True
        raise AssertionError("real AWS deploy should not run in dry-run mode")

    monkeypatch.setenv("ENABLE_REAL_DEPLOYMENT", "false")
    monkeypatch.setattr(AWSProvider, "deploy", fail_if_called)

    result = orchestrator.deploy_app(_config(max_cost=20, min_uptime=99.99))

    assert result["status"] == "dry_run"
    assert result["deployment"]["status"] == "dry_run"
    assert called["deploy"] is False


def test_no_subprocess_or_boto3_call_occurs_in_dry_run(monkeypatch):
    called = {"subprocess": False, "boto3": False}

    def fail_subprocess(*args, **kwargs):
        called["subprocess"] = True
        raise AssertionError("subprocess should not run in dry-run mode")

    def fail_boto3(self):
        called["boto3"] = True
        raise AssertionError("boto3 client should not be created in dry-run mode")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    monkeypatch.setattr(AWSProvider, "_client", fail_boto3)

    result = orchestrator.deploy_app(_config())

    assert result["status"] == "dry_run"
    assert called == {"subprocess": False, "boto3": False}


def test_real_deployment_enabled_without_provider_allow_flag_is_blocked(monkeypatch):
    monkeypatch.setenv("ENABLE_REAL_DEPLOYMENT", "true")
    monkeypatch.setenv("ALLOW_AWS_DEPLOYMENT", "false")
    monkeypatch.setattr(AWSProvider, "deploy", lambda self, config: (_ for _ in ()).throw(AssertionError("blocked")))

    result = orchestrator.deploy_app(_config(max_cost=20, min_uptime=99.99))

    assert result["status"] == "blocked_by_safety_flag"
    assert result["deployment"]["status"] == "blocked_by_safety_flag"


def test_azure_real_deployment_blocked_when_flags_false(monkeypatch):
    monkeypatch.setenv("ENABLE_REAL_DEPLOYMENT", "true")
    monkeypatch.setenv("ALLOW_AZURE_DEPLOYMENT", "false")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("blocked")))

    result = orchestrator.deploy_app(_manual_config("Azure"), confirm_real_deployment=True)

    assert result["status"] == "blocked_by_safety_flag"
    assert result["deployment"]["status"] == "blocked_by_safety_flag"


def test_aws_missing_env_returns_configuration_error_when_deploy_called(monkeypatch):
    for variable in ["AWS_REGION", "AWS_AMI_ID", "AWS_KEY_NAME", "AWS_SECURITY_GROUP_ID", "AWS_SUBNET_ID"]:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(AWSProvider, "_client", lambda self: (_ for _ in ()).throw(AssertionError("boto3 should not be called")))

    result = AWSProvider().deploy(_manual_config("AWS"))

    assert result["status"] == "configuration_error"
    assert set(result["missing_vars"]) == {
        "AWS_REGION",
        "AWS_AMI_ID",
        "AWS_KEY_NAME",
        "AWS_SECURITY_GROUP_ID",
        "AWS_SUBNET_ID",
    }


def test_azure_missing_env_returns_configuration_error_when_deploy_called(monkeypatch):
    for variable in ["AZURE_RESOURCE_GROUP", "AZURE_CONTAINERAPP_ENV", "AZURE_LOCATION"]:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("az should not be called")))

    result = AzureMockProvider().deploy(_manual_config("Azure"))

    assert result["status"] == "configuration_error"
    assert set(result["missing_vars"]) == {
        "AZURE_RESOURCE_GROUP",
        "AZURE_CONTAINERAPP_ENV",
        "AZURE_LOCATION",
    }


def test_azure_deploy_uses_subprocess_argument_list_when_allowed(monkeypatch):
    calls = []

    class Completed:
        stdout = "manual-azure-app.example.azurecontainerapps.io\n"
        stderr = ""

    def fake_run(command, capture_output, text, check):
        calls.append(
            {
                "command": command,
                "capture_output": capture_output,
                "text": text,
                "check": check,
            }
        )
        return Completed()

    monkeypatch.setenv("ENABLE_REAL_DEPLOYMENT", "true")
    monkeypatch.setenv("ALLOW_AZURE_DEPLOYMENT", "true")
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "fyp-rg")
    monkeypatch.setenv("AZURE_CONTAINERAPP_ENV", "fyp-env")
    monkeypatch.setenv("AZURE_LOCATION", "eastus")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        AzureMockProvider,
        "health_check",
        lambda self, result: {"status": "skipped", "passed": None, "message": "mocked"},
    )

    result = orchestrator.deploy_app(_manual_config("Azure"), confirm_real_deployment=True)

    assert result["status"] == "deployed"
    assert calls
    assert isinstance(calls[0]["command"], list)
    assert calls[0]["command"][:3] == ["az", "containerapp", "create"]
    assert calls[0]["capture_output"] is True
    assert calls[0]["text"] is True
    assert calls[0]["check"] is True
    assert result["public_endpoints"][0]["url"] == "https://manual-azure-app.example.azurecontainerapps.io"


def test_gcp_real_mode_not_ready_does_not_run_command(monkeypatch):
    monkeypatch.setenv("ENABLE_REAL_DEPLOYMENT", "true")
    monkeypatch.setenv("ALLOW_GCP_DEPLOYMENT", "true")
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("gcloud should not run")))

    result = orchestrator.deploy_app(_manual_config("GCP"))

    assert result["status"] == "provider_not_ready"
    assert result["deployment"]["provider"] == "GCP"
    assert "not ready" in result["deployment"]["message"]


def test_orchestrator_does_not_generate_plan_when_manual_selection_is_blocked(monkeypatch):
    called = {"plan": False}

    def fail_if_called(self, config):
        called["plan"] = True
        raise AssertionError("plan should not be generated for blocked manual selection")

    monkeypatch.setattr(AWSProvider, "generate_plan", fail_if_called)
    raw = yaml.safe_load(
        """
        app:
          name: blocked-manual
          environment: production
        selection:
          mode: manual
          provider: AWS
        deployment:
          type: container
          image: nginx
          port: 80
        requirements:
          max_monthly_cost_usd: 15
          min_uptime_percent: 99.9
          preferred_region: asia
          public_access: true
        """
    )

    result = orchestrator.deploy_app(validate_config(raw))

    assert result["status"] == "manual_selection_blocked"
    assert result["deployment"]["status"] == "manual_selection_blocked"
    assert result["generated_commands"] == []
    assert called["plan"] is False
