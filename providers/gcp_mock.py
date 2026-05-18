import os
import shlex
from typing import Any, Dict

from config_schema import get_service_definitions
from decision_engine import PROVIDER_CATALOG
from providers.base import CloudProvider


class GCPMockProvider(CloudProvider):
    name = "GCP"

    def estimate(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return PROVIDER_CATALOG[self.name].copy()

    def generate_plan(self, config: Dict[str, Any]) -> Dict[str, Any]:
        region = os.getenv("GCP_REGION", "asia-south1")
        platform = os.getenv("GCP_PLATFORM", "managed")
        commands = []

        for service in get_service_definitions(config):
            command = [
                "gcloud",
                "run",
                "deploy",
                _service_name(config, service),
                "--image",
                service["image"],
                "--region",
                region,
                "--platform",
                platform,
                "--port",
                str(service["port"]),
                "--format",
                "json",
            ]
            if _is_public(config, service):
                command.append("--allow-unauthenticated")

            commands.append(
                {
                    "service": service["name"],
                    "command": command,
                    "command_string": shlex.join(command),
                }
            )

        return {
            "provider": self.name,
            "deployment_type": "CLOUD_RUN",
            "status": "dry_run",
            "deployment_mode": "dry_run",
            "region": region,
            "platform": platform,
            "required_env_vars": ["GCP_REGION", "GCP_PLATFORM"],
            "generated_commands": commands,
            "message": "GCP Cloud Run dry-run plan generated. No gcloud command was executed.",
            "logs": ["Dry-run only; subprocess and gcloud were not called."],
            "service_endpoints": [],
        }

    def deploy(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "status": "not_implemented",
            "message": "GCP deployment is not implemented; this provider is available for decision evaluation only.",
            "logs": ["GCP mock provider does not execute deployments."],
            "service_endpoints": [],
        }


def _service_name(config: Dict[str, Any], service: Dict[str, Any]) -> str:
    services = get_service_definitions(config)
    name = config.get("app", {}).get("name") if len(services) == 1 else service.get("name")
    return _safe_name(name or service.get("name") or "service")


def _safe_name(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "-" for character in value).strip("-") or "service"


def _is_public(config: Dict[str, Any], service: Dict[str, Any]) -> bool:
    requirements = config.get("requirements", {})
    return bool(requirements.get("public_access") or service.get("public"))
