import yaml

from config_schema import validate_config
from decision_engine import select_provider
from orchestrator import deploy_app
from providers.aws_provider import AWSProvider


def _config(max_cost=20, min_uptime=99.9, preferred_region="asia"):
    return validate_config(
        yaml.safe_load(
            f"""
            app:
              name: test-app
              environment: production
            deployment:
              type: container
              image: nginx
              port: 80
              replicas: 1
            requirements:
              max_monthly_cost_usd: {max_cost}
              min_uptime_percent: {min_uptime}
              preferred_region: {preferred_region}
              public_access: true
            """
        )
    )


def test_decision_engine_rejects_providers_over_cost_limit():
    decision = select_provider(_config(max_cost=10, min_uptime=99.0))

    assert decision["selected_provider"] is None
    assert all(not provider["eligible"] for provider in decision["evaluated_providers"])
    assert all(provider["rejection_reasons"] for provider in decision["evaluated_providers"])


def test_decision_engine_rejects_providers_below_uptime_requirement():
    decision = select_provider(_config(max_cost=50, min_uptime=99.995))

    assert decision["selected_provider"] is None
    assert all(not provider["eligible"] for provider in decision["evaluated_providers"])


def test_decision_engine_selects_lowest_cost_eligible_provider_when_uptime_is_satisfied():
    decision = select_provider(_config(max_cost=20, min_uptime=99.9))

    assert decision["selected_provider"] == "GCP"
    assert decision["execution_provider"] == "AWS"
    assert all("pricing_type" in provider for provider in decision["evaluated_providers"])


def test_no_real_cloud_deployment_is_triggered_during_tests(monkeypatch, tmp_path):
    called = {"aws_deploy": False}

    def fail_if_called(self, config):
        called["aws_deploy"] = True
        raise AssertionError("AWS deployment should not run during tests")

    monkeypatch.setenv("DEPLOYMENT_HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setattr(AWSProvider, "deploy", fail_if_called)

    result = deploy_app(_config(max_cost=20, min_uptime=99.9), execute=False)

    assert result["status"] == "dry_run"
    assert called["aws_deploy"] is False
