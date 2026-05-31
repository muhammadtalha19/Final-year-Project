import app as app_module
from models import DeploymentRecord, User


def _result():
    return {
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


def _login_and_record():
    client = app_module.app.test_client()
    client.post(
        "/register",
        data={"name": "Reporter", "email": "reporter@example.com", "password": "secret123"},
    )
    with app_module.app.app_context():
        user = User.query.filter_by(email="reporter@example.com").first()
        record = DeploymentRecord(user_id=user.id, yaml_content="app:\n  name: report-app\n", result_json=_result())
        record.apply_result(record.result_json, yaml_content=record.yaml_content)
        app_module.db.session.add(record)
        app_module.db.session.commit()
        return client, record.id


def test_deployment_report_route_returns_saved_record():
    client, record_id = _login_and_record()

    response = client.get(f"/deployment-report/{record_id}")

    assert response.status_code == 200
    assert b"Deployment Report" in response.data
    assert b"report-app" in response.data
