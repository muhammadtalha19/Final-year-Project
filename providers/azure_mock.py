from typing import Any, Dict

from decision_engine import PROVIDER_CATALOG
from providers.base import CloudProvider


class AzureMockProvider(CloudProvider):
    name = "Azure"

    def estimate(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return PROVIDER_CATALOG[self.name].copy()

    def deploy(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "status": "not_implemented",
            "message": "Azure deployment is not implemented; this provider is available for decision evaluation only.",
            "logs": ["Azure mock provider does not execute deployments."],
            "service_endpoints": [],
        }
