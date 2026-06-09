from pricing.models import PriceEstimate


STATIC_MONTHLY_PRICES = {
    "AWS": 18.0,
    "GCP": 12.0,
    "Azure": 15.0,
}


def get_static_estimate(provider: str, region: str = "") -> PriceEstimate:
    normalized_provider = provider.strip()
    monthly_cost = STATIC_MONTHLY_PRICES.get(normalized_provider)
    if monthly_cost is None:
        raise ValueError(f"No static fallback price is configured for provider: {provider}")

    return PriceEstimate(
        provider=normalized_provider,
        estimated_monthly_cost_usd=monthly_cost,
        hourly_cost_usd=None,
        pricing_type="fallback",
        pricing_source="static_fallback",
        region=region or "",
        notes=["Static fallback pricing estimate used."],
    )
