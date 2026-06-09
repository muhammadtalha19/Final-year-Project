import subprocess

import yaml

import orchestrator
from config_schema import validate_config
from providers.gcp_mock import GCPMockProvider


def _manual_gcp_config():
    return validate_config(
        yaml.safe_load(
            """
            app:
              name: gcp-api
              environment: production
              type: api
            selection:
              mode: manual
              provider: GCP
            deployment:
              type: container
              image: dockertalha19/fyp-books-api:latest
              port: 8000
            health_check: /health
            requirements:
              max_monthly_cost_usd: 20
              min_uptime_percent: 99.9
              preferred_region: asia
              public_access: true
            """
        )
    )


def _enable_real_gcp(monkeypatch):
    monkeypatch.setenv("ENABLE_REAL_DEPLOYMENT", "true")
    monkeypatch.setenv("ALLOW_GCP_DEPLOYMENT", "true")
    monkeypatch.setenv("GCP_PROJECT_ID", "fyp-project")
    monkeypatch.setenv("GCP_REGION", "asia-south1")
    monkeypatch.setenv("GCP_PLATFORM", "managed")


def test_gcp_dry_run_does_not_call_subprocess(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no gcloud")))

    result = orchestrator.deploy_app(_manual_gcp_config())

    assert result["status"] == "dry_run"
    assert result["generated_commands"][0]["command"][:4] == ["gcloud", "run", "deploy", "gcp-api"]


def test_gcp_real_deploy_command_args_and_parses_url(monkeypatch):
    calls = []

    class Completed:
        stdout = '{"status": {"url": "https://gcp-api.example.run.app"}}'
        stderr = ""

    def fake_run(command, capture_output, text, check):
        calls.append((command, capture_output, text, check))
        return Completed()

    _enable_real_gcp(monkeypatch)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        GCPMockProvider,
        "health_check",
        lambda self, result: {"result": "skipped", "status": "skipped", "message": "mocked", "attempts": 0},
    )

    result = orchestrator.deploy_app(_manual_gcp_config(), confirm_real_deployment=True)

    assert result["status"] == "deployed"
    assert calls[0][0][:4] == ["gcloud", "run", "deploy", "gcp-api"]
    assert "--allow-unauthenticated" in calls[0][0]
    assert calls[0][1:] == (True, True, True)
    assert result["public_endpoints"][0]["url"] == "https://gcp-api.example.run.app"


def test_gcp_deploy_failure_returns_failed(monkeypatch):
    _enable_real_gcp(monkeypatch)

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], output="", stderr="gcloud failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = GCPMockProvider().deploy(_manual_gcp_config())

    assert result["status"] == "failed"
    assert result["stderr"] == "gcloud failed"


def test_gcp_cleanup_command_args_are_correct(monkeypatch):
    calls = []

    class Completed:
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    monkeypatch.setenv("GCP_REGION", "asia-south1")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = GCPMockProvider().delete({"service_names": ["gcp-api"]})

    assert result["status"] == "deleted"
    assert calls[0][0] == [
        "gcloud",
        "run",
        "services",
        "delete",
        "gcp-api",
        "--region",
        "asia-south1",
        "--quiet",
    ]
    assert calls[0][1] == {"capture_output": True, "text": True, "check": True}
