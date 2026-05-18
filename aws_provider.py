from providers.aws_provider import AWSProvider


def deploy_to_aws(container_image, container_port):
    """
    Backward-compatible wrapper for older code paths.

    New orchestration code should use providers.aws_provider.AWSProvider.
    """
    config = {
        "app": {"name": "legacy-app", "environment": "unknown"},
        "deployment": {"type": "container"},
        "services": [
            {
                "name": "web",
                "image": container_image,
                "port": int(container_port),
                "replicas": 1,
                "public": True,
            }
        ],
        "requirements": {},
    }
    result = AWSProvider().deploy(config)
    if result.get("public_ip"):
        return result["public_ip"]
    raise RuntimeError(result.get("message", "AWS deployment failed."))
