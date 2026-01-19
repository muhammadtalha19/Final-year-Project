from aws_provider import deploy_to_aws

print(">>> NEW orchestrator.py LOADED <<<")

# ------------------------
# Simulated cloud metrics
# ------------------------
CLOUD_DATA = {
    "AWS": {
        "uptime": 99.99,
        "cost": 18
    },
    "GCP": {
        "uptime": 99.95,
        "cost": 9
    },
    "Azure": {
        "uptime": 99.9,
        "cost": 11
    }
}

SUPPORTED_EXECUTION_CLOUD = "AWS"

# ------------------------
# Cloud selection logic
# ------------------------
def choose_cloud(requirements):
    for cloud, metrics in CLOUD_DATA.items():
        if (
            metrics["uptime"] >= requirements["min_uptime"]
            and metrics["cost"] <= requirements["max_monthly_cost"]
        ):
            return cloud
    return None


# ------------------------
# Main orchestration entry
# ------------------------
def deploy_app(config):

    app_name = config["app"]["name"]
    environment = config["app"]["environment"]
    requirements = config["requirements"]
    container_image = config["deployment"]["container"]["image"]
    container_port = config["deployment"]["container"]["port"]

    print(f">>> Starting orchestration for {app_name} ({environment})")

    result = {
        "app": app_name,
        "environment": environment,
        "decision": {},
        "deployment_steps": []
    }

    # Step 1: Decide best cloud
    selected_cloud = choose_cloud(requirements)

    if selected_cloud:
        print(f">>> {selected_cloud} meets constraints")
        decision_reason = (
            f"{selected_cloud} satisfies uptime and cost constraints"
        )
    else:
        print(">>> No cloud meets constraints")
        decision_reason = (
            "No cloud met constraints; using AWS fallback deployment"
        )

    # Step 2: FORCE execution cloud to AWS
    if selected_cloud != SUPPORTED_EXECUTION_CLOUD:
        print(
            f">>> Executing deployment on AWS "
            f"(fallback from {selected_cloud})"
        )

    result["decision"] = {
        "selected_cloud": selected_cloud,
        "execution_cloud": "AWS",
        "reason": decision_reason
    }

    # Step 3: ALWAYS deploy to AWS
    print(">>> Deploying to AWS (real deployment via boto3)")
    public_ip = deploy_to_aws(container_image, container_port)

    result["deployment_steps"].append("Application deployed to AWS")
    result["public_ip"] = public_ip

    print(">>> Orchestration completed")
    return result