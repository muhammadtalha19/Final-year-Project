import os
from typing import Any, Dict, List

import requests

from config_schema import get_service_definitions


PLACEHOLDER = "YOUR_DOCKERHUB_USERNAME"


def validate_docker_images(config: Dict[str, Any]) -> Dict[str, Any]:
    checks: List[Dict[str, str]] = []
    errors: List[str] = []
    warnings: List[str] = []
    registry_enabled = _env_bool("ENABLE_IMAGE_REGISTRY_CHECK")
    check_type = "registry_checked" if registry_enabled else "syntax_only"

    for service in get_service_definitions(config):
        service_name = service.get("name") or "service"
        image = str(service.get("image") or "").strip()

        if not image:
            message = f"{service_name}: Docker image is empty."
            errors.append(message)
            checks.append(_check(service_name, image, "failed", message))
            continue

        if PLACEHOLDER in image:
            message = f"{service_name}: Docker image contains placeholder {PLACEHOLDER}."
            errors.append(message)
            checks.append(_check(service_name, image, "failed", message))
            continue

        if not _has_tag(image):
            message = f"{service_name}: Docker image has no explicit tag; latest may be used implicitly."
            warnings.append(message)
            checks.append(_check(service_name, image, "warning", message))
            continue

        if registry_enabled:
            registry_result = docker_hub_image_exists(image)
            if registry_result["status"] == "failed":
                message = f"{service_name}: {registry_result['message']}"
                errors.append(message)
                checks.append(_check(service_name, image, "failed", message))
                continue
            if registry_result["status"] == "warning":
                message = f"{service_name}: {registry_result['message']}"
                warnings.append(message)
                checks.append(_check(service_name, image, "warning", message))
                continue

        checks.append(_check(service_name, image, "passed", f"{service_name}: Docker image syntax looks usable."))

    return {
        "valid": not errors,
        "check_type": check_type,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }


def docker_hub_image_exists(image: str) -> Dict[str, str]:
    repository, tag = _docker_hub_repository_and_tag(image)
    if not repository or not tag:
        return {
            "status": "warning",
            "message": "Registry check skipped because this image is not a simple Docker Hub reference.",
        }

    url = f"https://hub.docker.com/v2/repositories/{repository}/tags/{tag}"
    try:
        response = requests.get(url, timeout=5)
    except requests.RequestException as exc:
        return {
            "status": "warning",
            "message": f"Docker Hub registry check was unavailable; syntax validation used. {exc}",
        }

    if response.status_code == 200:
        return {"status": "passed", "message": "Docker Hub image tag exists."}
    if response.status_code == 404:
        return {"status": "failed", "message": "Docker Hub image tag was not found."}
    return {
        "status": "warning",
        "message": f"Docker Hub registry check returned HTTP {response.status_code}; syntax validation used.",
    }


def _has_tag(image: str) -> bool:
    last_segment = image.rsplit("/", 1)[-1]
    return ":" in last_segment and not last_segment.endswith(":")


def _docker_hub_repository_and_tag(image: str) -> tuple[str, str]:
    if "/" in image.split(":")[0]:
        namespace_repo = image.rsplit(":", 1)[0]
    else:
        namespace_repo = f"library/{image.rsplit(':', 1)[0]}"
    tag = image.rsplit(":", 1)[1] if ":" in image.rsplit("/", 1)[-1] else ""

    first_segment = namespace_repo.split("/", 1)[0]
    if "." in first_segment or ":" in first_segment:
        return "", ""
    return namespace_repo, tag


def _check(service: str, image: str, status: str, message: str) -> Dict[str, str]:
    return {
        "service": service,
        "image": image,
        "status": status,
        "message": message,
    }


def _env_bool(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"
