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

    @abstractmethod
    def delete(self, deployment_record: Dict[str, Any]) -> Dict[str, Any]:
        """Delete resources represented by a real deployment record."""

    def health_check(self, result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "result": "skipped",
            "status": "skipped",
            "passed": None,
            "url": None,
            "status_code": None,
            "response_time_ms": None,
            "attempts": 0,
            "message": "Health check is not implemented for this provider.",
        }

    def get_logs(self, deployment_record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "status": "not_implemented",
            "commands": [],
            "message": "Log retrieval is not implemented for this provider.",
        }
