import app as app_module
from models import DeploymentRecord


def _login():
    client = app_module.app.test_client()
    client.post("/register", data={"name": "Wizard", "email": "wizard@example.com", "password": "secret123"})
    return client


def test_wizard_page_requires_login():
    response = app_module.app.test_client().get("/deploy/wizard")

    assert response.status_code == 302


def test_wizard_renders_steps():
    response = _login().get("/deploy/wizard")

    assert response.status_code == 200
    assert b"Step 1" in response.data
    assert b"Step 4" in response.data


def test_wizard_generates_yaml_schema():
    config = app_module._wizard_config_from_form(
        {
            "app_name": "wizard-api",
            "app_type": "api",
            "image": "dockertalha19/fyp-books-api:latest",
            "port": "8000",
            "health_check": "/health",
            "budget": "30",
            "uptime": "99.9",
            "provider_mode": "GCP",
            "preferred_region": "asia",
            "public_access": "true",
        }
    )

    assert config["app"]["name"] == "wizard-api"
    assert config["services"][0]["image"] == "dockertalha19/fyp-books-api:latest"
    assert config["requirements"]["max_monthly_cost_usd"] == 30
    assert config["selection"] == {"mode": "manual", "provider": "GCP"}


def test_wizard_dry_run_submission_uses_existing_flow():
    client = _login()
    response = client.post(
        "/deploy/wizard",
        data={
            "app_name": "wizard-api",
            "app_type": "api",
            "image": "dockertalha19/fyp-books-api:latest",
            "port": "8000",
            "health_check": "/health",
            "budget": "30",
            "uptime": "99.9",
            "provider_mode": "auto",
            "preferred_region": "asia",
            "public_access": "true",
        },
    )

    assert response.status_code == 200
    assert b"dry_run" in response.data
    with app_module.app.app_context():
        record = DeploymentRecord.query.filter_by(app_name="wizard-api").first()
        assert record is not None
        assert "services:" in record.yaml_content
        assert "selection:" in record.yaml_content
