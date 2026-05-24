import os
import shlex
import subprocess
import time
from typing import Any, Dict

from config_schema import get_service_definitions
from decision_engine import PROVIDER_CATALOG
from providers.base import CloudProvider


class AzureMockProvider(CloudProvider):
    name = "Azure"

    def __init__(self) -> None:
        self.resource_group = os.getenv("AZURE_RESOURCE_GROUP", "")
        self.location = os.getenv("AZURE_LOCATION", "")
        self.containerapp_env = os.getenv("AZURE_CONTAINERAPP_ENV", "")
        self.timeout_seconds = int(os.getenv("DEPLOYMENT_TIMEOUT_SECONDS", "180"))

    def estimate(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return PROVIDER_CATALOG[self.name].copy()

    def generate_plan(self, config: Dict[str, Any]) -> Dict[str, Any]:
        commands = []

        for service in get_service_definitions(config):
            ingress = "external" if _is_public(config, service) else "internal"
            resource_name = _service_name(config, service)
            command = [
                "az",
                "containerapp",
                "create",
                "--name",
                resource_name,
                "--resource-group",
                self.resource_group or "<AZURE_RESOURCE_GROUP>",
                "--environment",
                self.containerapp_env or "<AZURE_CONTAINERAPP_ENV>",
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
                    "resource_name": resource_name,
                    "command": command,
                    "command_string": shlex.join(command),
                }
            )

        return {
            "provider": self.name,
            "deployment_type": "AZURE_CONTAINER_APPS",
            "status": "dry_run",
            "deployment_mode": "dry_run",
            "location": self.location,
            "resource_group": self.resource_group,
            "containerapp_environment": self.containerapp_env,
            "required_env_vars": ["AZURE_RESOURCE_GROUP", "AZURE_CONTAINERAPP_ENV", "AZURE_LOCATION"],
            "generated_commands": commands,
            "message": "Azure Container Apps dry-run plan generated. No az command was executed.",
            "logs": ["Dry-run only; subprocess and Azure CLI were not called."],
            "endpoints": [],
            "service_endpoints": [],
        }

    def deploy(self, config: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._missing_config()
        if missing:
            return {
                "provider": self.name,
                "status": "configuration_error",
                "missing_vars": missing,
                "message": "Missing Azure environment variables: " + ", ".join(missing),
                "logs": [],
                "generated_commands": [],
                "endpoints": [],
                "service_endpoints": [],
            }

        plan = self.generate_plan(config)
        commands = plan.get("generated_commands", [])
        endpoints = []
        raw_outputs = []

        try:
            for command in commands:
                completed = subprocess.run(
                    command["command"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                fqdn = completed.stdout.strip()
                raw_outputs.append(
                    {
                        "service": command["service"],
                        "stdout": completed.stdout,
                        "stderr": completed.stderr,
                    }
                )
                if fqdn:
                    endpoints.append(
                        {
                            "name": command["service"],
                            "url": f"https://{fqdn}",
                            "fqdn": fqdn,
                        }
                    )

            return {
                "provider": self.name,
                "status": "deployed",
                "fqdn": endpoints[0]["fqdn"] if endpoints else None,
                "app_names": [command["resource_name"] for command in commands],
                "endpoints": endpoints,
                "service_endpoints": endpoints,
                "generated_commands": commands,
                "raw_output": raw_outputs,
                "message": "Azure Container Apps deployment completed through Azure CLI.",
                "logs": [f"Executed {len(commands)} Azure Container Apps command(s)."],
            }
        except subprocess.CalledProcessError as exc:
            return {
                "provider": self.name,
                "status": "failed",
                "message": exc.stderr or str(exc),
                "generated_commands": commands,
                "raw_output": {
                    "stdout": exc.stdout,
                    "stderr": exc.stderr,
                },
                "logs": [exc.stderr or str(exc)],
                "endpoints": [],
                "service_endpoints": [],
            }

    def delete(self, deployment_record: Dict[str, Any]) -> Dict[str, Any]:
        app_names = deployment_record.get("app_names") or []
        if not app_names:
            deployment = deployment_record.get("deployment", {})
            if isinstance(deployment, dict):
                app_names = deployment.get("app_names") or []
        if not app_names and deployment_record.get("app_name"):
            app_names = [_safe_name(deployment_record["app_name"])]

        if not app_names:
            return {
                "provider": self.name,
                "status": "delete_skipped",
                "app_name": None,
                "message": "Azure cleanup skipped because the deployment record does not contain an app name.",
            }

        if not self.resource_group:
            return {
                "provider": self.name,
                "status": "delete_failed",
                "app_name": app_names[0],
                "message": "Azure cleanup failed because AZURE_RESOURCE_GROUP is not configured.",
            }

        commands = [
            [
                "az",
                "containerapp",
                "delete",
                "--name",
                app_name,
                "--resource-group",
                self.resource_group,
                "--yes",
            ]
            for app_name in app_names
        ]

        try:
            for command in commands:
                subprocess.run(command, capture_output=True, text=True, check=True)
            return {
                "provider": self.name,
                "status": "deleted",
                "app_name": app_names[0],
                "app_names": app_names,
                "generated_commands": commands,
                "message": f"Azure Container App deletion completed for {', '.join(app_names)}.",
            }
        except subprocess.CalledProcessError as exc:
            return {
                "provider": self.name,
                "status": "delete_failed",
                "app_name": app_names[0],
                "app_names": app_names,
                "generated_commands": commands,
                "message": exc.stderr or str(exc),
            }

    def health_check(self, result: Dict[str, Any]) -> Dict[str, Any]:
        endpoints = result.get("service_endpoints") or result.get("endpoints") or []
        urls = [endpoint["url"] for endpoint in endpoints if endpoint.get("url")]

        if result.get("status") != "deployed" or not urls:
            return {
                "status": "skipped",
                "passed": None,
                "message": "Health check skipped because no public deployment endpoint is available.",
            }

        try:
            import requests
        except ImportError:
            return {
                "status": "skipped",
                "passed": None,
                "message": "Health check skipped because the requests package is not installed.",
            }

        last_error = None
        for _ in range(3):
            try:
                responses = [requests.get(url, timeout=5) for url in urls]
                if all(response.status_code < 400 for response in responses):
                    return {
                        "status": "passed",
                        "passed": True,
                        "message": "All public endpoints responded successfully.",
                    }
                last_error = "One or more endpoints returned HTTP 400 or higher."
            except requests.RequestException as exc:
                last_error = str(exc)
            time.sleep(3)

        return {
            "status": "failed",
            "passed": False,
            "message": last_error or "Timed out waiting for public endpoints to respond.",
        }

    def _missing_config(self):
        required = {
            "AZURE_RESOURCE_GROUP": self.resource_group,
            "AZURE_CONTAINERAPP_ENV": self.containerapp_env,
            "AZURE_LOCATION": self.location,
        }
        return [name for name, value in required.items() if not value]


def _service_name(config: Dict[str, Any], service: Dict[str, Any]) -> str:
    services = get_service_definitions(config)
    name = config.get("app", {}).get("name") if len(services) == 1 else service.get("name")
    return _safe_name(name or service.get("name") or "service")


def _safe_name(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "-" for character in value).strip("-") or "service"


def _is_public(config: Dict[str, Any], service: Dict[str, Any]) -> bool:
    requirements = config.get("requirements", {})
    return bool(requirements.get("public_access") or service.get("public"))
