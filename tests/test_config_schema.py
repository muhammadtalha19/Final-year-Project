import pytest
import yaml

from config_schema import ConfigValidationError, validate_config


def test_valid_single_service_yaml_passes_validation():
    raw = yaml.safe_load(
        """
        app:
          name: img2pdf-web
          environment: production
        deployment:
          type: container
          image: dockertalha19/img2pdf
          port: 80
          replicas: 1
        resources:
          cpu: 1
          memory: 512Mi
        requirements:
          max_monthly_cost_usd: 20
          min_uptime_percent: 99.9
          preferred_region: asia
          public_access: true
        """
    )

    config = validate_config(raw)

    assert config["app"]["name"] == "img2pdf-web"
    assert config["deployment"]["type"] == "container"
    assert config["app"]["type"] == "api"
    assert config["services"][0]["image"] == "dockertalha19/img2pdf"
    assert config["services"][0]["port"] == 80
    assert config["selection"] == {"mode": "auto", "provider": None}


def test_valid_multi_service_yaml_passes_validation():
    raw = yaml.safe_load(
        """
        app:
          name: ecommerce-platform
          environment: production
        services:
          - name: login-service
            image: myrepo/login
            port: 5000
            public: true
          - name: order-service
            image: myrepo/orders
            port: 5001
            public: false
        requirements:
          max_monthly_cost_usd: 30
          min_uptime_percent: 99.9
          preferred_region: asia
          public_access: true
        """
    )

    config = validate_config(raw)

    assert len(config["services"]) == 2
    assert config["services"][0]["public"] is True
    assert config["services"][1]["public"] is False


def test_missing_image_fails_validation():
    raw = yaml.safe_load(
        """
        app:
          name: missing-image
          environment: production
        deployment:
          type: container
          port: 80
        requirements:
          max_monthly_cost_usd: 20
          min_uptime_percent: 99.9
        """
    )

    with pytest.raises(ConfigValidationError) as exc_info:
        validate_config(raw)

    assert "image" in str(exc_info.value)


def test_invalid_port_fails_validation():
    raw = yaml.safe_load(
        """
        app:
          name: invalid-port
          environment: production
        deployment:
          type: container
          image: nginx
          port: 70000
        requirements:
          max_monthly_cost_usd: 20
          min_uptime_percent: 99.9
        """
    )

    with pytest.raises(ConfigValidationError) as exc_info:
        validate_config(raw)

    assert "port" in str(exc_info.value).lower()


def test_auto_selection_ignores_provider_if_present():
    raw = yaml.safe_load(
        """
        app:
          name: auto-with-provider
          environment: production
        selection:
          mode: auto
          provider: NotACloud
        deployment:
          type: container
          image: nginx
          port: 80
        requirements:
          max_monthly_cost_usd: 20
          min_uptime_percent: 99.9
        """
    )

    config = validate_config(raw)

    assert config["selection"] == {"mode": "auto", "provider": None}


def test_app_type_and_resources_are_validated():
    raw = yaml.safe_load(
        """
        app:
          name: ml-api
          environment: production
          type: ml-api
        deployment:
          type: container
          image: dockertalha19/fyp-ml-api:latest
          port: 8000
        resources:
          cpu: 1
          memory: 1Gi
          min_instances: 0
          max_instances: 1
        health_check: /health
        requirements:
          max_monthly_cost_usd: 20
          min_uptime_percent: 99.9
        """
    )

    config = validate_config(raw)

    assert config["app"]["type"] == "ml-api"
    assert config["resources"]["cpu"] == 1.0
    assert config["resources"]["memory"] == "1Gi"
    assert config["resources"]["min_instances"] == 0
    assert config["resources"]["max_instances"] == 1
    assert config["health_check"]["path"] == "/health"


def test_invalid_app_type_fails_validation():
    raw = yaml.safe_load(
        """
        app:
          name: bad-type
          environment: production
          type: batch
        deployment:
          type: container
          image: nginx
          port: 80
        requirements:
          max_monthly_cost_usd: 20
          min_uptime_percent: 99.9
        """
    )

    with pytest.raises(ConfigValidationError) as exc_info:
        validate_config(raw)

    assert "app.type" in str(exc_info.value)


def test_high_scale_requires_env_flag(monkeypatch):
    monkeypatch.setenv("ALLOW_HIGH_SCALE", "false")
    raw = yaml.safe_load(
        """
        app:
          name: high-scale
          environment: production
        deployment:
          type: container
          image: nginx
          port: 80
        resources:
          max_instances: 2
        requirements:
          max_monthly_cost_usd: 20
          min_uptime_percent: 99.9
        """
    )

    with pytest.raises(ConfigValidationError) as exc_info:
        validate_config(raw)

    assert "ALLOW_HIGH_SCALE" in str(exc_info.value)
