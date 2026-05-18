import os
import shlex
from typing import Any, Dict

from config_schema import get_service_definitions
from decision_engine import PROVIDER_CATALOG
from providers.base import CloudProvider


class AzureMockProvider(CloudProvider):
    name = "Azure"

    def estimate(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return PROVIDER_CATALOG[self.name].copy()

    def generate_plan(self, config: Dict[str, Any]) -> Dict[str, Any]:
        resource_group = os.getenv("AZURE_RESOURCE_GROUP", "")
        containerapp_env = os.getenv("AZURE_CONTAINERAPP_ENV", "")
        location = os.getenv("AZURE_LOCATION", "eastus")
        commands = []

        for service in get_service_definitions(config):
            ingress = "external" if _is_public(config, service) else "internal"
            command = [
                "az",
                "containerapp",
                "create",
                "--name",
                _service_name(config, service),
                "--resource-group",
                resource_group or "<AZURE_RESOURCE_GROUP>",
                "--environment",
                containerapp_env or "<AZURE_CONTAINERAPP_ENV>",
                "--image",
                service["image"],
                "--target-port",
                str(service["port"]),
                "--ingress",
                ingress,
                "--query",
                "properties.configuration.ingress.fqdn",
                "--output",
                "tsv",
            ]
            commands.append(
                {
                    "service": service["name"],
                    "command": command,
                    "command_string": shlex.join(command),
                }
            )

        return {
            "provider": self.name,
            "deployment_type": "AZURE_CONTAINER_APPS",
            "status": "dry_run",
            "deployment_mode": "dry_run",
            "location": location,
            "resource_group": resource_group,
            "containerapp_environment": containerapp_env,
            "required_env_vars": ["AZURE_RESOURCE_GROUP", "AZURE_CONTAINERAPP_ENV"],
            "generated_commands": commands,
            "message": "Azure Container Apps dry-run plan generated. No az command was executed.",
            "logs": ["Dry-run only; subprocess and Azure CLI were not called."],
            "service_endpoints": [],
        }

    def deploy(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "status": "not_implemented",
            "message": "Azure deployment is not implemented; this provider is available for decision evaluation only.",
            "logs": ["Azure mock provider does not execute deployments."],
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
