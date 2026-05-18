from abc import ABC, abstractmethod
from typing import Any, Dict


class CloudProvider(ABC):
    name = "base"

    @abstractmethod
    def estimate(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Return estimated provider metadata for the config."""

    @abstractmethod
    def generate_plan(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Return a provider-specific dry-run deployment plan without executing commands."""

    @abstractmethod
    def deploy(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Deploy the validated config and return deployment metadata."""

    def health_check(self, result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "skipped",
            "passed": None,
            "message": "Health check is not implemented for this provider.",
        }
