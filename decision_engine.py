from typing import Any, Dict, List, Optional

from pricing.models import PriceEstimate
from pricing.pricing_service import get_price_estimates


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
        "execution_supported": True,
    },
    "Azure": {
        "estimated_cost_usd": 15,
        "uptime_percent": 99.90,
        "supported_deployment": ["container"],
        "regions": ["asia", "europe", "us"],
        "execution_supported": True,
    },
}


def select_provider(
    config: Dict[str, Any],
    price_estimates: Optional[dict[str, PriceEstimate]] = None,
) -> Dict[str, Any]:
    requirements = config.get("requirements", {})
    deployment_type = config.get("deployment", {}).get("type", "container")
    max_cost = requirements.get("max_monthly_cost_usd")
    min_uptime = requirements.get("min_uptime_percent")
    preferred_region = requirements.get("preferred_region")
    selection = config.get("selection", {})
    selection_mode = selection.get("mode", "auto")
    manual_provider = selection.get("provider") if selection_mode == "manual" else None
    price_estimates = price_estimates or _safe_price_estimates(config)

    evaluated = [
        _evaluate_provider(
            name,
            profile,
            deployment_type,
            max_cost,
            min_uptime,
            preferred_region,
            price_estimates.get(name),
        )
        for name, profile in PROVIDER_CATALOG.items()
    ]
    eligible = [provider for provider in evaluated if provider["eligible"]]
    recommended = _best_provider(eligible)

    selected_provider: Optional[str] = None
    execution_provider: Optional[str] = None
    recommended_provider = recommended["provider"] if recommended else None
    status = "no_provider_eligible"

    if selection_mode == "manual":
        manual_evaluation = next((item for item in evaluated if item["provider"] == manual_provider), None)
        if manual_evaluation and manual_evaluation["eligible"]:
            selected_provider = manual_provider
            execution_provider = manual_provider
            status = "selected"
            reason = (
                f"User manually selected {manual_provider}, and it satisfies the cost, uptime, deployment, "
                "and region requirements."
            )
        else:
            status = "manual_selection_blocked"
            rejection_reasons = manual_evaluation.get("rejection_reasons", []) if manual_evaluation else []
            reason = _manual_blocked_reason(manual_provider, rejection_reasons, recommended_provider)
    elif recommended:
        selected = recommended
        selected_provider = selected["provider"]
        execution_provider = _execution_provider_for(selected_provider, evaluated)
        status = "selected"
        reason = _decision_reason(selected_provider, execution_provider)
    else:
        reason = "No provider satisfied the requested cost, uptime, deployment, and region constraints."

    return {
        "status": status,
        "selection_mode": selection_mode,
        "manual_provider": manual_provider,
        "recommended_provider": recommended_provider,
        "selected_provider": selected_provider,
        "execution_provider": execution_provider,
        "selected_cloud": selected_provider,
        "execution_cloud": execution_provider,
        "reason": reason,
        "evaluated_providers": evaluated,
        "audit_trail": {
            "chosen_provider": selected_provider,
            "execution_provider": execution_provider,
            "decision_reason": reason,
            "provider_evaluations": evaluated,
        },
    }


def _best_provider(eligible: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            item["score"],
            -item["estimated_cost_usd"],
            item["uptime_percent"],
        ),
    )


def _evaluate_provider(
    name: str,
    profile: Dict[str, Any],
    deployment_type: str,
    max_cost: Optional[float],
    min_uptime: Optional[float],
    preferred_region: Optional[str],
    price_estimate: Optional[PriceEstimate],
) -> Dict[str, Any]:
    rejection_reasons: List[str] = []

    price_estimate = price_estimate or _fallback_price_estimate(name, preferred_region or "")
    estimated_cost = price_estimate.estimated_monthly_cost_usd
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
        score = _score_provider(profile, estimated_cost, max_cost, min_uptime, preferred_region)

    return {
        "provider": name,
        "eligible": eligible,
        "estimated_cost_usd": estimated_cost,
        "pricing_type": price_estimate.pricing_type,
        "pricing_source": price_estimate.pricing_source,
        "pricing_notes": price_estimate.notes,
        "uptime_percent": uptime,
        "score": round(score, 2),
        "rejection_reasons": rejection_reasons,
        "exclusion_reason": "; ".join(rejection_reasons),
        "region_support_notes": (
            f"Preferred region '{preferred_region}' is supported."
            if preferred_region and preferred_region in regions
            else f"Supported regions: {', '.join(regions)}."
        ),
        "execution_supported": profile["execution_supported"],
    }


def _score_provider(
    profile: Dict[str, Any],
    estimated_cost: float,
    max_budget: Optional[float],
    min_uptime: Optional[float],
    preferred_region: Optional[str],
) -> float:
    if max_budget:
        cost_score = max(0.0, (1 - (float(estimated_cost) / float(max_budget))) * 50)
    else:
        cost_score = max(0.0, 100.0 - float(estimated_cost))
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


def _manual_blocked_reason(
    manual_provider: Optional[str],
    rejection_reasons: List[str],
    recommended_provider: Optional[str],
) -> str:
    provider_label = manual_provider or "the requested provider"
    reason = f"User manually selected {provider_label}, but it does not satisfy the hard requirements."
    if rejection_reasons:
        reason += " Blocking reason(s): " + "; ".join(rejection_reasons)
    if recommended_provider:
        reason += f" Recommended eligible provider: {recommended_provider}."
    return reason


def _safe_price_estimates(config: Dict[str, Any]) -> dict[str, PriceEstimate]:
    try:
        return get_price_estimates(config)
    except Exception:
        preferred_region = config.get("requirements", {}).get("preferred_region", "")
        return {
            provider: _fallback_price_estimate(provider, preferred_region)
            for provider in PROVIDER_CATALOG
        }


def _fallback_price_estimate(provider: str, region: str = "") -> PriceEstimate:
    profile = PROVIDER_CATALOG[provider]
    return PriceEstimate(
        provider=provider,
        estimated_monthly_cost_usd=float(profile["estimated_cost_usd"]),
        hourly_cost_usd=None,
        pricing_type="fallback",
        pricing_source="provider_catalog",
        region=region,
        notes=["Provider catalog fallback pricing used."],
    )
