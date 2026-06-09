import requests

from providers.azure_mock import AzureMockProvider


def test_health_check_returns_richer_shape(monkeypatch):
    class Response:
        status_code = 200

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    deployment = {
        "status": "deployed",
        "health_check_path": "/health",
        "service_endpoints": [{"name": "api", "url": "https://api.example.com"}],
    }

    result = AzureMockProvider().health_check(deployment)

    assert result["result"] == "passed"
    assert result["url"] == "https://api.example.com/health"
    assert result["status_code"] == 200
    assert result["attempts"] == 1


def test_health_check_skips_without_endpoint():
    result = AzureMockProvider().health_check({"status": "deployed", "service_endpoints": []})

    assert result["result"] == "skipped"
    assert result["attempts"] == 0
