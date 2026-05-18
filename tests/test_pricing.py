import pytest
import yaml

from config_schema import validate_config
from decision_engine import select_provider
from pricing import azure_pricing
from pricing.azure_pricing import FALLBACK_NOTE, get_azure_estimate
from pricing.models import PriceEstimate
from pricing.pricing_service import get_price_estimates


def _config(max_cost=20, min_uptime=99.9):
    return validate_config(
        yaml.safe_load(
            f"""
            app:
              name: pricing-test
              environment: production
            deployment:
              type: container
              image: nginx
              port: 80
            requirements:
              max_monthly_cost_usd: {max_cost}
              min_uptime_percent: {min_uptime}
              preferred_region: asia
              public_access: true
            """
        )
    )


def test_fallback_pricing_returns_aws_gcp_azure():
    estimates = get_price_estimates(_config())

    assert set(estimates) == {"AWS", "GCP", "Azure"}
    assert estimates["AWS"].estimated_monthly_cost_usd == 18.0
    assert estimates["GCP"].estimated_monthly_cost_usd == 12.0
    assert estimates["Azure"].estimated_monthly_cost_usd == 15.0
    assert all(estimate.pricing_type == "fallback" for estimate in estimates.values())


def test_live_pricing_disabled_uses_fallback(monkeypatch):
    called = {"requests": False}

    def fail_if_called(*args, **kwargs):
        called["requests"] = True
        raise AssertionError("requests.get should not be called when live pricing is disabled")

    monkeypatch.setenv("ENABLE_LIVE_PRICING", "false")
    monkeypatch.setattr(azure_pricing.requests, "get", fail_if_called)

    estimate = get_azure_estimate(region="asia")

    assert estimate.provider == "Azure"
    assert estimate.pricing_type == "fallback"
    assert estimate.estimated_monthly_cost_usd == 15.0
    assert FALLBACK_NOTE in estimate.notes
    assert called["requests"] is False


def test_azure_api_failure_uses_fallback(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise azure_pricing.requests.exceptions.Timeout("pricing timeout")

    monkeypatch.setenv("ENABLE_LIVE_PRICING", "true")
    monkeypatch.setattr(azure_pricing.requests, "get", raise_timeout)

    estimate = get_azure_estimate(region="asia")

    assert estimate.provider == "Azure"
    assert estimate.pricing_type == "fallback"
    assert estimate.estimated_monthly_cost_usd == 15.0
    assert FALLBACK_NOTE in estimate.notes


def test_decision_engine_uses_dynamic_pricing_estimates():
    price_estimates = {
        "AWS": PriceEstimate(
            provider="AWS",
            estimated_monthly_cost_usd=18.0,
            hourly_cost_usd=None,
            pricing_type="fallback",
            pricing_source="test_dynamic",
        ),
        "GCP": PriceEstimate(
            provider="GCP",
            estimated_monthly_cost_usd=40.0,
            hourly_cost_usd=None,
            pricing_type="fallback",
            pricing_source="test_dynamic",
        ),
        "Azure": PriceEstimate(
            provider="Azure",
            estimated_monthly_cost_usd=15.0,
            hourly_cost_usd=None,
            pricing_type="fallback",
            pricing_source="test_dynamic",
        ),
    }

    decision = select_provider(_config(max_cost=20), price_estimates=price_estimates)
    gcp_evaluation = next(item for item in decision["evaluated_providers"] if item["provider"] == "GCP")

    assert decision["selected_provider"] == "Azure"
    assert gcp_evaluation["estimated_cost_usd"] == 40.0
    assert gcp_evaluation["pricing_source"] == "test_dynamic"


def test_live_pricing_success_uses_mocked_azure_response(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "Items": [
                    {
                        "retailPrice": 0.02,
                        "unitOfMeasure": "1 Hour",
                        "armRegionName": "southeastasia",
                    }
                ]
            }

    monkeypatch.setenv("ENABLE_LIVE_PRICING", "true")
    monkeypatch.setattr(azure_pricing.requests, "get", lambda *args, **kwargs: Response())

    estimate = get_azure_estimate(region="asia")

    assert estimate.pricing_type == "live"
    assert estimate.estimated_monthly_cost_usd == pytest.approx(14.6)
    assert estimate.pricing_source == "Azure Retail Prices API"
