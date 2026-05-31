from datetime import datetime, timedelta
from uuid import uuid4

from flask_login import UserMixin

from database import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    auth_provider = db.Column(db.String(40), default="password", nullable=False)
    oauth_id = db.Column(db.String(255), nullable=True, index=True)
    avatar_url = db.Column(db.String(500), nullable=True)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    theme_preference = db.Column(db.String(20), default="system", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)

    deployments = db.relationship("DeploymentRecord", back_populates="user", cascade="all, delete-orphan")

    @property
    def has_local_password(self) -> bool:
        return bool(self.password_hash)


class DeploymentRecord(db.Model):
    __tablename__ = "deployment_records"

    id = db.Column(db.String(32), primary_key=True, default=lambda: uuid4().hex)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    app_name = db.Column(db.String(200))
    app_type = db.Column(db.String(50))
    environment = db.Column(db.String(80))
    image = db.Column(db.String(500))
    selected_provider = db.Column(db.String(50))
    execution_provider = db.Column(db.String(50))
    selection_mode = db.Column(db.String(50))
    deployment_mode = db.Column(db.String(50))
    status = db.Column(db.String(80), index=True)
    endpoint = db.Column(db.String(500))
    health_status = db.Column(db.String(80))
    yaml_content = db.Column(db.Text, nullable=False)
    result_json = db.Column(db.JSON, nullable=False)
    health_result_json = db.Column(db.JSON, nullable=True)
    cleanup_status = db.Column(db.String(80), nullable=True)
    auto_cleanup_at = db.Column(db.DateTime, nullable=True)
    last_checked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship("User", back_populates="deployments")

    def apply_result(self, result, yaml_content=None):
        decision = result.get("decision", {})
        endpoints = result.get("public_endpoints") or []
        health = result.get("health_check", {})

        self.app_name = result.get("app")
        self.app_type = result.get("app_type")
        self.environment = result.get("environment")
        self.image = result.get("image")
        self.selected_provider = decision.get("selected_provider")
        self.execution_provider = decision.get("execution_provider")
        self.selection_mode = decision.get("selection_mode")
        self.deployment_mode = result.get("deployment_mode")
        self.status = result.get("status")
        self.endpoint = endpoints[0].get("url") if endpoints else None
        self.health_status = health.get("result") or health.get("status")
        self.health_result_json = health
        self.result_json = result
        cleanup = result.get("cleanup_result", {})
        if cleanup:
            self.cleanup_status = cleanup.get("status")
        if yaml_content is not None:
            self.yaml_content = yaml_content

    def to_cleanup_record(self):
        result = self.result_json or {}
        deployment = result.get("deployment", {})
        return {
            "id": self.id,
            "app_name": self.app_name,
            "execution_provider": self.execution_provider,
            "status": self.status,
            "deployment_mode": self.deployment_mode,
            "instance_id": deployment.get("instance_id"),
            "app_names": deployment.get("app_names", []),
            "service_names": deployment.get("service_names", []),
            "deployment": deployment,
        }


def auto_cleanup_delta(value: str):
    return {
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "24h": timedelta(hours=24),
    }.get(value)


def find_due_cleanups(now=None):
    now = now or datetime.utcnow()
    return (
        DeploymentRecord.query.filter(DeploymentRecord.auto_cleanup_at.isnot(None))
        .filter(DeploymentRecord.auto_cleanup_at <= now)
        .filter(DeploymentRecord.status.in_(["deployed", "delete_failed"]))
        .all()
    )
