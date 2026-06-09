from io import BytesIO

import app as app_module


YAML = b"""
app:
  name: timeline-api
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


def test_timeline_renders_for_dry_run_result():
    client = app_module.app.test_client()
    client.post("/register", data={"name": "Timeline", "email": "timeline@example.com", "password": "secret123"})

    response = client.post(
        "/deploy",
        data={"config_file": (BytesIO(YAML), "config.yaml"), "cloud_selection": "auto"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert b"Deployment Timeline" in response.data
    assert b"No cloud resources created" in response.data
    assert b"secret" not in response.data.lower()
