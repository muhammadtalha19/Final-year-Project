import requests
import yaml

import orchestrator
from config_schema import validate_config
from health_checks import check_urls_with_retries
from providers.azure_mock import AzureMockProvider


class Response:
    def __init__(self, status_code):
        self.status_code = status_code


def test_health_retry_passes_after_retry_without_real_sleep():
    calls = {"count": 0, "sleeps": []}

    def fake_get(url, timeout):
        calls["count"] += 1
        return Response(503 if calls["count"] == 1 else 200)

    result = check_urls_with_retries(
        ["https://example.test/health"],
        timeout_seconds=100,
        backoff_seconds=[1, 2],
        request_get=fake_get,
        sleep_func=lambda delay: calls["sleeps"].append(delay),
        monotonic=lambda: calls["count"],
    )

    assert result["result"] == "passed"
    assert result["attempts"] == 2
    assert calls["sleeps"] == [1]


def test_health_retry_fails_after_max_retries_without_network():
    def fake_get(url, timeout):
        raise requests.RequestException("offline")

    result = check_urls_with_retries(
        ["https://example.test/health"],
        timeout_seconds=100,
        backoff_seconds=[1, 2],
        request_get=fake_get,
        sleep_func=lambda delay: None,
        monotonic=lambda: 0,
    )

    assert result["result"] == "failed"
    assert result["attempts"] == 2
    assert "offline" in result["message"]


def test_auto_cleanup_runs_when_health_fails_and_flag_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_REAL_DEPLOYMENT", "true")
    monkeypatch.setenv("ALLOW_AZURE_DEPLOYMENT", "true")
    monkeypatch.setenv("AUTO_TERMINATE_ON_FAILURE", "true")
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "fyp-rg")
    monkeypatch.setenv("AZURE_LOCATION", "eastus")
    monkeypatch.setenv("AZURE_CONTAINERAPP_ENV", "fyp-env")
    monkeypatch.setenv("AZURE_ACCOUNT_READY", "true")

    def fake_deploy(self, config):
        return {
            "provider": "Azure",
            "status": "deployed",
            "deployment_mode": "real",
            "message": "mock deployed",
            "app_names": ["health-retry-api"],
            "generated_commands": [],
            "service_endpoints": [{"name": "api", "url": "https://api.example.test"}],
        }

    def fake_health_check(self, deployment):
        return {
            "result": "failed",
            "status": "failed",
            "passed": False,
            "url": "https://api.example.test/health",
            "status_code": 503,
            "response_time_ms": 12,
            "attempts": 2,
            "message": "not ready",
        }

    cleanup_calls = []

    def fake_cleanup(record, cloud_account=None, require_cloud_account=False):
        cleanup_calls.append(record)
        return {
            "provider": "Azure",
            "status": "deleted",
            "app_name": "health-retry-api",
            "message": "mock cleanup",
        }

    monkeypatch.setattr(AzureMockProvider, "deploy", fake_deploy)
    monkeypatch.setattr(AzureMockProvider, "health_check", fake_health_check)
    monkeypatch.setattr(orchestrator, "cleanup_deployment_record", fake_cleanup)

    config = validate_config(
        yaml.safe_load(
            """
            app:
              name: health-retry-api
              environment: production
            selection:
              mode: manual
              provider: Azure
            deployment:
              type: container
              image: dockertalha19/fyp-books-api:latest
              port: 8000
            requirements:
              max_monthly_cost_usd: 20
              min_uptime_percent: 99.9
              preferred_region: asia
              public_access: true
            health_check: /health
            """
        )
    )

    result = orchestrator.deploy_app(config, confirm_real_deployment=True)

    assert result["status"] == "cleanup_required"
    assert result["cleanup_result"]["status"] == "deleted"
    assert cleanup_calls
    assert cleanup_calls[0]["status"] == "deployed"
    assert cleanup_calls[0]["execution_provider"] == "Azure"
