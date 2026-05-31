import os
from flask import Flask, jsonify, render_template, request
import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed in the project environment.
    def load_dotenv() -> None:
        return None

from deployment_history import load_deployment_history
from orchestrator import delete_deployment, deploy_app

load_dotenv()

app = Flask(__name__)


# ya runtime config.yaml load kar raha ha (Config Management SaaS)

config_path = os.path.join(os.path.dirname(__file__), "config.yaml")

try:
    with open(config_path, "r") as f:
        configs = yaml.safe_load(f)
except FileNotFoundError:
    configs = {}


# ya html ui interface route ha.

@app.route("/", methods=["GET"])
def home():
    return render_template("index.html", history=load_deployment_history(limit=10))


# ya deploy route ha (YAML-DRIVEN)

@app.route("/deploy", methods=["POST"])
def deploy():
    confirm_real_deployment = request.form.get("confirm_real_deployment") == "true"
    config_payload = request.form.get("config_yaml")

    if confirm_real_deployment and config_payload:
        try:
            deployment_config = yaml.safe_load(config_payload)
        except Exception as e:
            result = {
                "status": "validation_failed",
                "validation_errors": [f"Invalid confirmation payload: {e}"],
                "decision": {},
                "deployment": {"status": "not_executed"},
                "public_endpoints": [],
                "health_check": {"status": "skipped", "message": "Invalid confirmation payload."},
            }
            return render_template("index.html", result=result, history=load_deployment_history(limit=10)), 400

        result = deploy_app(deployment_config, confirm_real_deployment=True)
        return render_template("index.html", result=result, history=load_deployment_history(limit=10))

    uploaded_file = request.files.get("config_file")
    if not uploaded_file:
        result = {
            "status": "validation_failed",
            "validation_errors": ["No YAML configuration file was uploaded."],
            "decision": {},
            "deployment": {"status": "not_executed"},
            "public_endpoints": [],
            "health_check": {"status": "skipped", "message": "No file was uploaded."},
        }
        return render_template("index.html", result=result, history=load_deployment_history(limit=10)), 400

    try:
        deployment_config = yaml.safe_load(uploaded_file.stream)
    except Exception as e:
        result = {
            "status": "validation_failed",
            "validation_errors": [f"Invalid YAML file: {e}"],
            "decision": {},
            "deployment": {"status": "not_executed"},
            "public_endpoints": [],
            "health_check": {"status": "skipped", "message": "Invalid YAML."},
        }
        return render_template("index.html", result=result, history=load_deployment_history(limit=10)), 400

    _apply_cloud_selection_override(deployment_config, request.form.get("cloud_selection", "yaml"))
    result = deploy_app(deployment_config, confirm_real_deployment=confirm_real_deployment)
    return render_template("index.html", result=result, history=load_deployment_history(limit=10))


@app.route("/history", methods=["GET"])
def history():
    return render_template("index.html", history=load_deployment_history(), show_history=True)


@app.route("/deployments/<deployment_id>/delete", methods=["POST"])
def delete_saved_deployment(deployment_id):
    delete_result = delete_deployment(deployment_id)
    return render_template("index.html", delete_result=delete_result, history=load_deployment_history(), show_history=True)


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


# ya api route ha configurantion management ky liye (API ROUTES (Config Management)).

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


# ya main body ha.

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.getenv("FLASK_ENV") == "development")
