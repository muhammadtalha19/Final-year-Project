import os
from typing import Any, Dict, List, Optional

from config_schema import get_service_definitions

try:
    import boto3 as _boto3
except ImportError:  # pragma: no cover - optional until real AWS deployment is used.
    _boto3 = None


boto3 = _boto3


def check_provider_readiness(provider_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
    provider = _normalize_provider(provider_name)
    if provider == "AWS":
        return _aws_readiness(config)
    if provider == "Azure":
        return _azure_readiness(config)
    if provider == "GCP":
        return _gcp_readiness(config)

    return {
        "provider": provider_name,
        "ready": False,
        "checks": [
            {
                "name": "provider",
                "status": "failed",
                "message": f"Provider '{provider_name}' is not supported.",
            }
        ],
        "missing": [],
        "warnings": [],
    }


def _aws_readiness(config: Dict[str, Any]) -> Dict[str, Any]:
    required = [
        "AWS_REGION",
        "AWS_AMI_ID",
        "AWS_KEY_NAME",
        "AWS_SECURITY_GROUP_ID",
        "AWS_SUBNET_ID",
    ]
    checks, missing = _env_checks(required)

    credentials_available = _aws_credentials_available()
    checks.append(
        {
            "name": "AWS_CREDENTIALS",
            "status": "passed" if credentials_available else "failed",
            "message": (
                "AWS credentials appear available."
                if credentials_available
                else "AWS credentials were not detected. Run aws configure or set AWS credentials before real deployment."
            ),
        }
    )
    if not credentials_available:
        missing.append("AWS_CREDENTIALS")

    port = _first_service_port(config)
    port_ok = isinstance(port, int) and 1 <= port <= 65535
    checks.append(
        {
            "name": "SERVICE_PORT",
            "status": "passed" if port_ok else "failed",
            "message": (
                f"Selected service port {port} is valid."
                if port_ok
                else "A valid service port is required before real deployment."
            ),
        }
    )
    if not port_ok:
        missing.append("SERVICE_PORT")

    return _result("AWS", checks, missing)


def _azure_readiness(config: Dict[str, Any]) -> Dict[str, Any]:
    checks, missing = _env_checks(
        [
            "AZURE_RESOURCE_GROUP",
            "AZURE_LOCATION",
            "AZURE_CONTAINERAPP_ENV",
        ]
    )

    account_ready = _env_bool("AZURE_ACCOUNT_READY") or bool(os.getenv("AZURE_SUBSCRIPTION_ID"))
    checks.append(
        {
            "name": "AZURE_ACCOUNT",
            "status": "passed" if account_ready else "warning",
            "message": (
                "Azure account context appears available."
                if account_ready
                else "Azure CLI login is not checked automatically here; run az login before real deployment."
            ),
        }
    )

    service_count = len(get_service_definitions(config))
    checks.append(
        {
            "name": "AZURE_CONTAINERAPP_ENV_READY",
            "status": "passed" if os.getenv("AZURE_CONTAINERAPP_ENV") else "failed",
            "message": (
                f"Container Apps environment is configured for {service_count or 1} service(s)."
                if os.getenv("AZURE_CONTAINERAPP_ENV")
                else "AZURE_CONTAINERAPP_ENV must reference an existing Container Apps environment."
            ),
        }
    )

    return _result("Azure", checks, missing)


def _gcp_readiness(config: Dict[str, Any]) -> Dict[str, Any]:
    checks, missing = _env_checks(["GCP_PROJECT_ID", "GCP_REGION", "GCP_PLATFORM"])
    checks.append(
        {
            "name": "GCP_REAL_DEPLOYMENT",
            "status": "failed",
            "message": "Real GCP deployment is not implemented; GCP is available for dry-run plans only.",
        }
    )
    warnings = ["GCP real deployment is not implemented in this project yet."]
    return {
        "provider": "GCP",
        "ready": False,
        "ready_for_dry_run": True,
        "ready_for_real_deploy": False,
        "checks": checks,
        "missing": missing,
        "warnings": warnings,
    }


def _env_checks(required: List[str]) -> tuple[List[Dict[str, str]], List[str]]:
    checks = []
    missing = []
    for name in required:
        value = os.getenv(name)
        passed = bool(value)
        if not passed:
            missing.append(name)
        checks.append(
            {
                "name": name,
                "status": "passed" if passed else "failed",
                "message": f"{name} is configured." if passed else f"{name} is missing.",
            }
        )
    return checks, missing


def _result(provider: str, checks: List[Dict[str, str]], missing: List[str]) -> Dict[str, Any]:
    warnings = [check["message"] for check in checks if check["status"] == "warning"]
    ready = not missing and not any(check["status"] == "failed" for check in checks)
    return {
        "provider": provider,
        "ready": ready,
        "checks": checks,
        "missing": missing,
        "warnings": warnings,
    }


def _aws_credentials_available() -> bool:
    if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
        return True
    if os.getenv("AWS_PROFILE") or os.getenv("AWS_SHARED_CREDENTIALS_FILE"):
        return True
    if boto3 is None or not _env_bool("AWS_READINESS_USE_BOTO3"):
        return False
    try:
        session = boto3.Session()
        return session.get_credentials() is not None
    except Exception:
        return False


def _first_service_port(config: Dict[str, Any]) -> Optional[int]:
    services = get_service_definitions(config)
    if not services:
        return None
    return services[0].get("port")


def _env_bool(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _normalize_provider(provider_name: str) -> str:
    providers = {
        "aws": "AWS",
        "gcp": "GCP",
        "azure": "Azure",
    }
    return providers.get(str(provider_name).strip().lower(), provider_name)
