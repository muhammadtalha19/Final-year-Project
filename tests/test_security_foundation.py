import pytest

import app as app_module
from config_schema import ConfigValidationError, validate_config
from credential_vault import mask_secret


def register(client):
    client.post("/register", data={"name": "Security", "email": "security@example.com", "password": "secret123"})


def test_request_id_header_present():
    response = app_module.app.test_client().get("/")

    assert response.headers.get("X-Request-ID")


def test_yaml_size_limit_rejects_large_input():
    client = app_module.app.test_client()
    register(client)

    response = client.post("/deploy/new", data={"yaml_content": "a" * (app_module.MAX_YAML_BYTES + 1)})

    assert response.status_code == 400
    assert b"YAML input is too large. Maximum allowed size is 64 KB." in response.data


def test_name_and_docker_image_shell_metacharacters_rejected():
    with pytest.raises(ConfigValidationError) as exc_info:
        validate_config(
            {
                "app": {"name": "bad name", "environment": "production"},
                "deployment": {"type": "container", "image": "dockertalha19/app:latest;rm", "port": 80},
                "requirements": {
                    "max_monthly_cost_usd": 20,
                    "min_uptime_percent": 99.9,
                    "preferred_region": "asia",
                    "public_access": True,
                },
            }
        )

    message = "; ".join(exc_info.value.errors)
    assert "app.name" in message
    assert "deployment.image contains unsafe characters" in message


def test_valid_registry_image_patterns_still_work():
    config = validate_config(
        {
            "app": {"name": "safe-app", "environment": "production"},
            "deployment": {"type": "container", "image": "registry.example.com/team/app:1.0", "port": 80},
            "requirements": {
                "max_monthly_cost_usd": 20,
                "min_uptime_percent": 99.9,
                "preferred_region": "asia",
                "public_access": True,
            },
        }
    )

    assert config["services"][0]["image"] == "registry.example.com/team/app:1.0"


def test_mask_secret_handles_empty_and_short_values():
    assert mask_secret(None) == ""
    assert mask_secret("") == ""
    assert mask_secret("abc") == "****"
