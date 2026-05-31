import os
from typing import Any, Dict, List, Optional

from config_schema import get_service_definitions

try:
    import boto3 as _boto3
except ImportError:  # pragma: no cover - optional until real AWS deployment is used.
    _boto3 = None


boto3 = _boto3


def check_provider_readiness(
    provider_name: str,
    config: Dict[str, Any],
    cloud_account: Any = None,
    require_cloud_account: bool = False,
) -> Dict[str, Any]:
    provider = _normalize_provider(provider_name)
    if cloud_account is not None:
        return _cloud_account_readiness(provider, config, cloud_account)
    if require_cloud_account or (_env_bool("MODEL_B_USER_CLOUD_ACCOUNTS") and not _env_bool("ALLOW_ADMIN_CLOUD_FALLBACK")):
        return _not_connected(provider)
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


def _cloud_account_readiness(provider: str, config: Dict[str, Any], cloud_account: Any) -> Dict[str, Any]:
    credentials = _credentials_from_cloud_account(cloud_account)
    if not credentials:
        return _not_connected(provider)
    if provider == "AWS":
        required = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"]
        checks, missing = _credential_checks(required, credentials)
        optional = ["AWS_AMI_ID", "AWS_KEY_NAME", "AWS_SECURITY_GROUP_ID", "AWS_SUBNET_ID"]
        warnings = []
        for name in optional:
            if not credentials.get(name):
                message = f"{name} is not saved; real AWS deployment may require it."
                warnings.append(message)
                checks.append({"name": name, "status": "warning", "message": message})
        _append_port_check(config, checks, missing)
        result = _result("AWS", checks, missing)
        result["warnings"].extend(warnings)
        result["account_connected"] = True
        return result
    if provider == "Azure":
        required = [
            "AZURE_TENANT_ID",
            "AZURE_CLIENT_ID",
            "AZURE_CLIENT_SECRET",
            "AZURE_SUBSCRIPTION_ID",
            "AZURE_RESOURCE_GROUP",
            "AZURE_LOCATION",
            "AZURE_CONTAINERAPP_ENV",
        ]
        checks, missing = _credential_checks(required, credentials)
        result = _result("Azure", checks, missing)
        result["account_connected"] = True
        return result
    if provider == "GCP":
        required = ["GCP_PROJECT_ID", "GCP_REGION", "GCP_PLATFORM", "GCP_SERVICE_ACCOUNT_JSON"]
        checks, missing = _credential_checks(required, credentials)
        checks.append(
            {
                "name": "GCP_REAL_DEPLOYMENT",
                "status": "passed",
                "message": "Real GCP Cloud Run deployment is implemented behind safety flags.",
            }
        )
        return {
            "provider": "GCP",
            "ready": not missing,
            "ready_for_dry_run": True,
            "ready_for_real_deploy": not missing,
            "account_connected": True,
            "checks": checks,
            "missing": missing,
            "warnings": [],
        }
    return _not_connected(provider)


def _not_connected(provider: str) -> Dict[str, Any]:
    return {
        "provider": provider,
        "ready": False,
        "ready_for_dry_run": True,
        "ready_for_real_deploy": False,
        "account_connected": False,
        "checks": [
            {
                "name": "CLOUD_ACCOUNT",
                "status": "failed",
                "message": "Cloud account not connected.",
            }
        ],
        "missing": [f"{provider}_CLOUD_ACCOUNT"],
        "warnings": ["Cloud account not connected. Real deployment will be blocked."],
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

    _append_port_check(config, checks, missing)

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
            "status": "passed",
            "message": "Real GCP Cloud Run deployment is implemented behind safety flags.",
        }
    )
    return {
        "provider": "GCP",
        "ready": not missing,
        "ready_for_dry_run": True,
        "ready_for_real_deploy": not missing,
        "checks": checks,
        "missing": missing,
        "warnings": [],
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


def _credential_checks(required: List[str], credentials: Dict[str, Any]) -> tuple[List[Dict[str, str]], List[str]]:
    checks = []
    missing = []
    for name in required:
        passed = bool(credentials.get(name))
        if not passed:
            missing.append(name)
        checks.append(
            {
                "name": name,
                "status": "passed" if passed else "failed",
                "message": f"{name} is saved." if passed else f"{name} is missing from the connected account.",
            }
        )
    return checks, missing


def _append_port_check(config: Dict[str, Any], checks: List[Dict[str, str]], missing: List[str]) -> None:
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


def _credentials_from_cloud_account(cloud_account: Any) -> Dict[str, Any]:
    if not cloud_account:
        return {}
    if isinstance(cloud_account, dict):
        return cloud_account
    if hasattr(cloud_account, "get_credentials"):
        return cloud_account.get_credentials()
    return {}
