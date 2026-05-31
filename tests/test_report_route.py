import app as app_module
from portal_models import DeploymentRecord, User, db


def test_deployment_report_route_returns_saved_record():
    client = app_module.app.test_client()
    client.post(
        "/register",
        data={"name": "Reporter", "email": "report@example.com", "password": "secret123"},
        follow_redirects=True,
    )
    with app_module.app.app_context():
        user = User.query.filter_by(email="report@example.com").first()
        result = {
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
        record = DeploymentRecord(user_id=user.id, yaml_content="app:\n  name: report-app\n", result_json=result)
        record.apply_result(result, yaml_content=record.yaml_content)
        db.session.add(record)
        db.session.commit()
        deployment_id = record.id

    response = client.get(f"/deployment-report/{deployment_id}")

    assert response.status_code == 200
    assert b"Deployment Report" in response.data
    assert b"report-app" in response.data
