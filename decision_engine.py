from typing import Any, Dict, List, Optional


PROVIDER_CATALOG: Dict[str, Dict[str, Any]] = {
    "AWS": {
        "estimated_cost_usd": 18,
        "uptime_percent": 99.99,
        "supported_deployment": ["container"],
        "regions": ["asia", "europe", "us"],
        "execution_supported": True,
    },
    "GCP": {
        "estimated_cost_usd": 12,
        "uptime_percent": 99.95,
        "supported_deployment": ["container"],
        "regions": ["asia", "europe", "us"],
        "execution_supported": False,
    },
    "Azure": {
        "estimated_cost_usd": 15,
        "uptime_percent": 99.90,
        "supported_deployment": ["container"],
        "regions": ["asia", "europe", "us"],
        "execution_supported": False,
    },
}


def select_provider(config: Dict[str, Any]) -> Dict[str, Any]:
    requirements = config.get("requirements", {})
    deployment_type = config.get("deployment", {}).get("type", "container")
    max_cost = requirements.get("max_monthly_cost_usd")
    min_uptime = requirements.get("min_uptime_percent")
    preferred_region = requirements.get("preferred_region")

    evaluated = [
        _evaluate_provider(name, profile, deployment_type, max_cost, min_uptime, preferred_region)
        for name, profile in PROVIDER_CATALOG.items()
    ]
    eligible = [provider for provider in evaluated if provider["eligible"]]

    selected_provider: Optional[str] = None
    execution_provider: Optional[str] = None

    if eligible:
        selected = max(
            eligible,
            key=lambda item: (
                item["score"],
                -item["estimated_cost_usd"],
                item["uptime_percent"],
            ),
        )
        selected_provider = selected["provider"]
        execution_provider = _execution_provider_for(selected_provider, evaluated)
        reason = _decision_reason(selected_provider, execution_provider)
    else:
        reason = "No provider satisfied the requested cost, uptime, deployment, and region constraints."

    return {
        "selected_provider": selected_provider,
        "execution_provider": execution_provider,
        "selected_cloud": selected_provider,
        "execution_cloud": execution_provider,
        "reason": reason,
        "evaluated_providers": evaluated,
    }


def _evaluate_provider(
    name: str,
    profile: Dict[str, Any],
    deployment_type: str,
    max_cost: Optional[float],
    min_uptime: Optional[float],
    preferred_region: Optional[str],
) -> Dict[str, Any]:
    rejection_reasons: List[str] = []

    estimated_cost = profile["estimated_cost_usd"]
    uptime = profile["uptime_percent"]
    supported_deployments = profile["supported_deployment"]
    regions = profile["regions"]

    if max_cost is not None and estimated_cost > max_cost:
        rejection_reasons.append(f"Estimated cost ${estimated_cost}/month exceeds limit ${max_cost}/month.")
    if min_uptime is not None and uptime < min_uptime:
        rejection_reasons.append(f"Uptime {uptime}% is below required {min_uptime}%.")
    if deployment_type not in supported_deployments:
        rejection_reasons.append(f"Deployment type '{deployment_type}' is not supported.")
    if preferred_region and preferred_region not in regions:
        rejection_reasons.append(f"Preferred region '{preferred_region}' is not supported.")

    eligible = not rejection_reasons
    score = 0.0
    if eligible:
        score = _score_provider(profile, min_uptime, preferred_region)

    return {
        "provider": name,
        "eligible": eligible,
        "estimated_cost_usd": estimated_cost,
        "uptime_percent": uptime,
        "score": round(score, 2),
        "rejection_reasons": rejection_reasons,
        "execution_supported": profile["execution_supported"],
    }


def _score_provider(
    profile: Dict[str, Any],
    min_uptime: Optional[float],
    preferred_region: Optional[str],
) -> float:
    cost_score = max(0.0, 100.0 - float(profile["estimated_cost_usd"]))
    uptime_margin = float(profile["uptime_percent"]) - float(min_uptime or 0)
    uptime_score = max(0.0, uptime_margin * 10)
    region_bonus = 5.0 if preferred_region and preferred_region in profile["regions"] else 0.0
    execution_bonus = 1.0 if profile["execution_supported"] else 0.0
    return cost_score + uptime_score + region_bonus + execution_bonus


def _execution_provider_for(selected_provider: str, evaluated: List[Dict[str, Any]]) -> Optional[str]:
    selected_profile = PROVIDER_CATALOG[selected_provider]
    if selected_profile["execution_supported"]:
        return selected_provider

    aws_result = next((item for item in evaluated if item["provider"] == "AWS"), None)
    if aws_result and aws_result["eligible"]:
        return "AWS"
    return None


def _decision_reason(selected_provider: str, execution_provider: Optional[str]) -> str:
    if selected_provider == execution_provider:
        return f"{selected_provider} was selected because it satisfies the hard constraints and has the best score."

    if execution_provider == "AWS":
        return (
            f"Selected provider is {selected_provider} based on requirements, but current execution backend supports "
            "AWS only. AWS is also eligible, so AWS can be used as the execution provider for the working backend."
        )

    return (
        f"Selected provider is {selected_provider} based on requirements, but current execution backend supports "
        "AWS only. AWS is not eligible for these requirements, so deployment is stopped before execution."
    )
