from copy import deepcopy
from typing import Any, Dict, List, Optional


class ConfigValidationError(ValueError):
    """Raised when an uploaded deployment YAML does not match the schema."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_config(raw_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and normalize a deployment config.

    The normalized shape always contains:
    - app.name and app.environment
    - deployment.type
    - services[] with image, port, replicas, and public flags
    - requirements.max_monthly_cost_usd and min_uptime_percent
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(raw_config, dict):
        raise ConfigValidationError(["YAML root must be a mapping/object."])

    source = deepcopy(raw_config)
    app = _mapping(source.get("app"), "app", errors)
    requirements = _mapping(source.get("requirements"), "requirements", errors)
    deployment = source.get("deployment")
    services = source.get("services")
    selection = _normalize_selection(source.get("selection"), errors)

    app_name = _required_string(app, "name", "app.name", errors)
    environment = _required_string(app, "environment", "app.environment", errors)

    if deployment is None and services is None:
        errors.append("Either deployment or services must exist.")

    deployment_type = "container"
    if deployment is not None:
        if not isinstance(deployment, dict):
            errors.append("deployment must be a mapping/object.")
            deployment = {}
        deployment_type = _first_present(deployment, ["type"], "container")

    if requirements and "force_deploy" in requirements:
        warnings.append("requirements.force_deploy is ignored; deployments only run when requirements are satisfied.")

    max_cost = _positive_number(
        _first_present(requirements, ["max_monthly_cost_usd", "max_monthly_cost"]),
        "requirements.max_monthly_cost_usd",
        errors,
    )
    min_uptime = _percentage(
        _first_present(requirements, ["min_uptime_percent", "min_uptime"]),
        "requirements.min_uptime_percent",
        errors,
    )
    preferred_region = _optional_string(requirements.get("preferred_region"), "requirements.preferred_region", errors)
    public_access = _optional_bool(requirements.get("public_access"), "requirements.public_access", errors)

    normalized_services = _normalize_services(
        services=services,
        deployment=deployment if isinstance(deployment, dict) else None,
        default_public=public_access,
        errors=errors,
    )

    if errors:
        raise ConfigValidationError(errors)

    return {
        "app": {
            "name": app_name,
            "environment": environment,
        },
        "deployment": {
            "type": str(deployment_type).strip().lower(),
        },
        "services": normalized_services,
        "resources": source.get("resources", {}),
        "requirements": {
            "max_monthly_cost_usd": max_cost,
            "min_uptime_percent": min_uptime,
            "preferred_region": preferred_region.lower() if preferred_region else None,
            "public_access": public_access,
        },
        "selection": selection,
        "warnings": warnings,
    }


def get_service_definitions(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return normalized service definitions from an already validated config."""
    return list(config.get("services", []))


def _mapping(value: Any, field: str, errors: List[str]) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    errors.append(f"{field} is required and must be a mapping/object.")
    return {}


def _required_string(mapping: Dict[str, Any], key: str, field: str, errors: List[str]) -> Optional[str]:
    value = mapping.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    errors.append(f"{field} is required.")
    return None


def _optional_string(value: Any, field: str, errors: List[str]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    errors.append(f"{field} must be a non-empty string if provided.")
    return None


def _optional_bool(value: Any, field: str, errors: List[str]) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    errors.append(f"{field} must be boolean if provided.")
    return None


def _positive_number(value: Any, field: str, errors: List[str]) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        errors.append(f"{field} is required and must be greater than 0.")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{field} must be a number greater than 0.")
        return None
    if number <= 0:
        errors.append(f"{field} must be greater than 0.")
        return None
    return number


def _percentage(value: Any, field: str, errors: List[str]) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        errors.append(f"{field} is required and must be between 0 and 100.")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{field} must be a number between 0 and 100.")
        return None
    if number < 0 or number > 100:
        errors.append(f"{field} must be between 0 and 100.")
        return None
    return number


def _port(value: Any, field: str, errors: List[str]) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        errors.append(f"{field} is required and must be between 1 and 65535.")
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append(f"{field} must be an integer between 1 and 65535.")
        return None
    if number < 1 or number > 65535:
        errors.append(f"{field} must be between 1 and 65535.")
        return None
    return number


def _replicas(value: Any, field: str, errors: List[str]) -> int:
    if value is None:
        return 1
    if isinstance(value, bool):
        errors.append(f"{field} must be an integer greater than or equal to 1.")
        return 1
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append(f"{field} must be an integer greater than or equal to 1.")
        return 1
    if number < 1:
        errors.append(f"{field} must be greater than or equal to 1.")
        return 1
    return number


def _first_present(mapping: Optional[Dict[str, Any]], keys: List[str], default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def _normalize_selection(value: Any, errors: List[str]) -> Dict[str, Optional[str]]:
    if value is None:
        return {
            "mode": "auto",
            "provider": None,
        }

    if not isinstance(value, dict):
        errors.append("selection must be a mapping/object when provided.")
        return {
            "mode": "auto",
            "provider": None,
        }

    mode_value = value.get("mode", "auto")
    if not isinstance(mode_value, str):
        errors.append("selection.mode must be either auto or manual.")
        mode = "auto"
    else:
        mode = mode_value.strip().lower()
        if mode not in {"auto", "manual"}:
            errors.append("selection.mode must be either auto or manual.")
            mode = "auto"

    if mode == "auto":
        return {
            "mode": mode,
            "provider": None,
        }

    provider_value = value.get("provider")
    provider = _normalize_provider(provider_value, "selection.provider", errors) if provider_value is not None else None

    if provider is None:
        errors.append("selection.provider is required when selection.mode is manual.")

    return {
        "mode": mode,
        "provider": provider,
    }


def _normalize_provider(value: Any, field: str, errors: List[str]) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be one of AWS, GCP, Azure.")
        return None

    normalized = value.strip().lower()
    providers = {
        "aws": "AWS",
        "gcp": "GCP",
        "azure": "Azure",
    }
    provider = providers.get(normalized)
    if provider is None:
        errors.append(f"{field} must be one of AWS, GCP, Azure.")
    return provider


def _normalize_services(
    services: Any,
    deployment: Optional[Dict[str, Any]],
    default_public: Optional[bool],
    errors: List[str],
) -> List[Dict[str, Any]]:
    if services is not None:
        if not isinstance(services, list) or not services:
            errors.append("services must be a non-empty list when provided.")
            return []

        normalized = []
        for index, service in enumerate(services, start=1):
            if not isinstance(service, dict):
                errors.append(f"services[{index - 1}] must be a mapping/object.")
                continue

            image = _required_string(service, "image", f"services[{index - 1}].image", errors)
            port = _port(service.get("port"), f"services[{index - 1}].port", errors)
            replicas = _replicas(service.get("replicas"), f"services[{index - 1}].replicas", errors)
            public = _optional_bool(service.get("public"), f"services[{index - 1}].public", errors)

            normalized.append(
                {
                    "name": str(service.get("name") or f"service-{index}").strip(),
                    "image": image,
                    "port": port,
                    "replicas": replicas,
                    "public": public if public is not None else bool(default_public),
                }
            )
        return normalized

    if deployment is None:
        return []

    container = deployment.get("container") if isinstance(deployment.get("container"), dict) else {}
    image = _first_present(deployment, ["image"], _first_present(container, ["image"]))
    port = _first_present(deployment, ["port"], _first_present(container, ["port"]))
    replicas = _first_present(deployment, ["replicas"], _first_present(container, ["replicas"], 1))

    service = {
        "name": "web",
        "image": image,
        "port": port,
        "replicas": replicas,
        "public": default_public if default_public is not None else True,
    }

    image_value = service["image"]
    if not isinstance(image_value, str) or not image_value.strip():
        errors.append("deployment.image is required.")
    else:
        service["image"] = image_value.strip()

    service["port"] = _port(service["port"], "deployment.port", errors)
    service["replicas"] = _replicas(service["replicas"], "deployment.replicas", errors)
    return [service]
