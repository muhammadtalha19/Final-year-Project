import os
from copy import deepcopy
from typing import Any, Dict, Optional

import yaml

from config_schema import ConfigValidationError, get_service_definitions, validate_config
from decision_engine import select_provider
from deployment_history import add_deployment_record, get_deployment_record, update_deployment_record
from docker_image_validation import validate_docker_images
from pricing.models import PriceEstimate
from pricing.pricing_service import get_price_estimates
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
            "environment": _safe_app_value(config, "environment"),
            "status": "validation_failed",
            "deployment_mode": "dry_run" if not _real_deployment_enabled() else "real",
            "validation_errors": exc.errors,
            "warnings": [],
            "decision": {},
            "pricing": {},
            "provider_readiness": {},
            "docker_image_validation": {},
            "approval": {},
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
    image_validation = validate_docker_images(validated)
    result = {
        "app": validated["app"]["name"],
        "environment": validated["app"]["environment"],
        "status": "pending",
        "deployment_mode": "real" if _real_deployment_enabled() else "dry_run",
        "validation_errors": [],
        "warnings": validated.get("warnings", []),
        "decision": decision,
        "pricing": _pricing_to_dict(pricing_estimates),
        "provider_readiness": {},
        "docker_image_validation": image_validation,
        "approval": {},
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
    provider_readiness = check_provider_readiness(selected_provider, validated)
    result["provider_readiness"] = provider_readiness

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

    provider = _provider_instance(execution_provider)
    plan = provider.generate_plan(validated)

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
        add_deployment_record(result)
        return result

    if execution_provider == "GCP":
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
        add_deployment_record(result)
        return result

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
        add_deployment_record(result)
        return result

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


def delete_deployment(deployment_id: str) -> Dict[str, Any]:
    record = get_deployment_record(deployment_id)
    if not record:
        return {
            "provider": None,
            "status": "delete_skipped",
            "message": "Cleanup skipped because the deployment record was not found.",
        }

    execution_provider = record.get("execution_provider")
    status = record.get("status")

    if status not in {"deployed", "delete_failed"}:
        delete_result = {
            "provider": execution_provider,
            "status": "delete_skipped",
            "message": "Cleanup skipped because this record is not an active real deployment.",
        }
    elif execution_provider not in {"AWS", "Azure"}:
        delete_result = {
            "provider": execution_provider,
            "status": "delete_skipped",
            "message": "Cleanup skipped because real GCP cleanup is not implemented.",
        }
    else:
        delete_result = _provider_instance(execution_provider).delete(record)

    update_deployment_record(
        deployment_id,
        {
            "status": delete_result["status"],
            "cleanup_result": delete_result,
        },
    )
    return delete_result


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
