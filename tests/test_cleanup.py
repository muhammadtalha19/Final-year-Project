import subprocess

from deployment_history import add_deployment_record, get_deployment_record
from orchestrator import delete_deployment
from providers.aws_provider import AWSProvider
from providers.azure_mock import AzureMockProvider
from providers.gcp_mock import GCPMockProvider


def _stored_result(provider, status="deployed", deployment_mode="real", deployment=None):
    return {
        "app": "expense-tracker",
        "status": status,
        "deployment_mode": deployment_mode,
        "decision": {
            "selected_provider": provider,
            "execution_provider": provider,
            "reason": "test",
            "evaluated_providers": [],
        },
        "deployment": deployment or {},
        "public_endpoints": [],
    }


def test_aws_delete_missing_instance_id_returns_delete_skipped(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(AWSProvider, "_client", lambda self: (_ for _ in ()).throw(AssertionError("no boto3")))

    result = AWSProvider().delete({"provider": "AWS"})

    assert result["status"] == "delete_skipped"
    assert "instance ID" in result["message"]


def test_aws_delete_calls_mocked_terminate_instances(monkeypatch):
    calls = []

    class FakeEC2:
        def terminate_instances(self, InstanceIds):
            calls.append(InstanceIds)

    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(AWSProvider, "_client", lambda self: FakeEC2())

    result = AWSProvider().delete({"instance_id": "i-test123"})

    assert result["status"] == "deleted"
    assert result["instance_id"] == "i-test123"
    assert calls == [["i-test123"]]


def test_azure_delete_missing_app_name_returns_delete_skipped(monkeypatch):
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "fyp-rg")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no az")))

    result = AzureMockProvider().delete({"provider": "Azure"})

    assert result["status"] == "delete_skipped"
    assert "app name" in result["message"]


def test_azure_delete_calls_mocked_subprocess_with_argument_list(monkeypatch):
    calls = []

    class Completed:
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "fyp-rg")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = AzureMockProvider().delete({"app_names": ["expense-tracker"]})

    assert result["status"] == "deleted"
    assert calls[0][0] == [
        "az",
        "containerapp",
        "delete",
        "--name",
        "expense-tracker",
        "--resource-group",
        "fyp-rg",
        "--yes",
    ]
    assert "shell" not in calls[0][1]
    assert calls[0][1] == {"capture_output": True, "text": True, "check": True}


def test_orchestrator_skips_delete_for_dry_run_record(monkeypatch):
    record = add_deployment_record(_stored_result("AWS", status="dry_run", deployment_mode="dry_run"))
    monkeypatch.setattr(AWSProvider, "delete", lambda self, value: (_ for _ in ()).throw(AssertionError("skip")))

    result = delete_deployment(record["id"])
    updated = get_deployment_record(record["id"])

    assert result["status"] == "delete_skipped"
    assert updated["status"] == "delete_skipped"


def test_orchestrator_skips_gcp_cleanup(monkeypatch):
    record = add_deployment_record(_stored_result("GCP"))
    monkeypatch.setattr(GCPMockProvider, "delete", lambda self, value: (_ for _ in ()).throw(AssertionError("skip")))

    result = delete_deployment(record["id"])
    updated = get_deployment_record(record["id"])

    assert result["status"] == "delete_skipped"
    assert "GCP" in result["message"]
    assert updated["status"] == "delete_skipped"
