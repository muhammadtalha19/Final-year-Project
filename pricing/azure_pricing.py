import os
from typing import Any, Dict, Optional

import requests

from pricing.models import PriceEstimate
from pricing.static_fallback import get_static_estimate


AZURE_RETAIL_PRICES_URL = "https://prices.azure.com/api/retail/prices"
HOURS_PER_MONTH = 730
FALLBACK_NOTE = "Azure live pricing unavailable; static fallback used."

REGION_TO_AZURE_ARM_REGION = {
    "asia": "southeastasia",
    "europe": "westeurope",
    "us": "eastus",
}


def get_azure_estimate(region: str = "", live_pricing_enabled: Optional[bool] = None) -> PriceEstimate:
    if live_pricing_enabled is None:
        live_pricing_enabled = _live_pricing_enabled()

    if not live_pricing_enabled:
        return _azure_fallback(region)

    azure_region = _azure_region(region)

    try:
        response = requests.get(
            AZURE_RETAIL_PRICES_URL,
            params={
                "api-version": "2023-01-01-preview",
                "$filter": (
                    "serviceName eq 'Virtual Machines' "
                    f"and armRegionName eq '{azure_region}' "
                    "and armSkuName eq 'Standard_B1s' "
                    "and priceType eq 'Consumption'"
                ),
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        item = _first_hourly_price_item(payload)
        if not item:
            return _azure_fallback(region)

        hourly_cost = float(item["retailPrice"])
        return PriceEstimate(
            provider="Azure",
            estimated_monthly_cost_usd=round(hourly_cost * HOURS_PER_MONTH, 2),
            hourly_cost_usd=hourly_cost,
            pricing_type="live",
            pricing_source="Azure Retail Prices API",
            region=item.get("armRegionName") or azure_region,
            notes=[
                "Estimated from Azure Retail Prices API using Standard_B1s VM consumption pricing.",
                "This is an MVP estimate and not a final Azure bill.",
            ],
        )
    except Exception:
        return _azure_fallback(region)


def _first_hourly_price_item(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    items = payload.get("Items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None

    for item in items:
        if not isinstance(item, dict):
            continue
        price = item.get("retailPrice")
        unit = str(item.get("unitOfMeasure", "")).lower()
        if isinstance(price, (int, float)) and price > 0 and "hour" in unit:
            return item
    return None


def _azure_fallback(region: str = "") -> PriceEstimate:
    estimate = get_static_estimate("Azure", region=region)
    estimate.notes = [FALLBACK_NOTE]
    return estimate


def _azure_region(region: str = "") -> str:
    normalized = (region or "").strip().lower()
    return REGION_TO_AZURE_ARM_REGION.get(normalized, normalized or "eastus")


def _live_pricing_enabled() -> bool:
    return os.getenv("ENABLE_LIVE_PRICING", "false").strip().lower() == "true"
