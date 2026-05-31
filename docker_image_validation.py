from typing import Any, Dict, List

from config_schema import get_service_definitions


PLACEHOLDER = "YOUR_DOCKERHUB_USERNAME"


def validate_docker_images(config: Dict[str, Any]) -> Dict[str, Any]:
    checks: List[Dict[str, str]] = []
    errors: List[str] = []
    warnings: List[str] = []

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

        checks.append(_check(service_name, image, "passed", f"{service_name}: Docker image syntax looks usable."))

    return {
        "valid": not errors,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }


def _has_tag(image: str) -> bool:
    last_segment = image.rsplit("/", 1)[-1]
    return ":" in last_segment and not last_segment.endswith(":")


def _check(service: str, image: str, status: str, message: str) -> Dict[str, str]:
    return {
        "service": service,
        "image": image,
        "status": status,
        "message": message,
    }
