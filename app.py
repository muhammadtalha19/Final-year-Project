import os
import logging
from functools import wraps
from uuid import uuid4
from datetime import datetime
from typing import Any, Dict, Optional

from flask import Flask, Response, abort, flash, g, has_request_context, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
import requests
import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed in the project environment.
    def load_dotenv() -> None:
        return None

from auth import begin_oauth, complete_oauth, init_auth, oauth_status
from config_schema import ConfigValidationError, validate_config
from credential_vault import is_encryption_configured
from database import db, init_database
from models import AuditLog, CloudAccount, DeploymentRecord, User, auto_cleanup_delta, find_due_cleanups
from orchestrator import cleanup_deployment_record, deploy_app
from provider_bootstrap import generate_provider_bootstrap_plan
from provider_readiness import check_provider_readiness
from queue_utils import enqueue_deployment

try:
    from flask_wtf.csrf import CSRFProtect, generate_csrf
except ImportError:  # pragma: no cover - dependency is declared for production installs.
    class CSRFProtect:
        def __init__(self, app=None):
            return None

    def generate_csrf():
        return ""

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except ImportError:  # pragma: no cover - dependency is declared for production installs.
    class Limiter:
        def __init__(self, *args, **kwargs):
            return None

        def init_app(self, app):
            return None

        def limit(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

    def get_remote_address():
        return "127.0.0.1"

try:
    from flask_migrate import Migrate
except ImportError:  # pragma: no cover - dependency is declared for production installs.
    class Migrate:
        def __init__(self, *args, **kwargs):
            return None


load_dotenv()
logger = logging.getLogger(__name__)
from config import get_config_class

app = Flask(__name__, instance_relative_config=True)
config_class = get_config_class()
app.config.from_object(config_class)
config_class.init_app(app)
os.makedirs(app.instance_path, exist_ok=True)

init_database(app)
migrate = Migrate(app, db)
init_auth(app)
csrf = CSRFProtect(app)
limiter = Limiter(key_func=get_remote_address, storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"))
limiter.init_app(app)

MAX_YAML_BYTES = 65536

config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
try:
    with open(config_path, "r", encoding="utf-8") as f:
        configs = yaml.safe_load(f)
except FileNotFoundError:
    configs = {}


YAML_TEMPLATES = {
    "static-react": {
        "title": "Static React/Web app",
        "description": "Public web frontend using automatic provider selection.",
        "yaml": """app:
  name: static-react-web
  environment: production
  type: static-web
selection:
  mode: auto
deployment:
  type: container
  image: dockertalha19/expense-tracker-react:latest
  port: 80
resources:
  cpu: 1
  memory: 512Mi
  min_instances: 0
  max_instances: 1
requirements:
  max_monthly_cost_usd: 20
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
""",
    },
    "fastapi-api": {
        "title": "FastAPI API",
        "description": "Backend API container with /health endpoint.",
        "yaml": """app:
  name: fyp-books-api
  environment: production
  type: api
selection:
  mode: auto
deployment:
  type: container
  image: dockertalha19/fyp-books-api:latest
  port: 8000
health_check: /health
resources:
  cpu: 1
  memory: 1Gi
  min_instances: 0
  max_instances: 1
requirements:
  max_monthly_cost_usd: 20
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
""",
    },
    "ml-api": {
        "title": "ML API",
        "description": "Small ML-style FastAPI container for demo inference.",
        "yaml": """app:
  name: fyp-ml-api
  environment: production
  type: ml-api
selection:
  mode: auto
deployment:
  type: container
  image: dockertalha19/fyp-ml-api:latest
  port: 8000
health_check: /health
resources:
  cpu: 1
  memory: 1Gi
  min_instances: 0
  max_instances: 1
requirements:
  max_monthly_cost_usd: 20
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
""",
    },
    "manual-aws": {
        "title": "Manual AWS",
        "description": "Force AWS EC2 Docker if AWS satisfies requirements.",
        "yaml": """app:
  name: manual-aws-api
  environment: production
  type: api
selection:
  mode: manual
  provider: AWS
deployment:
  type: container
  image: dockertalha19/fyp-books-api:latest
  port: 8000
health_check: /health
requirements:
  max_monthly_cost_usd: 30
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
""",
    },
    "manual-azure": {
        "title": "Manual Azure",
        "description": "Force Azure Container Apps if Azure satisfies requirements.",
        "yaml": """app:
  name: manual-azure-api
  environment: production
  type: api
selection:
  mode: manual
  provider: Azure
deployment:
  type: container
  image: dockertalha19/fyp-books-api:latest
  port: 8000
health_check: /health
requirements:
  max_monthly_cost_usd: 30
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
""",
    },
    "manual-gcp": {
        "title": "Manual GCP",
        "description": "Force GCP Cloud Run if GCP satisfies requirements.",
        "yaml": """app:
  name: manual-gcp-api
  environment: production
  type: api
selection:
  mode: manual
  provider: GCP
deployment:
  type: container
  image: dockertalha19/fyp-books-api:latest
  port: 8000
health_check: /health
requirements:
  max_monthly_cost_usd: 20
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
""",
    },
    "auto": {
        "title": "Auto provider selection",
        "description": "Let the decision engine choose the highest-scoring eligible provider.",
        "yaml": """app:
  name: auto-provider-api
  environment: production
  type: api
selection:
  mode: auto
deployment:
  type: container
  image: dockertalha19/fyp-books-api:latest
  port: 8000
health_check: /health
requirements:
  max_monthly_cost_usd: 20
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
""",
    },
}


DEMO_SCENARIOS = [
    {
        "title": "Static Web App",
        "name": "Expense Tracker React",
        "image": "dockertalha19/expense-tracker-react:latest",
        "port": 80,
        "health": "/",
        "template": "static-react",
        "story": "A small SME expense tracker frontend needs a public URL without hand-configuring cloud consoles.",
    },
    {
        "title": "Backend API",
        "name": "FastAPI Books API",
        "image": "dockertalha19/fyp-books-api:latest",
        "port": 8000,
        "health": "/health",
        "template": "fastapi-api",
        "story": "A backend service needs cost-aware provider selection and a health-checked endpoint.",
    },
    {
        "title": "ML API",
        "name": "FYP ML API",
        "image": "dockertalha19/fyp-ml-api:latest",
        "port": 8000,
        "health": "/health",
        "template": "ml-api",
        "story": "A lightweight ML inference API needs a repeatable dry-run deployment plan for demo review.",
    },
]


PROVIDERS = ["AWS", "Azure", "GCP"]


CLOUD_ACCOUNT_FIELDS = {
    "AWS": [
        {"name": "AWS_ACCESS_KEY_ID", "label": "AWS Access Key ID", "required": True, "secret": True},
        {"name": "AWS_SECRET_ACCESS_KEY", "label": "AWS Secret Access Key", "required": True, "secret": True},
        {"name": "AWS_REGION", "label": "AWS Region", "required": True},
        {"name": "AWS_AMI_ID", "label": "AWS AMI ID", "required": False},
        {"name": "AWS_INSTANCE_TYPE", "label": "AWS Instance Type", "required": False, "default": "t3.micro"},
        {"name": "AWS_KEY_NAME", "label": "AWS Key Name", "required": False},
        {"name": "AWS_SECURITY_GROUP_ID", "label": "AWS Security Group ID", "required": False},
        {"name": "AWS_SUBNET_ID", "label": "AWS Subnet ID", "required": False},
    ],
    "Azure": [
        {"name": "AZURE_TENANT_ID", "label": "Azure Tenant ID", "required": True, "secret": True},
        {"name": "AZURE_CLIENT_ID", "label": "Azure Client ID", "required": True, "secret": True},
        {"name": "AZURE_CLIENT_SECRET", "label": "Azure Client Secret", "required": True, "secret": True},
        {"name": "AZURE_SUBSCRIPTION_ID", "label": "Azure Subscription ID", "required": True},
        {"name": "AZURE_RESOURCE_GROUP", "label": "Azure Resource Group", "required": True},
        {"name": "AZURE_LOCATION", "label": "Azure Location", "required": True, "default": "eastus"},
        {"name": "AZURE_CONTAINERAPP_ENV", "label": "Azure Container Apps Environment", "required": True},
    ],
    "GCP": [
        {"name": "GCP_PROJECT_ID", "label": "GCP Project ID", "required": True},
        {"name": "GCP_REGION", "label": "GCP Region", "required": True, "default": "asia-south1"},
        {"name": "GCP_PLATFORM", "label": "GCP Platform", "required": True, "default": "managed"},
        {"name": "GCP_SERVICE_ACCOUNT_JSON", "label": "GCP Service Account JSON", "required": True, "secret": True, "textarea": True},
    ],
}


@app.context_processor
def inject_portal_context():
    return {
        "oauth_providers": oauth_status(),
        "safety_flags": _safety_flags(),
        "status_class": _status_class,
        "format_dt": _format_dt,
        "csrf_token": generate_csrf,
        "deployment_timeline": build_deployment_timeline,
    }


@app.before_request
def attach_request_id():
    g.request_id = uuid4().hex


@app.after_request
def add_request_id(response):
    response.headers["X-Request-ID"] = getattr(g, "request_id", uuid4().hex)
    return response


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role != "admin":
            abort(403)
        return func(*args, **kwargs)

    return wrapper


SECRET_METADATA_MARKERS = ("SECRET", "TOKEN", "PASSWORD", "PRIVATE_KEY", "CREDENTIAL", "ACCESS_KEY", "REFRESH_TOKEN")


def record_audit_event(
    action: str,
    entity_type: str = "",
    entity_id: str = "",
    provider: str = "",
    message: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
) -> None:
    if user_id is None and has_request_context() and current_user.is_authenticated:
        user_id = current_user.id
    log = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        provider=provider or None,
        message=message,
        metadata_json=_safe_audit_metadata(metadata or {}),
        request_id=getattr(g, "request_id", None) if has_request_context() else None,
    )
    db.session.add(log)
    db.session.commit()


def _safe_audit_metadata(value):
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            key_string = str(key)
            if _looks_secret_key(key_string):
                safe[key_string] = "[redacted]"
            else:
                safe[key_string] = _safe_audit_metadata(item)
        return safe
    if isinstance(value, list):
        return [_safe_audit_metadata(item) for item in value]
    if isinstance(value, str) and _looks_secret_value(value):
        return "[redacted]"
    return value


def _looks_secret_key(key: str) -> bool:
    key_upper = key.upper()
    return any(marker in key_upper for marker in SECRET_METADATA_MARKERS)


def _looks_secret_value(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if "-----BEGIN" in stripped or "PRIVATE KEY" in stripped:
        return True
    return False


@app.route("/", methods=["GET"])
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        errors = _registration_errors(name, email, password)
        if not errors and User.query.filter_by(email=email).first():
            errors.append("An account with this email already exists.")
        if errors:
            return render_template("register.html", errors=errors, name=name, email=email), 400
        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
            auth_provider="password",
            email_verified=False,
            last_login_at=datetime.utcnow(),
        )
        db.session.add(user)
        db.session.commit()
        record_audit_event(
            "user_registered",
            entity_type="user",
            entity_id=str(user.id),
            user_id=user.id,
            message="User registered with email/password.",
        )
        login_user(user)
        return redirect(url_for("dashboard"))
    return render_template("register.html", errors=[])


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.password_hash or not check_password_hash(user.password_hash, password):
            return render_template("login.html", error="Invalid email or password.", email=email), 401
        user.last_login_at = datetime.utcnow()
        db.session.commit()
        login_user(user)
        record_audit_event(
            "user_login",
            entity_type="user",
            entity_id=str(user.id),
            user_id=user.id,
            message="User logged in with email/password.",
        )
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/auth/<provider>", methods=["GET"])
def oauth_start(provider):
    return begin_oauth(provider)


@app.route("/auth/<provider>/callback", methods=["GET"])
def oauth_callback(provider):
    try:
        user = complete_oauth(provider)
    except Exception:
        return render_template("login.html", error="OAuth login failed or is not configured."), 400
    record_audit_event(
        "oauth_login",
        entity_type="user",
        entity_id=str(user.id),
        provider=provider,
        user_id=user.id,
        message=f"User logged in with {provider}.",
    )
    return redirect(url_for("dashboard"))


@app.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("landing"))


@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    deployments = _user_deployments_query().all()
    analytics = _deployment_analytics(deployments)
    readiness = _provider_readiness_summary()
    return render_template("dashboard.html", analytics=analytics, latest=deployments[:5], readiness=readiness)


@app.route("/admin", methods=["GET"])
@login_required
@admin_required
def admin_dashboard():
    deployments = DeploymentRecord.query.order_by(DeploymentRecord.created_at.desc()).all()
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template(
        "admin.html",
        deployment_count=len(deployments),
        user_count=len(users),
        analytics=_deployment_analytics(deployments),
        latest=deployments[:10],
    )


@app.route("/admin/deployments", methods=["GET"])
@login_required
@admin_required
def admin_deployments():
    deployments = DeploymentRecord.query.order_by(DeploymentRecord.created_at.desc()).all()
    return render_template("admin_deployments.html", deployments=deployments)


@app.route("/admin/users", methods=["GET"])
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    deployment_counts = {
        user_id: count
        for user_id, count in db.session.query(DeploymentRecord.user_id, db.func.count(DeploymentRecord.id)).group_by(DeploymentRecord.user_id)
    }
    connected_counts = {
        user_id: count
        for user_id, count in db.session.query(CloudAccount.user_id, db.func.count(CloudAccount.id)).group_by(CloudAccount.user_id)
    }
    return render_template(
        "admin_users.html",
        users=users,
        deployment_counts=deployment_counts,
        connected_counts=connected_counts,
    )


@app.route("/audit", methods=["GET"])
@login_required
def audit_logs():
    query = AuditLog.query.order_by(AuditLog.created_at.desc())
    if current_user.role != "admin":
        query = query.filter_by(user_id=current_user.id)
    return render_template("audit.html", logs=query.limit(200).all())


@app.route("/deploy/new", methods=["GET", "POST"])
@login_required
def deploy_new():
    if request.method == "POST":
        return _handle_deploy_submission()
    template_key = request.args.get("template", "")
    prefilled_yaml = YAML_TEMPLATES.get(template_key, {}).get("yaml", "")
    return render_template(
        "deploy_new.html",
        prefilled_yaml=prefilled_yaml,
        selected_template=template_key,
        cloud_accounts=_cloud_account_summaries(current_user.id),
        quota=_deployment_quota_snapshot(current_user.id),
    )


@app.route("/deploy/wizard", methods=["GET", "POST"])
@login_required
def deploy_wizard():
    if request.method == "POST":
        deployment_config = _wizard_config_from_form(request.form)
        generated_yaml = yaml.safe_dump(deployment_config, sort_keys=False)
        result = deploy_app(
            deployment_config,
            cloud_accounts=_cloud_account_map(current_user.id),
            require_cloud_account=True,
        )
        result["billing_safety"] = _billing_safety_summary(current_user.id, result)
        record = _save_deployment_result(
            current_user.id,
            generated_yaml,
            result,
            request.form.get("auto_cleanup_after", "none"),
        )
        record_audit_event(
            "deployment_dry_run" if result.get("status") == "dry_run" else "deployment_requested",
            entity_type="deployment",
            entity_id=record.id,
            provider=record.execution_provider,
            message=f"Wizard deployment recorded with status {record.status}.",
            metadata={"status": record.status, "source": "wizard"},
        )
        return render_template("deploy_result.html", record=record, result=result)
    return render_template("deploy_wizard.html", quota=_deployment_quota_snapshot(current_user.id))


@app.route("/deploy", methods=["POST"])
@login_required
def deploy_legacy_post():
    return _handle_deploy_submission()


@app.route("/deployments", methods=["GET"])
@login_required
def deployments():
    return render_template("deployments.html", deployments=_user_deployments_query().all())


@app.route("/history", methods=["GET"])
@login_required
def history():
    return redirect(url_for("deployments"))


@app.route("/deployments/<deployment_id>", methods=["GET"])
@login_required
def deployment_detail(deployment_id):
    record = _owned_deployment_or_404(deployment_id)
    return render_template("deployment_detail.html", record=record, result=record.result_json or {})


@app.route("/deployments/<deployment_id>/confirm", methods=["POST"])
@login_required
def confirm_deployment(deployment_id):
    record = _owned_deployment_or_404(deployment_id)
    config = yaml.safe_load(record.yaml_content)
    preflight = deploy_app(
        config,
        execute=False,
        confirm_real_deployment=True,
        cloud_accounts=_cloud_account_map(current_user.id),
        require_cloud_account=True,
    )
    if preflight.get("status") in {"cloud_account_required", "provider_not_ready", "image_validation_failed", "blocked_by_safety_flag"}:
        record.apply_result(preflight, yaml_content=record.yaml_content)
        db.session.commit()
        record_audit_event(
            "deployment_real_requested",
            entity_type="deployment",
            entity_id=record.id,
            provider=record.execution_provider,
            message=f"Real deployment blocked with status {record.status}.",
            metadata={"status": record.status},
        )
        return render_template("deploy_result.html", record=record, result=preflight)

    safety_block = _real_deployment_safety_block(
        current_user.id,
        preflight,
        billing_acknowledged=request.form.get("billing_acknowledgement") == "yes",
    )
    if safety_block:
        record.apply_result(safety_block, yaml_content=record.yaml_content)
        db.session.commit()
        action = "deployment_blocked_by_billing_ack" if record.status == "blocked_by_billing_ack" else "deployment_blocked_by_quota"
        record_audit_event(
            action,
            entity_type="deployment",
            entity_id=record.id,
            provider=record.execution_provider,
            message=safety_block.get("deployment", {}).get("message", "Real deployment blocked by safety policy."),
            metadata={"status": record.status},
        )
        return render_template("deploy_result.html", record=record, result=safety_block)

    queue_result = enqueue_deployment(record.id)
    result = dict(record.result_json or {})
    result["status"] = "queued" if queue_result.queued else "failed"
    result["deployment_mode"] = "real"
    result.setdefault("deployment", {})["status"] = result["status"]
    result["deployment"]["message"] = queue_result.message
    result["job_id"] = queue_result.job_id
    result["billing_safety"] = _billing_safety_summary(current_user.id, preflight)
    record.apply_result(result, yaml_content=record.yaml_content)
    db.session.commit()
    record_audit_event(
        "deployment_real_requested",
        entity_type="deployment",
        entity_id=record.id,
        provider=record.execution_provider,
        message="Real deployment queued for background execution.",
        metadata={"status": record.status, "job_id": queue_result.job_id},
    )
    return render_template("deploy_result.html", record=record, result=result)


@app.route("/deployments/<deployment_id>/delete", methods=["POST"])
@login_required
def delete_saved_deployment(deployment_id):
    record = _owned_deployment_or_404(deployment_id)
    account = _cloud_account_for_user(current_user.id, record.execution_provider)
    delete_result = cleanup_deployment_record(
        record.to_cleanup_record(),
        cloud_account=account,
        require_cloud_account=True,
    )
    result = dict(record.result_json or {})
    result["cleanup_result"] = delete_result
    result["status"] = delete_result["status"]
    result.setdefault("deployment", {})["status"] = delete_result["status"]
    record.apply_result(result)
    record.cleanup_status = delete_result["status"]
    db.session.commit()
    record_audit_event(
        "deployment_deleted",
        entity_type="deployment",
        entity_id=record.id,
        provider=record.execution_provider,
        message=delete_result.get("message", "Deployment cleanup requested."),
        metadata={"status": delete_result.get("status")},
    )
    flash(delete_result["message"])
    return redirect(url_for("deployment_detail", deployment_id=record.id))


@app.route("/deployments/<deployment_id>/refresh", methods=["POST"])
@login_required
def refresh_deployment(deployment_id):
    record = _owned_deployment_or_404(deployment_id)
    health_result = refresh_deployment_health(record)
    record.last_checked_at = datetime.utcnow()
    record.health_status = health_result.get("result") or health_result.get("status")
    record.health_result_json = health_result
    result = dict(record.result_json or {})
    result["health_check"] = health_result
    record.result_json = result
    db.session.commit()
    flash(health_result.get("message", "Deployment status refreshed."))
    return redirect(url_for("deployment_detail", deployment_id=record.id))


@app.route("/deployments/<deployment_id>/status", methods=["GET"])
@login_required
def deployment_status(deployment_id):
    record = _owned_deployment_or_404(deployment_id)
    return jsonify(
        {
            "status": record.status,
            "health_status": record.health_status,
            "public_url": record.endpoint,
            "message": (record.result_json or {}).get("deployment", {}).get("message"),
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }
    )


@app.route("/deployments/<deployment_id>/cleanup-if-due", methods=["POST"])
@login_required
def cleanup_if_due(deployment_id):
    record = _owned_deployment_or_404(deployment_id)
    if not record.auto_cleanup_at or record.auto_cleanup_at > datetime.utcnow():
        flash("Cleanup is not due for this deployment.")
        return redirect(url_for("deployment_detail", deployment_id=record.id))
    if record.deployment_mode != "real":
        flash("Dry-run deployments do not create resources and do not require cleanup.")
        return redirect(url_for("deployment_detail", deployment_id=record.id))
    return delete_saved_deployment(deployment_id)


@app.route("/deployment-report/<deployment_id>", methods=["GET"])
@login_required
def deployment_report(deployment_id):
    record = _owned_deployment_or_404(deployment_id)
    return Response(_report_from_record(record), mimetype="text/plain")


@app.route("/providers", methods=["GET"])
@login_required
def providers():
    readiness = _provider_readiness_summary(include_bootstrap=True)
    return render_template("providers.html", readiness=readiness, safety_flags=_safety_flags())


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            name = request.form.get("name", "").strip()
            theme = request.form.get("theme_preference", "system")
            if name:
                current_user.name = name
            if theme in {"system", "light", "dark"}:
                current_user.theme_preference = theme
            db.session.commit()
            flash("Settings updated.")
        elif action == "password":
            if not current_user.password_hash:
                flash("Password is managed by your OAuth provider.")
            else:
                current_password = request.form.get("current_password", "")
                new_password = request.form.get("new_password", "")
                if not check_password_hash(current_user.password_hash, current_password):
                    flash("Current password is incorrect.")
                elif len(new_password) < 8:
                    flash("New password must be at least 8 characters.")
                else:
                    current_user.password_hash = generate_password_hash(new_password)
                    db.session.commit()
                    flash("Password changed.")
        return redirect(url_for("settings"))
    return render_template("settings.html")


@app.route("/settings/theme", methods=["POST"])
@login_required
def save_theme():
    payload = request.get_json(silent=True) or request.form
    theme = payload.get("theme", "system")
    if theme in {"system", "light", "dark"}:
        current_user.theme_preference = theme
        db.session.commit()
    return jsonify({"theme": current_user.theme_preference})


@app.route("/templates", methods=["GET"])
@login_required
def templates_library():
    return render_template("templates.html", templates=YAML_TEMPLATES)


@app.route("/demo-scenarios", methods=["GET"])
@login_required
def demo_scenarios():
    return render_template("demo_scenarios.html", scenarios=DEMO_SCENARIOS, templates=YAML_TEMPLATES)


@app.route("/production-readiness", methods=["GET"])
@login_required
def production_readiness():
    implemented = [
        "authentication",
        "OAuth",
        "encrypted cloud credentials",
        "user-owned cloud accounts",
        "dry-run",
        "approval gate",
        "provider readiness",
        "billing acknowledgement",
        "quotas",
        "deployment reports",
        "cleanup",
        "audit logs",
        "background job support",
    ]
    future_work = [
        "managed secrets",
        "cloud role-based auth instead of raw keys",
        "payment/subscription billing",
        "team workspaces",
        "advanced monitoring",
        "SLA/error budgets",
        "Kubernetes support",
    ]
    return render_template(
        "production_readiness.html",
        implemented=implemented,
        future_work=future_work,
        phase13_skipped=True,
    )


@app.route("/cloud/accounts", methods=["GET"])
@login_required
def cloud_accounts():
    readiness = _provider_readiness_summary(include_bootstrap=False)
    return render_template(
        "cloud_accounts.html",
        providers=PROVIDERS,
        accounts=_cloud_account_summaries(current_user.id),
        readiness_by_provider={item["provider"]: item["readiness"] for item in readiness},
        encryption_configured=is_encryption_configured(),
    )


@app.route("/cloud/<provider>/connect", methods=["GET", "POST"])
@login_required
def connect_cloud_account(provider):
    provider_name = _normalize_provider(provider)
    if provider_name not in CLOUD_ACCOUNT_FIELDS:
        return redirect(url_for("cloud_accounts"))

    account = _cloud_account_for_user(current_user.id, provider_name)
    if request.method == "POST":
        errors, credentials = _cloud_account_credentials_from_form(provider_name)
        display_name = request.form.get("display_name", "").strip() or f"{provider_name} account"
        if not is_encryption_configured():
            errors.append("Credential encryption key is not configured.")
        if errors:
            return render_template(
                "cloud_account_form.html",
                provider=provider_name,
                fields=CLOUD_ACCOUNT_FIELDS[provider_name],
                errors=errors,
                account=account,
            ), 400

        account = account or CloudAccount(user_id=current_user.id, provider=provider_name)
        account.display_name = display_name
        try:
            account.set_credentials(credentials)
            db.session.add(account)
            db.session.commit()
            record_audit_event(
                "cloud_account_connected",
                entity_type="cloud_account",
                entity_id=str(account.id),
                provider=provider_name,
                message=f"{provider_name} cloud account connected or updated.",
                metadata={"display_name": display_name},
            )
        except (RuntimeError, ValueError) as exc:
            db.session.rollback()
            return render_template(
                "cloud_account_form.html",
                provider=provider_name,
                fields=CLOUD_ACCOUNT_FIELDS[provider_name],
                errors=[str(exc)],
                account=account,
            ), 400
        except IntegrityError:
            db.session.rollback()
            return render_template(
                "cloud_account_form.html",
                provider=provider_name,
                fields=CLOUD_ACCOUNT_FIELDS[provider_name],
                errors=["Only one account per provider is allowed for each user."],
                account=account,
            ), 400

        flash(f"{provider_name} cloud account saved. Secret fields were cleared after save.")
        return redirect(url_for("cloud_accounts"))

    return render_template(
        "cloud_account_form.html",
        provider=provider_name,
        fields=CLOUD_ACCOUNT_FIELDS[provider_name],
        errors=[],
        account=account,
    )


@app.route("/cloud/accounts/<int:account_id>/delete", methods=["POST"])
@login_required
def delete_cloud_account(account_id):
    account = CloudAccount.query.filter_by(id=account_id, user_id=current_user.id).first_or_404()
    provider_name = account.provider
    db.session.delete(account)
    db.session.commit()
    record_audit_event(
        "cloud_account_deleted",
        entity_type="cloud_account",
        entity_id=str(account_id),
        provider=provider_name,
        message=f"{provider_name} cloud account disconnected.",
    )
    flash(f"{provider_name} cloud account disconnected.")
    return redirect(url_for("cloud_accounts"))


def _handle_deploy_submission():
    uploaded_file = request.files.get("config_file")
    textarea_content = request.form.get("yaml_content", "").strip()
    if textarea_content:
        if len(textarea_content.encode("utf-8")) > MAX_YAML_BYTES:
            return _deploy_form_error("YAML input is too large. Maximum allowed size is 64 KB.", textarea_content)
        yaml_content = textarea_content
        if uploaded_file and uploaded_file.filename:
            flash("Textarea YAML was used because both textarea and file upload were provided.")
    elif uploaded_file and uploaded_file.filename:
        try:
            raw_content = uploaded_file.read(MAX_YAML_BYTES + 1)
            if len(raw_content) > MAX_YAML_BYTES:
                return _deploy_form_error("YAML input is too large. Maximum allowed size is 64 KB.")
            yaml_content = raw_content.decode("utf-8")
        except Exception as exc:
            return _deploy_form_error(f"Could not read YAML file: {exc}")
    else:
        return _deploy_form_error("Provide a YAML file or paste YAML content.")

    try:
        deployment_config = yaml.safe_load(yaml_content)
    except Exception as exc:
        return _deploy_form_error(f"Invalid YAML file: {exc}", yaml_content)

    _apply_cloud_selection_override(deployment_config, request.form.get("cloud_selection", "yaml"))
    effective_yaml = yaml.safe_dump(deployment_config, sort_keys=False)
    result = deploy_app(
        deployment_config,
        cloud_accounts=_cloud_account_map(current_user.id),
        require_cloud_account=True,
    )
    result["billing_safety"] = _billing_safety_summary(current_user.id, result)
    record = _save_deployment_result(
        current_user.id,
        effective_yaml,
        result,
        request.form.get("auto_cleanup_after", "none"),
    )
    if result.get("status") == "dry_run":
        action = "deployment_dry_run"
    elif result.get("status") == "approval_required":
        action = "deployment_real_requested"
    else:
        action = "deployment_requested"
    record_audit_event(
        action,
        entity_type="deployment",
        entity_id=record.id,
        provider=record.execution_provider,
        message=f"Deployment flow recorded with status {record.status}.",
        metadata={"status": record.status, "deployment_mode": record.deployment_mode},
    )
    return render_template("deploy_result.html", record=record, result=result)


def _deploy_form_error(message: str, prefilled_yaml: str = ""):
    if current_user.is_authenticated:
        record_audit_event(
            "security_validation_failed",
            entity_type="deployment",
            message=message,
            metadata={"reason": message},
        )
    return render_template(
        "deploy_new.html",
        errors=[message],
        prefilled_yaml=prefilled_yaml,
        cloud_accounts=_cloud_account_summaries(current_user.id),
        quota=_deployment_quota_snapshot(current_user.id),
    ), 400


def _save_deployment_result(user_id: int, yaml_content: str, result: Dict[str, Any], cleanup_after: str = "none") -> DeploymentRecord:
    record = DeploymentRecord(user_id=user_id, yaml_content=yaml_content, result_json=result)
    record.apply_result(result, yaml_content=yaml_content)
    delta = auto_cleanup_delta(cleanup_after)
    if delta:
        record.auto_cleanup_at = datetime.utcnow() + delta
        record.cleanup_status = "not_required" if record.deployment_mode != "real" else "scheduled"
    db.session.add(record)
    db.session.commit()
    return record


def _owned_deployment_or_404(deployment_id: str) -> DeploymentRecord:
    return DeploymentRecord.query.filter_by(id=deployment_id, user_id=current_user.id).first_or_404()


def _user_deployments_query():
    return DeploymentRecord.query.filter_by(user_id=current_user.id).order_by(DeploymentRecord.created_at.desc())


def _registration_errors(name: str, email: str, password: str) -> list[str]:
    errors = []
    if not name:
        errors.append("Name is required.")
    if not email or "@" not in email:
        errors.append("A valid email is required.")
    if len(password) < 6:
        errors.append("Password must be at least 6 characters.")
    return errors


def _apply_cloud_selection_override(deployment_config, cloud_selection):
    if not isinstance(deployment_config, dict):
        return
    selection_map = {
        "auto": {"mode": "auto"},
        "AWS": {"mode": "manual", "provider": "AWS"},
        "Azure": {"mode": "manual", "provider": "Azure"},
        "GCP": {"mode": "manual", "provider": "GCP"},
    }
    override = selection_map.get(cloud_selection)
    if override:
        deployment_config["selection"] = override


def _wizard_config_from_form(form) -> Dict[str, Any]:
    provider_mode = form.get("provider_mode", "auto")
    app_name = form.get("app_name", "wizard-api").strip()
    public_access = form.get("public_access", "true") == "true"
    selection = {"mode": "auto"}
    if provider_mode in {"AWS", "Azure", "GCP"}:
        selection = {"mode": "manual", "provider": provider_mode}

    return {
        "app": {
            "name": app_name,
            "environment": form.get("environment", "production"),
            "type": form.get("app_type", "api"),
        },
        "services": [
            {
                "name": app_name,
                "image": form.get("image", "").strip(),
                "port": int(form.get("port", "8000") or 8000),
                "public": public_access,
            }
        ],
        "requirements": {
            "max_monthly_cost_usd": float(form.get("budget", "30") or 30),
            "min_uptime_percent": float(form.get("uptime", "99.9") or 99.9),
            "preferred_region": form.get("preferred_region", "asia"),
            "public_access": public_access,
        },
        "selection": selection,
        "health_check": form.get("health_check", "/health") or "/",
    }


def _cloud_account_for_user(user_id: int, provider: Optional[str]):
    provider_name = _normalize_provider(provider)
    if not provider_name:
        return None
    return CloudAccount.query.filter_by(user_id=user_id, provider=provider_name).first()


def _cloud_account_map(user_id: int) -> Dict[str, CloudAccount]:
    return {account.provider: account for account in CloudAccount.query.filter_by(user_id=user_id).all()}


def _cloud_account_summaries(user_id: int) -> Dict[str, Dict[str, Any]]:
    connected = _cloud_account_map(user_id)
    summaries = {}
    for provider in PROVIDERS:
        account = connected.get(provider)
        if account:
            summaries[provider] = account.masked_summary()
        else:
            summaries[provider] = {
                "provider": provider,
                "connected": False,
                "status": "not_connected",
                "display_name": provider,
                "region": "",
                "project_id": "",
                "subscription_id": "",
                "last_checked_at": None,
            }
    return summaries


def _cloud_account_credentials_from_form(provider: str) -> tuple[list[str], Dict[str, str]]:
    errors = []
    credentials = {}
    for field in CLOUD_ACCOUNT_FIELDS[provider]:
        name = field["name"]
        value = request.form.get(name, "").strip()
        if not value and field.get("default"):
            value = field["default"]
        if field.get("required") and not value:
            errors.append(f"{field['label']} is required.")
        credentials[name] = value
    return errors, credentials


def _normalize_provider(provider: Optional[str]) -> Optional[str]:
    if not provider:
        return None
    return {"aws": "AWS", "azure": "Azure", "gcp": "GCP"}.get(str(provider).strip().lower(), provider)


def _provider_readiness_summary(include_bootstrap: bool = False):
    config = _readiness_probe_config()
    summary = []
    accounts = _cloud_account_map(current_user.id) if current_user.is_authenticated else {}
    for provider in ["AWS", "Azure", "GCP"]:
        readiness = check_provider_readiness(
            provider,
            config,
            cloud_account=accounts.get(provider),
            require_cloud_account=True,
        )
        item = {"provider": provider, "readiness": readiness}
        if accounts.get(provider):
            item["account"] = accounts[provider].masked_summary()
        if include_bootstrap or not readiness.get("ready"):
            item["bootstrap_plan"] = generate_provider_bootstrap_plan(provider)
        summary.append(item)
    return summary


def _readiness_probe_config() -> Dict[str, Any]:
    raw = {
        "app": {"name": "readiness-probe", "environment": "production", "type": "api"},
        "deployment": {"type": "container", "image": "dockertalha19/fyp-books-api:latest", "port": 80},
        "requirements": {
            "max_monthly_cost_usd": 30,
            "min_uptime_percent": 99.9,
            "preferred_region": "asia",
            "public_access": True,
        },
    }
    try:
        return validate_config(raw)
    except ConfigValidationError:
        return raw


ACTIVE_REAL_STATUSES = {"queued", "running", "deployed", "cleanup_required"}
REAL_ATTEMPT_STATUSES = {"queued", "running", "deployed", "failed", "cleanup_required", "deleted", "delete_failed"}


def _deployment_quota_snapshot(user_id: int) -> Dict[str, Any]:
    active_limit = int(app.config.get("MAX_ACTIVE_DEPLOYMENTS_PER_USER", 3))
    daily_limit = int(app.config.get("MAX_REAL_DEPLOYMENTS_PER_DAY", 5))
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    active_count = DeploymentRecord.query.filter_by(user_id=user_id, deployment_mode="real").filter(
        DeploymentRecord.status.in_(ACTIVE_REAL_STATUSES)
    ).count()
    real_today_count = DeploymentRecord.query.filter_by(user_id=user_id, deployment_mode="real").filter(
        DeploymentRecord.created_at >= today_start,
        DeploymentRecord.status.in_(REAL_ATTEMPT_STATUSES),
    ).count()
    return {
        "active_count": active_count,
        "active_limit": active_limit,
        "real_today_count": real_today_count,
        "real_today_limit": daily_limit,
        "monthly_cost_limit_usd": float(app.config.get("MAX_MONTHLY_COST_LIMIT_USD", 50)),
    }


def _billing_safety_summary(user_id: int, result: Dict[str, Any]) -> Dict[str, Any]:
    summary = _deployment_quota_snapshot(user_id)
    summary["estimated_monthly_cost_usd"] = _selected_estimated_cost(result)
    summary["billing_warning"] = "Real deployments create resources in your connected cloud account and may incur charges."
    return summary


def _real_deployment_safety_block(user_id: int, preflight: Dict[str, Any], billing_acknowledged: bool) -> Optional[Dict[str, Any]]:
    if preflight.get("deployment_mode") != "real":
        return None
    if not billing_acknowledged:
        return _blocked_deployment_result(
            preflight,
            "blocked_by_billing_ack",
            "Real deployment requires billing acknowledgement before resources can be queued.",
            user_id,
        )

    quota = _deployment_quota_snapshot(user_id)
    if quota["active_count"] >= quota["active_limit"]:
        return _blocked_deployment_result(
            preflight,
            "blocked_by_quota",
            f"Active real deployment quota exceeded ({quota['active_count']}/{quota['active_limit']}).",
            user_id,
        )
    if quota["real_today_count"] >= quota["real_today_limit"]:
        return _blocked_deployment_result(
            preflight,
            "blocked_by_quota",
            f"Daily real deployment quota exceeded ({quota['real_today_count']}/{quota['real_today_limit']}).",
            user_id,
        )

    estimated_cost = _selected_estimated_cost(preflight)
    if estimated_cost is not None and estimated_cost > quota["monthly_cost_limit_usd"]:
        return _blocked_deployment_result(
            preflight,
            "blocked_by_cost_limit",
            (
                f"Estimated monthly cost ${estimated_cost:.2f} exceeds the platform safety limit "
                f"of ${quota['monthly_cost_limit_usd']:.2f}."
            ),
            user_id,
        )
    return None


def _blocked_deployment_result(result: Dict[str, Any], status: str, message: str, user_id: int) -> Dict[str, Any]:
    blocked = dict(result)
    blocked["status"] = status
    blocked["billing_safety"] = _billing_safety_summary(user_id, result)
    blocked.setdefault("deployment", {})
    blocked["deployment"] = dict(blocked["deployment"])
    blocked["deployment"]["status"] = status
    blocked["deployment"]["message"] = message
    blocked.setdefault("diagnostics", {})
    blocked["diagnostics"] = dict(blocked["diagnostics"])
    blocked["diagnostics"]["next_steps"] = [message]
    return blocked


def _selected_estimated_cost(result: Dict[str, Any]) -> Optional[float]:
    decision = result.get("decision", {})
    selected_provider = decision.get("selected_provider") or decision.get("execution_provider")
    for provider in decision.get("evaluated_providers", []):
        if provider.get("provider") == selected_provider:
            try:
                return float(provider.get("estimated_cost_usd"))
            except (TypeError, ValueError):
                return None
    return None


def build_deployment_timeline(result: Dict[str, Any]) -> list[Dict[str, str]]:
    status = result.get("status") or "unknown"
    deployment_mode = result.get("deployment_mode") or "dry_run"
    health = result.get("health_check", {})
    deployment = result.get("deployment", {})
    timeline = [
        {"label": "YAML received", "status": "completed", "message": "Deployment configuration was submitted."},
        {
            "label": "Validation passed" if not result.get("validation_errors") else "Validation failed",
            "status": "completed" if not result.get("validation_errors") else "failed",
            "message": "YAML schema and safety checks completed.",
        },
        {
            "label": "Docker image validated",
            "status": "completed" if result.get("docker_image_validation", {}).get("valid", True) else "failed",
            "message": "Docker image input was checked without contacting a registry unless enabled.",
        },
        {"label": "Provider evaluation completed", "status": "completed", "message": result.get("decision", {}).get("reason", "")},
        {
            "label": "Cloud account checked",
            "status": "completed" if result.get("cloud_account", {}).get("connected") else "warning",
            "message": result.get("cloud_account", {}).get("message", "Cloud account status recorded."),
        },
    ]
    if deployment_mode == "real":
        if status in {"queued", "running", "deployed", "failed", "cleanup_required"}:
            timeline.append({"label": "Billing acknowledgement confirmed", "status": "completed", "message": "User confirmed billable resource acknowledgement."})
        if status in {"queued", "running", "deployed", "failed", "cleanup_required"}:
            timeline.append({"label": "Deployment queued", "status": "completed", "message": deployment.get("message", "Background job queued.")})
        if status in {"running", "deployed", "failed", "cleanup_required"}:
            timeline.append({"label": "Deployment running", "status": "completed" if status in {"deployed", "failed", "cleanup_required"} else "running", "message": "Provider execution started."})
    else:
        timeline.append({"label": "Dry-run plan generated", "status": "completed", "message": "Generated provider-specific deployment plan."})
        timeline.append({"label": "No cloud resources created", "status": "completed", "message": "Dry-run mode does not execute cloud commands."})

    if result.get("public_endpoints"):
        timeline.append({"label": "Public URL generated", "status": "completed", "message": result["public_endpoints"][0].get("url", "")})
    if health.get("result") in {"passed", "failed"}:
        timeline.append({"label": f"Health check {health.get('result')}", "status": health.get("result"), "message": health.get("message", "")})
    if result.get("cleanup_result"):
        timeline.append({"label": "Cleanup completed", "status": result["cleanup_result"].get("status", "completed"), "message": result["cleanup_result"].get("message", "")})
    if status in {"failed", "cleanup_required"} and not health.get("result"):
        timeline.append({"label": "Deployment failed", "status": "failed", "message": deployment.get("message", "Deployment did not complete successfully.")})
    return timeline


def _deployment_analytics(records):
    by_provider: Dict[str, int] = {}
    by_app_type: Dict[str, int] = {}
    for record in records:
        by_provider[record.execution_provider or "None"] = by_provider.get(record.execution_provider or "None", 0) + 1
        by_app_type[record.app_type or "api"] = by_app_type.get(record.app_type or "api", 0) + 1
    return {
        "total": len(records),
        "dry_run": sum(1 for record in records if record.status == "dry_run"),
        "real": sum(1 for record in records if record.deployment_mode == "real"),
        "deployed": sum(1 for record in records if record.status == "deployed"),
        "failed": sum(1 for record in records if record.status in {"failed", "configuration_error", "provider_not_ready", "image_validation_failed", "cloud_account_required"}),
        "deleted": sum(1 for record in records if record.status in {"deleted", "delete_skipped"}),
        "by_provider": by_provider,
        "by_app_type": by_app_type,
    }


def refresh_deployment_health(record: DeploymentRecord) -> Dict[str, Any]:
    if record.status in {"dry_run", "deleted", "delete_skipped", "failed"} or record.deployment_mode != "real":
        return {
            "result": "skipped",
            "status": "skipped",
            "url": record.endpoint,
            "status_code": None,
            "response_time_ms": None,
            "attempts": 0,
            "message": "Refresh skipped because this record does not represent an active real deployment.",
        }
    if not record.endpoint:
        return {
            "result": "skipped",
            "status": "skipped",
            "url": None,
            "status_code": None,
            "response_time_ms": None,
            "attempts": 0,
            "message": "Refresh skipped because no endpoint is stored.",
        }
    started = datetime.utcnow()
    try:
        response = requests.get(record.endpoint, timeout=5)
        elapsed = (datetime.utcnow() - started).total_seconds() * 1000
        result = "passed" if response.status_code < 400 else "failed"
        return {
            "result": result,
            "status": result,
            "url": record.endpoint,
            "status_code": response.status_code,
            "response_time_ms": round(elapsed, 2),
            "attempts": 1,
            "message": f"Endpoint returned HTTP {response.status_code}.",
        }
    except requests.RequestException as exc:
        return {
            "result": "failed",
            "status": "failed",
            "url": record.endpoint,
            "status_code": None,
            "response_time_ms": None,
            "attempts": 1,
            "message": str(exc),
        }


def _report_from_record(record: DeploymentRecord) -> str:
    result = record.result_json or {}
    decision = result.get("decision", {})
    health = result.get("health_check", {})
    lines = [
        "Deployment Report",
        "=================",
        f"Timestamp: {record.created_at.isoformat() if record.created_at else 'N/A'}",
        f"App name: {record.app_name or 'N/A'}",
        f"App type: {record.app_type or 'N/A'}",
        f"Image: {record.image or 'N/A'}",
        f"Selected provider: {record.selected_provider or 'N/A'}",
        f"Execution provider: {record.execution_provider or 'N/A'}",
        f"Deployment mode: {record.deployment_mode or 'N/A'}",
        f"Status: {record.status or 'N/A'}",
        f"Endpoint: {record.endpoint or 'N/A'}",
        f"Cleanup status: {record.cleanup_status or 'N/A'}",
        f"Cloud account connected: {result.get('cloud_account', {}).get('connected', 'N/A')}",
        "",
        "Provider Evaluation:",
    ]
    for provider in decision.get("evaluated_providers", []):
        lines.append(
            f"- {provider.get('provider')}: eligible={provider.get('eligible')}, "
            f"cost=${provider.get('estimated_cost_usd')}/mo, uptime={provider.get('uptime_percent')}%, "
            f"score={provider.get('score')}"
        )
    lines.extend(
        [
            "",
            "Generated Commands:",
            *[
                f"- {command.get('command_string') or ' '.join(command.get('command', []))}"
                for command in result.get("generated_commands", [])
            ],
            "",
            "Health Check:",
            f"- Result: {health.get('result') or health.get('status', 'N/A')}",
            f"- Message: {health.get('message', 'N/A')}",
            "",
            "Readiness:",
            f"- Ready: {result.get('provider_readiness', {}).get('ready', 'N/A')}",
            "",
            "Docker Image Validation:",
            f"- Valid: {result.get('docker_image_validation', {}).get('valid', 'N/A')}",
        ]
    )
    return "\n".join(lines) + "\n"


def _safety_flags():
    return {
        "ENABLE_REAL_DEPLOYMENT": os.getenv("ENABLE_REAL_DEPLOYMENT", "false"),
        "ALLOW_AWS_DEPLOYMENT": os.getenv("ALLOW_AWS_DEPLOYMENT", "false"),
        "ALLOW_AZURE_DEPLOYMENT": os.getenv("ALLOW_AZURE_DEPLOYMENT", "false"),
        "ALLOW_GCP_DEPLOYMENT": os.getenv("ALLOW_GCP_DEPLOYMENT", "false"),
        "MODEL_B_USER_CLOUD_ACCOUNTS": os.getenv("MODEL_B_USER_CLOUD_ACCOUNTS", "true"),
        "ALLOW_ADMIN_CLOUD_FALLBACK": os.getenv("ALLOW_ADMIN_CLOUD_FALLBACK", "false"),
    }


def _status_class(status: Optional[str]) -> str:
    status = (status or "").lower()
    if status in {"deployed", "passed", "deleted"}:
        return "success"
    if status in {"dry_run", "approval_required", "blocked_by_safety_flag", "delete_skipped", "provider_not_ready", "cloud_account_required", "pending", "queued", "running", "blocked_by_billing_ack", "blocked_by_quota", "blocked_by_cost_limit"}:
        return "warning"
    if status in {"failed", "validation_failed", "configuration_error", "image_validation_failed", "delete_failed"}:
        return "danger"
    return ""


def _format_dt(value) -> str:
    if not value:
        return "N/A"
    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except AttributeError:
        return str(value)


@app.route("/health")
def health():
    return "OK"


@app.cli.command("cleanup-due")
def cleanup_due_command():
    count = 0
    for record in find_due_cleanups():
        account = _cloud_account_for_user(record.user_id, record.execution_provider)
        result = cleanup_deployment_record(record.to_cleanup_record(), cloud_account=account, require_cloud_account=True)
        payload = dict(record.result_json or {})
        payload["cleanup_result"] = result
        payload["status"] = result.get("status")
        record.apply_result(payload)
        record.cleanup_status = result.get("status")
        count += 1
    db.session.commit()
    click_message = f"Processed {count} due cleanup record(s)."
    try:
        import click

        click.echo(click_message)
    except Exception:
        logger.info(click_message)


@app.route("/apps")
def get_apps():
    return jsonify(list(configs.keys()))


@app.route("/config/<app_name>/<env>/<key>")
def get_config(app_name, env, key):
    try:
        return jsonify({key: configs[app_name][env][key]})
    except KeyError:
        return jsonify({"error": "Not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.getenv("FLASK_ENV") == "development")
