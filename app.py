from flask import Flask, jsonify, render_template, request
import yaml
import os
from orchestrator import deploy_app

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
    return render_template("index.html")


# ya deploy route ha (YAML-DRIVEN)

@app.route("/deploy", methods=["POST"])
def deploy():
    print(">>> DEPLOY BUTTON CLICKED <<<")

    uploaded_file = request.files.get("config_file")

    if not uploaded_file:
        return "No deployment_config.yaml uploaded", 400

    try:
        # Parse YAML from the uploaded file stream safely
        deployment_config = yaml.safe_load(uploaded_file.stream)
    except Exception as e:
        return f"Invalid YAML file: {e}", 400

    print(">>> DEPLOYMENT CONFIG:", deployment_config)

    result = deploy_app(deployment_config)

    print(">>> DEPLOY RESULT:", result)

    return render_template("index.html", result=result)


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
    app.run(host="0.0.0.0", port=5000, debug=True)
