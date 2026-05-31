import yaml

from config_schema import validate_config
from provider_readiness import check_provider_readiness


def _config(provider="AWS"):
    return validate_config(
        yaml.safe_load(
            f"""
            app:
              name: readiness-test
              environment: production
            selection:
              mode: manual
              provider: {provider}
            deployment:
              type: container
              image: dockertalha19/fyp-books-api:latest
              port: 8080
            requirements:
              max_monthly_cost_usd: 30
              min_uptime_percent: 99.9
              preferred_region: asia
              public_access: true
            """
        )
    )


def test_aws_readiness_missing_aws_vars_returns_not_ready(monkeypatch):
    for variable in [
        "AWS_REGION",
        "AWS_AMI_ID",
        "AWS_KEY_NAME",
        "AWS_SECURITY_GROUP_ID",
        "AWS_SUBNET_ID",
        "AWS_PROFILE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    ]:
        monkeypatch.delenv(variable, raising=False)

    result = check_provider_readiness("AWS", _config("AWS"))

    assert result["provider"] == "AWS"
    assert result["ready"] is False
    assert {"AWS_REGION", "AWS_AMI_ID", "AWS_KEY_NAME", "AWS_SECURITY_GROUP_ID", "AWS_SUBNET_ID"}.issubset(
        set(result["missing"])
    )


def test_aws_readiness_with_vars_returns_ready(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_AMI_ID", "ami-test")
    monkeypatch.setenv("AWS_KEY_NAME", "fyp-key")
    monkeypatch.setenv("AWS_SECURITY_GROUP_ID", "sg-test")
    monkeypatch.setenv("AWS_SUBNET_ID", "subnet-test")
    monkeypatch.setenv("AWS_PROFILE", "default")

    result = check_provider_readiness("AWS", _config("AWS"))

    assert result["ready"] is True
    assert result["missing"] == []


def test_azure_readiness_missing_container_env_returns_not_ready(monkeypatch):
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "fyp-rg")
    monkeypatch.setenv("AZURE_LOCATION", "eastus")
    monkeypatch.delenv("AZURE_CONTAINERAPP_ENV", raising=False)

    result = check_provider_readiness("Azure", _config("Azure"))

    assert result["ready"] is False
    assert "AZURE_CONTAINERAPP_ENV" in result["missing"]


def test_azure_readiness_with_env_vars_returns_ready(monkeypatch):
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "fyp-rg")
    monkeypatch.setenv("AZURE_LOCATION", "eastus")
    monkeypatch.setenv("AZURE_CONTAINERAPP_ENV", "fyp-env")

    result = check_provider_readiness("Azure", _config("Azure"))

    assert result["ready"] is True
    assert result["missing"] == []


def test_gcp_readiness_with_env_vars_returns_ready(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "fyp-project")
    monkeypatch.setenv("GCP_REGION", "asia-south1")
    monkeypatch.setenv("GCP_PLATFORM", "managed")

    result = check_provider_readiness("GCP", _config("GCP"))

    assert result["ready"] is True
    assert result["ready_for_dry_run"] is True
    assert result["ready_for_real_deploy"] is True
    assert any("implemented" in check["message"] for check in result["checks"])
