from providers.aws_provider import AWSProvider
from providers.azure_mock import AzureMockProvider
from providers.gcp_mock import GCPMockProvider


def test_aws_log_stub_returns_console_hint():
    result = AWSProvider().get_logs({"instance_id": "i-123"})

    assert result["status"] == "plan_only"
    assert result["commands"][0]["command"] == ["aws", "ec2", "get-console-output", "--instance-id", "i-123"]
    assert "cloud-init-output" in result["message"]


def test_azure_log_stub_returns_az_command(monkeypatch):
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "fyp-rg")

    result = AzureMockProvider().get_logs({"app_names": ["expense-tracker"]})

    assert result["commands"][0]["command"][:4] == ["az", "containerapp", "logs", "show"]
    assert "expense-tracker" in result["commands"][0]["command"]


def test_gcp_log_stub_returns_gcloud_command(monkeypatch):
    monkeypatch.setenv("GCP_REGION", "asia-south1")

    result = GCPMockProvider().get_logs({"service_names": ["gcp-api"]})

    assert result["commands"][0]["command"][:5] == ["gcloud", "run", "services", "logs", "read"]
    assert "gcp-api" in result["commands"][0]["command"]
