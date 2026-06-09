import os
from copy import deepcopy
from typing import Any, Dict, Optional

import yaml

from config_schema import ConfigValidationError, get_service_definitions, validate_config
from decision_engine import select_provider
from diagnostics import build_diagnostics
from deployment_history import add_deployment_record, get_deployment_record, update_deployment_record
from docker_image_validation import validate_docker_images
from health_checks import check_urls_with_retries
from pricing.models import PriceEstimate
from pricing.pricing_service import get_price_estimates
from provider_bootstrap import generate_provider_bootstrap_plan
from provider_readiness import check_provider_readiness
from providers.aws_provider import AWSProvider
from providers.azure_mock import AzureMockProvider
from providers.gcp_mock import GCPMockProvider


PROVIDERS = {
    "AWS": AWSProvider,
    "GCP": GCPMockProvider,
    "Azure": AzureMockProvider,
}


def deploy_app(
    config: Dict[str, Any],
    execute: bool = True,
    confirm_real_deployment: bool = False,
    cloud_account: Any = None,
    cloud_accounts: Optional[Dict[str, Any]] = None,
    require_cloud_account: bool = False,
) -> Dict[str, Any]:
    """
    Validate, decide, deploy through an implemented backend, run health checks,
    and format a dashboard-friendly response.
    """
    try:
        validated = validate_config(config)
    except ConfigValidationError as exc:
        result = {
            "app": _safe_app_value(config, "name"),
            "app_type": _safe_app_value(config, "type"),
            "environment": _safe_app_value(config, "environment"),
            "status": "validation_failed",
            "deployment_mode": "dry_run" if not _real_deployment_enabled() else "real",
            "validation_errors": exc.errors,
            "warnings": [],
            "decision": {},
            "pricing": {},
            "provider_readiness": {},
            "docker_image_validation": {},
            "bootstrap_plan": {},
            "approval": {},
            "diagnostics": {},
            "deployment": {"status": "not_executed", "message": "Validation failed."},
            "deployment_steps": ["YAML validation failed"],
            "logs": ["YAML validation failed"],
            "generated_commands": [],
            "public_endpoints": [],
            "health_check": _skipped_health("Health check skipped because validation failed."),
        }
        return _finalize_result(result)

    pricing_estimates = get_price_estimates(validated)
    decision = select_provider(validated, price_estimates=pricing_estimates)
    image_validation = validate_docker_images(validated)
    result = {
        "app": validated["app"]["name"],
        "app_type": validated["app"]["type"],
        "image": _first_service(validated).get("image"),
        "environment": validated["app"]["environment"],
        "status": "pending",
        "deployment_mode": "real" if _real_deployment_enabled() else "dry_run",
        "validation_errors": [],
        "warnings": validated.get("warnings", []),
        "decision": decision,
        "decision_audit_trail": decision.get("audit_trail", {}),
        "pricing": _pricing_to_dict(pricing_estimates),
        "provider_readiness": {},
        "docker_image_validation": image_validation,
        "bootstrap_plan": {},
        "approval": {},
        "diagnostics": {},
        "deployment": {},
        "deployment_steps": ["YAML validation passed", "Provider decision completed"],
        "logs": ["YAML validation passed", "Provider decision completed"],
        "generated_commands": [],
        "public_endpoints": [],
        "health_check": _skipped_health("Health check has not run yet."),
    }

    if decision.get("status") == "manual_selection_blocked":
        result.update(
            {
                "status": "manual_selection_blocked",
                "deployment": {
                    "status": "manual_selection_blocked",
                    "message": decision["reason"],
                },
                "generated_commands": [],
                "health_check": _skipped_health("Health check skipped because manual provider selection was blocked."),
            }
        )
        result["deployment_steps"].append("Deployment stopped before plan generation")
        result["logs"] = list(result["deployment_steps"])
        return _finalize_result(result)

    if not decision.get("selected_provider"):
        result.update(
            {
                "status": "requirements_not_satisfied",
                "deployment": {
                    "status": "not_executed",
                    "message": "No provider satisfied the deployment requirements.",
                },
                "health_check": _skipped_health("Health check skipped because no deployment was executed."),
            }
        )
        result["deployment_steps"].append("Deployment stopped before execution")
        result["logs"] = list(result["deployment_steps"])
        return _finalize_result(result)

    selected_provider = decision["selected_provider"]
    selected_cloud_account = _cloud_account_for(selected_provider, cloud_account, cloud_accounts)
    cloud_account_summary = _cloud_account_summary(selected_provider, selected_cloud_account)
    provider_readiness = check_provider_readiness(
        selected_provider,
        validated,
        cloud_account=selected_cloud_account,
        require_cloud_account=require_cloud_account,
    )
    result["provider_readiness"] = provider_readiness
    result["cloud_account"] = cloud_account_summary
    if not provider_readiness.get("ready", False):
        result["bootstrap_plan"] = generate_provider_bootstrap_plan(selected_provider)

    if not _real_deployment_enabled():
        execution_provider = selected_provider
        provider = _provider_instance(execution_provider)
        deployment = _call_generate_plan(provider, validated, selected_cloud_account)
        if require_cloud_account and not selected_cloud_account:
            result["warnings"].append("Cloud account not connected. Real deployment will be blocked.")
        decision = _decision_for_selected_execution(
            decision,
            execution_provider,
            (
                f"{decision['reason']} Dry-run mode is enabled, so the "
                f"orchestrator generated a {selected_provider} deployment plan without executing cloud commands."
            ),
        )
        result.update(
            {
                "status": "dry_run",
                "deployment_mode": "dry_run",
                "decision": decision,
                "deployment": deployment,
                "generated_commands": deployment.get("generated_commands", []),
                "health_check": _skipped_health("Health check skipped because dry-run mode does not execute deployment."),
            }
        )
        result["deployment_steps"].append(f"Dry-run provider: {execution_provider}")
        result["deployment_steps"].append(deployment.get("message", "Dry-run plan generated."))
        result["logs"] = list(result["deployment_steps"])
        return _finalize_result(result)

    execution_provider = selected_provider
    decision = _decision_for_selected_execution(
        decision,
        execution_provider,
        f"{decision['reason']} Real deployment mode is enabled for {selected_provider}.",
    )
    result["decision"] = decision

    if not execution_provider:
        result.update(
            {
                "status": "not_executed",
                "deployment": {
                    "status": "not_executed",
                    "message": decision["reason"],
                },
                "health_check": _skipped_health("Health check skipped because no execution backend is available."),
            }
        )
        result["deployment_steps"].append("Deployment stopped before execution")
        result["logs"] = list(result["deployment_steps"])
        return _finalize_result(result)

    provider = _provider_instance(execution_provider)
    plan = _call_generate_plan(provider, validated, selected_cloud_account)

    if require_cloud_account and not selected_cloud_account:
        deployment = {
            **plan,
            "status": "cloud_account_required",
            "deployment_mode": "real",
            "message": (
                f"Connect your {execution_provider} cloud account before real deployment. "
                "You can connect it from Cloud Accounts or choose a connected provider."
            ),
        }
        result.update(
            {
                "status": "cloud_account_required",
                "deployment_mode": "real",
                "deployment": deployment,
                "generated_commands": plan.get("generated_commands", []),
                "health_check": _skipped_health("Health check skipped because no connected cloud account is available."),
            }
        )
        result["deployment_steps"].append(f"Execution provider: {execution_provider}")
        result["deployment_steps"].append(deployment["message"])
        result["logs"] = list(result["deployment_steps"])
        return _finalize_result(result)

    if not _provider_deployment_allowed(execution_provider):
        deployment = {
            **plan,
            "status": "blocked_by_safety_flag",
            "deployment_mode": "real",
            "message": (
                f"Real deployment is enabled, but ALLOW_{execution_provider}_DEPLOYMENT is not true. "
                "No cloud commands were executed."
            ),
        }
        result.update(
            {
                "status": "blocked_by_safety_flag",
                "deployment_mode": "real",
                "deployment": deployment,
                "generated_commands": plan.get("generated_commands", []),
                "health_check": _skipped_health("Health check skipped because deployment was blocked by safety flag."),
            }
        )
        result["deployment_steps"].append(f"Execution provider: {execution_provider}")
        result["deployment_steps"].append(deployment["message"])
        result["logs"] = list(result["deployment_steps"])
        return _finalize_result(result)

    if not image_validation.get("valid", False):
        deployment = {
            **plan,
            "status": "image_validation_failed",
            "deployment_mode": "real",
            "message": "Docker image validation failed. No cloud commands were executed.",
        }
        result.update(
            {
                "status": "image_validation_failed",
                "deployment_mode": "real",
                "deployment": deployment,
                "generated_commands": plan.get("generated_commands", []),
                "health_check": _skipped_health("Health check skipped because Docker image validation failed."),
            }
        )
        result["deployment_steps"].append(f"Execution provider: {execution_provider}")
        result["deployment_steps"].append(deployment["message"])
        result["logs"] = list(result["deployment_steps"])
        return _finalize_result(result)

    if not provider_readiness.get("ready", False):
        deployment = {
            **plan,
            "status": "provider_not_ready",
            "deployment_mode": "real",
            "missing_vars": provider_readiness.get("missing", []),
            "message": "Selected provider is not ready for real deployment. No cloud commands were executed.",
        }
        result.update(
            {
                "status": "provider_not_ready",
                "deployment_mode": "real",
                "deployment": deployment,
                "generated_commands": plan.get("generated_commands", []),
                "health_check": _skipped_health("Health check skipped because provider readiness failed."),
            }
        )
        result["deployment_steps"].append(f"Execution provider: {execution_provider}")
        result["deployment_steps"].append(deployment["message"])
        result["logs"] = list(result["deployment_steps"])
        return _finalize_result(result)

    if not confirm_real_deployment:
        deployment = {
            **plan,
            "status": "approval_required",
            "deployment_mode": "real",
            "message": "Real deployment approval is required before cloud resources are created.",
        }
        result.update(
            {
                "status": "approval_required",
                "deployment_mode": "real",
                "deployment": deployment,
                "generated_commands": plan.get("generated_commands", []),
                "approval": _approval_summary(validated, decision, plan, provider_readiness),
                "health_check": _skipped_health("Health check skipped while waiting for deployment approval."),
            }
        )
        result["deployment_steps"].append(f"Execution provider: {execution_provider}")
        result["deployment_steps"].append(deployment["message"])
        result["logs"] = list(result["deployment_steps"])
        return _finalize_result(result)

    if not execute:
        result.update(
            {
                "status": "execution_skipped",
                "deployment_mode": "real",
                "deployment": {
                    "provider": execution_provider,
                    "status": "skipped",
                    "message": "Execution was disabled for this run.",
                    "service_endpoints": [],
                },
                "health_check": _skipped_health("Health check skipped because execution was disabled."),
            }
        )
        result["deployment_steps"].append("Execution skipped")
        result["logs"] = list(result["deployment_steps"])
        return _finalize_result(result)

    deployment = _call_provider_deploy(provider, validated, selected_cloud_account)
    deployment["health_check_path"] = validated.get("health_check", {}).get("path", "/")
    endpoints = deployment.get("service_endpoints", [])
    health_check = provider.health_check(deployment) if deployment.get("status") == "deployed" else _skipped_health(
        "Health check skipped because deployment did not complete successfully."
    )
    result_status = deployment.get("status", "unknown")
    cleanup_result = {}
    if result_status == "deployed" and health_check.get("result") == "failed":
        result_status = "cleanup_required"
        if _env_bool("AUTO_TERMINATE_ON_FAILURE"):
            cleanup_result = cleanup_deployment_record(
                _history_like_record(
                    {
                        **result,
                        "status": "deployed",
                        "deployment_mode": "real",
                        "decision": decision,
                        "deployment": deployment,
                    }
                ),
                cloud_account=selected_cloud_account,
                require_cloud_account=require_cloud_account,
            )

    result.update(
        {
            "status": result_status,
            "deployment_mode": "real",
            "deployment": deployment,
            "generated_commands": deployment.get("generated_commands", []),
            "public_ip": deployment.get("public_ip"),
            "public_endpoints": endpoints,
            "health_check": health_check,
            "cleanup_result": cleanup_result,
        }
    )
    result["deployment_steps"].append(f"Execution provider: {execution_provider}")
    result["deployment_steps"].append(deployment.get("message", "Deployment finished."))
    result["logs"] = list(result["deployment_steps"])
    return _finalize_result(result)


def _approval_summary(
    config: Dict[str, Any],
    decision: Dict[str, Any],
    plan: Dict[str, Any],
    readiness: Dict[str, Any],
) -> Dict[str, Any]:
    service = _first_service(config)
    selected_provider = decision.get("selected_provider")
    selected_evaluation = _provider_evaluation(decision, selected_provider)
    public_access = bool(config.get("requirements", {}).get("public_access") or service.get("public"))

    return {
        "required": True,
        "config_yaml": yaml.safe_dump(config, sort_keys=False),
        "app_name": config["app"]["name"],
        "selected_provider": selected_provider,
        "execution_provider": decision.get("execution_provider"),
        "docker_image": service.get("image"),
        "port": service.get("port"),
        "access": "public" if public_access else "private",
        "estimated_cost_usd": selected_evaluation.get("estimated_cost_usd"),
        "readiness_ready": readiness.get("ready"),
        "generated_commands": plan.get("generated_commands", []),
        "warning": "Confirming will execute real cloud deployment commands and may create billable resources.",
    }


def cleanup_deployment_record(
    record: Dict[str, Any],
    cloud_account: Any = None,
    require_cloud_account: bool = False,
) -> Dict[str, Any]:
    execution_provider = record.get("execution_provider") or record.get("provider")
    status = record.get("status")
    deployment_mode = record.get("deployment_mode")

    if deployment_mode != "real" or status not in {"deployed", "delete_failed"}:
        return {
            "provider": execution_provider,
            "status": "delete_skipped",
            "message": "Cleanup skipped because this record is not an active real deployment.",
        }
    if execution_provider not in PROVIDERS:
        return {
            "provider": execution_provider,
            "status": "delete_skipped",
            "message": "Cleanup skipped because this provider does not have a cleanup backend.",
        }
    if require_cloud_account and cloud_account is None:
        return {
            "provider": execution_provider,
            "status": "cloud_account_required",
            "message": f"Cleanup blocked because the {execution_provider} cloud account is not connected.",
        }
    provider = _provider_instance(execution_provider)
    return provider.delete(record, cloud_account) if cloud_account is not None else provider.delete(record)


def delete_deployment(deployment_id: str) -> Dict[str, Any]:
    record = get_deployment_record(deployment_id)
    if not record:
        return {
            "provider": None,
            "status": "delete_skipped",
            "message": "Cleanup skipped because the deployment record was not found.",
        }

    delete_result = cleanup_deployment_record(record)

    update_deployment_record(
        deployment_id,
        {
            "status": delete_result["status"],
            "cleanup_result": delete_result,
        },
    )
    return delete_result


def build_deployment_report(deployment_id: str) -> Optional[str]:
    record = get_deployment_record(deployment_id)
    if not record:
        return None

    lines = [
        "Deployment Report",
        "=================",
        f"Timestamp: {record.get('timestamp', 'N/A')}",
        f"App name: {record.get('app_name', 'N/A')}",
        f"App type: {record.get('app_type', 'N/A')}",
        f"Image: {record.get('image', 'N/A')}",
        f"Selected provider: {record.get('selected_provider', 'N/A')}",
        f"Execution provider: {record.get('execution_provider', 'N/A')}",
        f"Deployment mode: {record.get('deployment_mode', 'N/A')}",
        f"Status: {record.get('status', 'N/A')}",
        "",
        "Provider Evaluation:",
    ]
    for provider in record.get("evaluated_providers", []):
        lines.append(
            f"- {provider.get('provider')}: eligible={provider.get('eligible')}, "
            f"cost=${provider.get('estimated_cost_usd')}/mo, uptime={provider.get('uptime_percent')}%, "
            f"score={provider.get('score')}"
        )

    lines.extend(["", "Generated Commands:"])
    for command in record.get("generated_commands", []):
        lines.append(f"- {command.get('command_string') or ' '.join(command.get('command', []))}")

    lines.extend(["", "Public Endpoints:"])
    for endpoint in record.get("public_endpoints", []):
        lines.append(f"- {endpoint.get('name', 'service')}: {endpoint.get('url')}")

    health = record.get("health_check", {})
    lines.extend(
        [
            "",
            "Health Check:",
            f"- Result: {health.get('result') or health.get('status', 'N/A')}",
            f"- URL: {health.get('url', 'N/A')}",
            f"- Status code: {health.get('status_code', 'N/A')}",
            f"- Attempts: {health.get('attempts', 'N/A')}",
            f"- Message: {health.get('message', 'N/A')}",
            "",
            "Provider Readiness:",
            f"- Ready: {record.get('provider_readiness', {}).get('ready', 'N/A')}",
            f"- Missing: {', '.join(record.get('provider_readiness', {}).get('missing', [])) or 'None'}",
            "",
            "Docker Image Validation:",
            f"- Type: {record.get('docker_image_validation', {}).get('check_type', 'N/A')}",
            f"- Valid: {record.get('docker_image_validation', {}).get('valid', 'N/A')}",
            "",
            "Cleanup:",
            f"- Status: {record.get('cleanup_result', {}).get('status', 'N/A')}",
        ]
    )
    return "\n".join(lines) + "\n"


def _finalize_result(result: Dict[str, Any]) -> Dict[str, Any]:
    result["decision_audit_trail"] = result.get("decision", {}).get("audit_trail", result.get("decision_audit_trail", {}))
    result["diagnostics"] = _diagnostics_for_result(result)
    add_deployment_record(result)
    return result


def _diagnostics_for_result(result: Dict[str, Any]) -> Dict[str, Any]:
    deployment = result.get("deployment", {})
    generated_commands = result.get("generated_commands") or deployment.get("generated_commands", [])
    provider_messages = list(result.get("logs") or deployment.get("logs") or [])
    action_hint = deployment.get("action_hint") or ""
    raw_error_summary = deployment.get("stderr") or ""
    if not raw_error_summary and result.get("status") in {"failed", "configuration_error", "provider_not_ready"}:
        raw_error_summary = deployment.get("message", "")

    next_steps = _next_steps_for_result(result)
    log_commands = _log_commands_for_result(result)

    return build_diagnostics(
        generated_commands=generated_commands,
        provider_messages=provider_messages,
        action_hint=action_hint,
        raw_error_summary=raw_error_summary,
        next_steps=next_steps,
        log_commands=log_commands,
    )


def _next_steps_for_result(result: Dict[str, Any]) -> list[str]:
    status = result.get("status")
    if status == "approval_required":
        return ["Review the plan and click Confirm Real Deployment only in a controlled cloud account."]
    if status == "provider_not_ready":
        return ["Review provider readiness checks and bootstrap suggestions before retrying."]
    if status == "image_validation_failed":
        return ["Replace placeholder or invalid Docker image references and upload the YAML again."]
    if status == "blocked_by_safety_flag":
        return ["Enable the matching ALLOW_*_DEPLOYMENT flag only when you intend to create real resources."]
    if status == "cloud_account_required":
        return ["Connect the selected cloud provider account, then retry or choose a connected provider."]
    if status == "deployed":
        return ["Verify the public endpoint, monitor billing, and use cleanup when the demo is complete."]
    if status == "dry_run":
        return ["Review generated commands. No cloud resources were created."]
    return []


def _log_commands_for_result(result: Dict[str, Any]) -> list[Dict[str, Any]]:
    provider_name = result.get("decision", {}).get("execution_provider") or result.get("deployment", {}).get("provider")
    if not provider_name:
        return []
    try:
        provider = _provider_instance(provider_name)
        return provider.get_logs(_history_like_record(result)).get("commands", [])
    except Exception:
        return []


def _history_like_record(result: Dict[str, Any]) -> Dict[str, Any]:
    deployment = result.get("deployment", {})
    decision = result.get("decision", {})
    return {
        "app_name": result.get("app"),
        "provider": deployment.get("provider"),
        "selected_provider": decision.get("selected_provider") or deployment.get("provider"),
        "execution_provider": decision.get("execution_provider") or deployment.get("provider"),
        "status": result.get("status") or deployment.get("status"),
        "deployment_mode": result.get("deployment_mode") or deployment.get("deployment_mode"),
        "instance_id": deployment.get("instance_id"),
        "app_names": deployment.get("app_names", []),
        "service_names": deployment.get("service_names", []),
        "deployment": deployment,
    }


def _deployment_health_check(deployment: Dict[str, Any]) -> Dict[str, Any]:
    endpoints = deployment.get("service_endpoints") or deployment.get("endpoints") or []
    path = deployment.get("health_check_path", "/")
    urls = [_health_url(endpoint.get("url"), path) for endpoint in endpoints if endpoint.get("url")]
    return check_urls_with_retries(urls, int(os.getenv("DEPLOYMENT_TIMEOUT_SECONDS", "180")))


def _health_url(url: Optional[str], path: str) -> Optional[str]:
    if not url:
        return None
    if not path or path == "/":
        return url
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=path, query="", fragment=""))


def _first_service(config: Dict[str, Any]) -> Dict[str, Any]:
    services = get_service_definitions(config)
    return services[0] if services else {}


def _provider_evaluation(decision: Dict[str, Any], provider_name: Optional[str]) -> Dict[str, Any]:
    return next(
        (
            provider
            for provider in decision.get("evaluated_providers", [])
            if provider.get("provider") == provider_name
        ),
        {},
    )


def _provider_instance(provider_name: str):
    provider_cls = PROVIDERS.get(provider_name)
    if not provider_cls:
        raise ValueError(f"Unsupported execution provider: {provider_name}")
    return provider_cls()


def _cloud_account_for(provider_name: str, cloud_account: Any = None, cloud_accounts: Optional[Dict[str, Any]] = None) -> Any:
    if cloud_accounts:
        return cloud_accounts.get(provider_name)
    if cloud_account is not None:
        provider = getattr(cloud_account, "provider", None)
        if not provider or provider == provider_name:
            return cloud_account
    return None


def _cloud_account_summary(provider_name: str, cloud_account: Any = None) -> Dict[str, Any]:
    if not cloud_account:
        return {
            "provider": provider_name,
            "connected": False,
            "status": "missing",
            "message": "Cloud account not connected. Real deployment will be blocked.",
        }
    if hasattr(cloud_account, "masked_summary"):
        summary = cloud_account.masked_summary()
        for key in ["last_checked_at", "created_at"]:
            if summary.get(key) is not None:
                summary[key] = str(summary[key])
    elif isinstance(cloud_account, dict):
        summary = {"provider": provider_name, "connected": True, "status": "connected"}
    else:
        summary = {"provider": provider_name, "connected": True, "status": "connected"}
    summary["connected"] = True
    summary.setdefault("provider", provider_name)
    return summary


def _call_generate_plan(provider, config: Dict[str, Any], cloud_account: Any = None) -> Dict[str, Any]:
    return provider.generate_plan(config, cloud_account) if cloud_account is not None else provider.generate_plan(config)


def _call_provider_deploy(provider, config: Dict[str, Any], cloud_account: Any = None) -> Dict[str, Any]:
    return provider.deploy(config, cloud_account) if cloud_account is not None else provider.deploy(config)


def _skipped_health(message: str) -> Dict[str, Any]:
    return {
        "result": "skipped",
        "status": "skipped",
        "passed": None,
        "url": None,
        "status_code": None,
        "response_time_ms": None,
        "attempts": 0,
        "message": message,
    }


def _safe_app_value(config: Optional[Dict[str, Any]], key: str) -> Optional[str]:
    if not isinstance(config, dict):
        return None
    app = config.get("app", {})
    if not isinstance(app, dict):
        return None
    return app.get(key)


def _pricing_to_dict(price_estimates: dict[str, PriceEstimate]) -> Dict[str, Any]:
    return {
        provider: estimate.to_dict()
        for provider, estimate in price_estimates.items()
    }


def _real_deployment_enabled() -> bool:
    return _env_bool("ENABLE_REAL_DEPLOYMENT")


def _provider_deployment_allowed(provider_name: str) -> bool:
    return _env_bool(f"ALLOW_{provider_name.upper()}_DEPLOYMENT")


def _env_bool(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _decision_for_selected_execution(
    decision: Dict[str, Any],
    execution_provider: str,
    reason: str,
) -> Dict[str, Any]:
    updated = deepcopy(decision)
    updated["execution_provider"] = execution_provider
    updated["execution_cloud"] = execution_provider
    updated["reason"] = reason
    return updated
