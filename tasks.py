import yaml

from app import app, _cloud_account_map
from database import db
from models import DeploymentRecord
from orchestrator import deploy_app


def run_deployment_job(deployment_id: str):
    with app.app_context():
        record = db.session.get(DeploymentRecord, deployment_id)
        if not record:
            return {"status": "not_found"}

        record.status = "running"
        result = dict(record.result_json or {})
        result["status"] = "running"
        result.setdefault("deployment", {})["status"] = "running"
        result["deployment"]["message"] = "Background deployment job is running."
        record.result_json = result
        db.session.commit()

        config = yaml.safe_load(record.yaml_content)
        result = deploy_app(
            config,
            confirm_real_deployment=True,
            cloud_accounts=_cloud_account_map(record.user_id),
            require_cloud_account=True,
        )
        record.apply_result(result, yaml_content=record.yaml_content)
        db.session.commit()
        return {"status": record.status, "deployment_id": record.id}
