from typing import Any, Dict

from pricing.azure_pricing import get_azure_estimate
from pricing.models import PriceEstimate
from pricing.static_fallback import get_static_estimate


def get_price_estimates(config: Dict[str, Any]) -> dict[str, PriceEstimate]:
    requirements = config.get("requirements", {}) if isinstance(config, dict) else {}
    region = requirements.get("preferred_region") or ""

    estimates: dict[str, PriceEstimate] = {}
    for provider in ("AWS", "GCP"):
        estimates[provider] = _safe_static_estimate(provider, region)

    try:
        estimates["Azure"] = get_azure_estimate(region=region)
    except Exception:
        estimates["Azure"] = _safe_static_estimate("Azure", region)
        estimates["Azure"].notes = ["Azure live pricing unavailable; static fallback used."]

    return estimates


def _safe_static_estimate(provider: str, region: str) -> PriceEstimate:
    try:
        return get_static_estimate(provider, region=region)
    except Exception:
        return PriceEstimate(
            provider=provider,
            estimated_monthly_cost_usd=0.0,
            hourly_cost_usd=None,
            pricing_type="fallback",
            pricing_source="static_fallback_error",
            region=region,
            notes=["Pricing lookup failed; defaulted to 0.0 for safe error reporting."],
        )
