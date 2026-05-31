import os
from datetime import datetime
from typing import Any, Dict, Optional

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed in the project environment.
    def load_dotenv() -> None:
        return None

from config_schema import ConfigValidationError, validate_config
from deployment_history import load_deployment_history
from orchestrator import cleanup_deployment_record, deploy_app
from provider_bootstrap import generate_provider_bootstrap_plan
from provider_readiness import check_provider_readiness
from portal_models import DeploymentRecord, User, db


load_dotenv()

app = Flask(__name__, instance_relative_config=True)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(app.instance_path, 'orchestrator.db')}",
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
os.makedirs(app.instance_path, exist_ok=True)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."


config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
try:
    with open(config_path, "r", encoding="utf-8") as f:
        configs = yaml.safe_load(f)
except FileNotFoundError:
    configs = {}


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    if not user_id.isdigit():
        return None
    return db.session.get(User, int(user_id))


def init_database() -> None:
    with app.app_context():
        db.create_all()


init_database()


@app.route("/", methods=["GET"])
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
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
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for("dashboard"))

    return render_template("register.html", errors=[])


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            return render_template("login.html", error="Invalid email or password.", email=email), 401
        login_user(user)
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("landing"))


@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    deployments = _user_deployments_query().all()
    latest = deployments[:5]
    counts = {
        "total": len(deployments),
        "deployed": sum(1 for record in deployments if record.status == "deployed"),
        "failed": sum(1 for record in deployments if record.status in {"failed", "configuration_error", "provider_not_ready", "image_validation_failed"}),
        "dry_run": sum(1 for record in deployments if record.status == "dry_run"),
    }
    readiness = _provider_readiness_summary()
    return render_template("dashboard.html", counts=counts, latest=latest, readiness=readiness)


@app.route("/deploy/new", methods=["GET", "POST"])
@login_required
def deploy_new():
    if request.method == "POST":
        return _handle_deploy_submission()
    return render_template("deploy_new.html")


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
    result = deploy_app(config, confirm_real_deployment=True)
    record.apply_result(result, yaml_content=record.yaml_content)
    db.session.commit()
    return render_template("deploy_result.html", record=record, result=result)


@app.route("/deployments/<deployment_id>/delete", methods=["POST"])
@login_required
def delete_saved_deployment(deployment_id):
    record = _owned_deployment_or_404(deployment_id)
    delete_result = cleanup_deployment_record(record.to_cleanup_record())
    result = dict(record.result_json or {})
    result["cleanup_result"] = delete_result
    result["status"] = delete_result["status"]
    result.setdefault("deployment", {})["status"] = delete_result["status"]
    record.apply_result(result)
    db.session.commit()
    flash(delete_result["message"])
    return redirect(url_for("deployment_detail", deployment_id=record.id))


@app.route("/deployment-report/<deployment_id>", methods=["GET"])
@login_required
def deployment_report(deployment_id):
    record = _owned_deployment_or_404(deployment_id)
    return Response(_report_from_record(record), mimetype="text/plain")


@app.route("/providers", methods=["GET"])
@login_required
def providers():
    readiness = _provider_readiness_summary(include_bootstrap=True)
    return render_template("providers.html", readiness=readiness)


def _handle_deploy_submission():
    uploaded_file = request.files.get("config_file")
    if not uploaded_file:
        return render_template("deploy_new.html", errors=["No YAML configuration file was uploaded."]), 400

    try:
        yaml_content = uploaded_file.read().decode("utf-8")
        deployment_config = yaml.safe_load(yaml_content)
    except Exception as exc:
        return render_template("deploy_new.html", errors=[f"Invalid YAML file: {exc}"]), 400

    _apply_cloud_selection_override(deployment_config, request.form.get("cloud_selection", "yaml"))
    effective_yaml = yaml.safe_dump(deployment_config, sort_keys=False)
    result = deploy_app(deployment_config)
    record = _save_deployment_result(current_user.id, effective_yaml, result)
    return render_template("deploy_result.html", record=record, result=result)


def _save_deployment_result(user_id: int, yaml_content: str, result: Dict[str, Any]) -> DeploymentRecord:
    record = DeploymentRecord(user_id=user_id, yaml_content=yaml_content, result_json=result)
    record.apply_result(result, yaml_content=yaml_content)
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


def _provider_readiness_summary(include_bootstrap: bool = False):
    config = _readiness_probe_config()
    summary = []
    for provider in ["AWS", "Azure", "GCP"]:
        readiness = check_provider_readiness(provider, config)
        item = {
            "provider": provider,
            "readiness": readiness,
        }
        if include_bootstrap or not readiness.get("ready"):
            item["bootstrap_plan"] = generate_provider_bootstrap_plan(provider)
        summary.append(item)
    return summary


def _readiness_probe_config() -> Dict[str, Any]:
    raw = {
        "app": {
            "name": "readiness-probe",
            "environment": "production",
            "type": "api",
        },
        "deployment": {
            "type": "container",
            "image": "dockertalha19/fyp-books-api:latest",
            "port": 80,
        },
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
            "Health Check:",
            f"- Result: {health.get('result') or health.get('status', 'N/A')}",
            f"- Message: {health.get('message', 'N/A')}",
            "",
            "Readiness:",
            f"- Ready: {result.get('provider_readiness', {}).get('ready', 'N/A')}",
            "",
            "Docker Image Validation:",
            f"- Valid: {result.get('docker_image_validation', {}).get('valid', 'N/A')}",
            "",
            "Cleanup:",
            f"- Status: {result.get('cleanup_result', {}).get('status', 'N/A')}",
        ]
    )
    return "\n".join(lines) + "\n"


@app.route("/health")
def health():
    return "OK"


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
