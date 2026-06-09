import yaml
from datetime import datetime

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
        record.started_at = record.started_at or datetime.utcnow()
        result = dict(record.result_json or {})
        result["status"] = "running"
        result.setdefault("deployment", {})["status"] = "running"
        result["deployment"]["message"] = "Background deployment job is running."
        record.result_json = result
        db.session.commit()

        try:
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
        except Exception:
            result = dict(record.result_json or {})
            result["status"] = "failed"
            result.setdefault("deployment", {})["status"] = "failed"
            result["deployment"]["message"] = "Background deployment job failed. Check worker logs for details."
            record.status = "failed"
            record.last_error = "Background deployment job failed. Check worker logs for details."
            record.completed_at = datetime.utcnow()
            record.result_json = result
            db.session.commit()
            raise
