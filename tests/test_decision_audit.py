from io import BytesIO

import yaml

import app as app_module
from config_schema import validate_config
from decision_engine import PROVIDER_CATALOG, _score_provider, select_provider
from models import DeploymentRecord


YAML = b"""
app:
  name: why-provider-api
  environment: production
deployment:
  type: container
  image: dockertalha19/fyp-books-api:latest
  port: 8000
requirements:
  max_monthly_cost_usd: 30
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
"""


def test_cost_scoring_is_relative_to_budget():
    cheaper = _score_provider(PROVIDER_CATALOG["GCP"], estimated_cost=10, max_budget=20, min_uptime=99.9, preferred_region="asia")
    pricier = _score_provider(PROVIDER_CATALOG["GCP"], estimated_cost=18, max_budget=20, min_uptime=99.9, preferred_region="asia")

    assert cheaper > pricier
    assert cheaper >= 25


def test_over_budget_provider_has_exclusion_reason():
    decision = select_provider(
        validate_config(
            yaml.safe_load(
                """
                app:
                  name: over-budget-api
                  environment: production
                deployment:
                  type: container
                  image: dockertalha19/fyp-books-api:latest
                  port: 8000
                requirements:
                  max_monthly_cost_usd: 10
                  min_uptime_percent: 99.0
                  preferred_region: asia
                  public_access: true
                """
            )
        )
    )

    assert decision["selected_provider"] is None
    assert all(provider["exclusion_reason"] for provider in decision["evaluated_providers"])


def test_decision_audit_trail_stored_for_deployment():
    client = app_module.app.test_client()
    client.post("/register", data={"name": "Why", "email": "why@example.com", "password": "secret123"})

    response = client.post(
        "/deploy",
        data={"config_file": (BytesIO(YAML), "config.yaml"), "cloud_selection": "auto"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert b"Why this provider?" in response.data
    with app_module.app.app_context():
        record = DeploymentRecord.query.filter_by(app_name="why-provider-api").first()
        assert record is not None
        audit = record.result_json["decision"]["audit_trail"]
        assert audit["chosen_provider"] == record.selected_provider
        assert audit["provider_evaluations"]
