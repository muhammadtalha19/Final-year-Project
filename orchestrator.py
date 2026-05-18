import os
from copy import deepcopy
from typing import Any, Dict, Optional

from config_schema import ConfigValidationError, validate_config
from decision_engine import select_provider
from deployment_history import add_deployment_record
from pricing.models import PriceEstimate
from pricing.pricing_service import get_price_estimates
from providers.aws_provider import AWSProvider
from providers.azure_mock import AzureMockProvider
from providers.gcp_mock import GCPMockProvider


PROVIDERS = {
    "AWS": AWSProvider,
    "GCP": GCPMockProvider,
    "Azure": AzureMockProvider,
}


def deploy_app(config: Dict[str, Any], execute: bool = True) -> Dict[str, Any]:
    """
    Validate, decide, deploy through an implemented backend, run health checks,
    and format a dashboard-friendly response.
    """
    try:
        validated = validate_config(config)
    except ConfigValidationError as exc:
        result = {
            "app": _safe_app_value(config, "name"),
            "environment": _safe_app_value(config, "environment"),
            "status": "validation_failed",
            "deployment_mode": "dry_run" if not _real_deployment_enabled() else "real",
            "validation_errors": exc.errors,
            "warnings": [],
            "decision": {},
            "pricing": {},
            "deployment": {"status": "not_executed", "message": "Validation failed."},
            "deployment_steps": ["YAML validation failed"],
            "logs": ["YAML validation failed"],
            "generated_commands": [],
            "public_endpoints": [],
            "health_check": _skipped_health("Health check skipped because validation failed."),
        }
        add_deployment_record(result)
        return result

    pricing_estimates = get_price_estimates(validated)
    decision = select_provider(validated, price_estimates=pricing_estimates)
    result = {
        "app": validated["app"]["name"],
        "environment": validated["app"]["environment"],
        "status": "pending",
        "deployment_mode": "real" if _real_deployment_enabled() else "dry_run",
        "validation_errors": [],
        "warnings": validated.get("warnings", []),
        "decision": decision,
        "pricing": _pricing_to_dict(pricing_estimates),
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
        add_deployment_record(result)
        return result

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
        add_deployment_record(result)
        return result

    selected_provider = decision["selected_provider"]

    if not _real_deployment_enabled():
        execution_provider = selected_provider
        provider = _provider_instance(execution_provider)
        deployment = provider.generate_plan(validated)
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
        add_deployment_record(result)
        return result

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
        add_deployment_record(result)
        return result

    if not _provider_deployment_allowed(execution_provider):
        provider = _provider_instance(execution_provider)
        plan = provider.generate_plan(validated)
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
        add_deployment_record(result)
        return result

    if execution_provider == "GCP":
        provider = _provider_instance(execution_provider)
        plan = provider.generate_plan(validated)
        deployment = {
            **plan,
            "status": "blocked_by_safety_flag",
            "deployment_mode": "real",
            "message": "Real GCP deployment is not implemented in this project yet. No gcloud command was executed.",
        }
        result.update(
            {
                "status": "blocked_by_safety_flag",
                "deployment_mode": "real",
                "deployment": deployment,
                "generated_commands": plan.get("generated_commands", []),
                "health_check": _skipped_health("Health check skipped because real GCP deployment is not implemented."),
            }
        )
        result["deployment_steps"].append(f"Execution provider: {execution_provider}")
        result["deployment_steps"].append(deployment["message"])
        result["logs"] = list(result["deployment_steps"])
        add_deployment_record(result)
        return result

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
        add_deployment_record(result)
        return result

    provider = _provider_instance(execution_provider)
    deployment = provider.deploy(validated)
    endpoints = deployment.get("service_endpoints", [])
    health_check = provider.health_check(deployment) if deployment.get("status") == "deployed" else _skipped_health(
        "Health check skipped because deployment did not complete successfully."
    )

    result.update(
        {
            "status": deployment.get("status", "unknown"),
            "deployment_mode": "real",
            "deployment": deployment,
            "generated_commands": deployment.get("generated_commands", []),
            "public_ip": deployment.get("public_ip"),
            "public_endpoints": endpoints,
            "health_check": health_check,
        }
    )
    result["deployment_steps"].append(f"Execution provider: {execution_provider}")
    result["deployment_steps"].append(deployment.get("message", "Deployment finished."))
    result["logs"] = list(result["deployment_steps"])
    add_deployment_record(result)
    return result


def _provider_instance(provider_name: str):
    provider_cls = PROVIDERS.get(provider_name)
    if not provider_cls:
        raise ValueError(f"Unsupported execution provider: {provider_name}")
    return provider_cls()


def _skipped_health(message: str) -> Dict[str, Any]:
    return {
        "status": "skipped",
        "passed": None,
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
