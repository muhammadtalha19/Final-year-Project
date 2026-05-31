import app as app_module
from deployment_history import add_deployment_record


def test_deployment_report_route_returns_saved_record():
    record = add_deployment_record(
        {
            "app": "report-app",
            "app_type": "api",
            "image": "dockertalha19/fyp-books-api:latest",
            "status": "dry_run",
            "deployment_mode": "dry_run",
            "decision": {
                "selected_provider": "GCP",
                "execution_provider": "GCP",
                "reason": "test",
                "evaluated_providers": [],
            },
            "deployment": {"status": "dry_run"},
            "generated_commands": [],
            "public_endpoints": [],
            "health_check": {"result": "skipped", "message": "dry-run"},
            "provider_readiness": {},
            "docker_image_validation": {},
            "diagnostics": {},
        }
    )
    app_module.app.config["TESTING"] = True

    response = app_module.app.test_client().get(f"/deployment-report/{record['id']}")

    assert response.status_code == 200
    assert b"Deployment Report" in response.data
    assert b"report-app" in response.data
