import json
import os
import shlex
import subprocess
import tempfile
import time
from typing import Any, Dict
from urllib.parse import urlparse, urlunparse

from config_schema import get_service_definitions
from decision_engine import PROVIDER_CATALOG
from providers.base import CloudProvider


class GCPMockProvider(CloudProvider):
    name = "GCP"

    def __init__(self) -> None:
        self.project_id = os.getenv("GCP_PROJECT_ID", "")
        self.region = os.getenv("GCP_REGION", "asia-south1")
        self.platform = os.getenv("GCP_PLATFORM", "managed")
        self.service_account_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "")
        self._using_cloud_account = False

    def estimate(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return PROVIDER_CATALOG[self.name].copy()

    def generate_plan(self, config: Dict[str, Any], cloud_account: Any = None) -> Dict[str, Any]:
        values = self._values_for_account(cloud_account)
        commands = []

        for service in get_service_definitions(config):
            resource_name = _service_name(config, service)
            command = [
                "gcloud",
                "run",
                "deploy",
                resource_name,
                "--image",
                service["image"],
                "--region",
                values["region"],
                "--platform",
                values["platform"],
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
                    "resource_name": resource_name,
                    "command": command,
                    "command_string": shlex.join(command),
                }
            )

        return {
            "provider": self.name,
            "deployment_type": "CLOUD_RUN",
            "status": "dry_run",
            "deployment_mode": "dry_run",
            "region": values["region"],
            "platform": values["platform"],
            "project_id": values["project_id"],
            "resources": config.get("resources", {}),
            "required_env_vars": ["GCP_PROJECT_ID", "GCP_REGION", "GCP_PLATFORM"],
            "generated_commands": commands,
            "message": "GCP Cloud Run dry-run plan generated. No gcloud command was executed.",
            "logs": ["Dry-run only; subprocess and gcloud were not called."],
            "service_endpoints": [],
        }

    def deploy(self, config: Dict[str, Any], cloud_account: Any = None) -> Dict[str, Any]:
        self._apply_cloud_account(cloud_account)
        missing = self._missing_config()
        if missing:
            return {
                "provider": self.name,
                "status": "configuration_error",
                "missing_vars": missing,
                "message": "Missing GCP cloud account configuration: " + ", ".join(missing),
                "action_hint": "Update your connected GCP account before enabling real GCP deployment.",
                "generated_commands": [],
                "logs": [],
                "endpoints": [],
                "service_endpoints": [],
            }

        plan = self.generate_plan(config, cloud_account)
        commands = plan.get("generated_commands", [])
        endpoints = []
        raw_outputs = []
        service_names = []
        run_kwargs = {"capture_output": True, "text": True, "check": True}
        temp_key_path = None
        env = None

        try:
            env, temp_key_path = self._subprocess_env()
            if env:
                run_kwargs["env"] = env
            for command in commands:
                completed = subprocess.run(
                    command["command"],
                    **run_kwargs,
                )
                payload = json.loads(completed.stdout or "{}")
                url = payload.get("status", {}).get("url")
                service_names.append(command["resource_name"])
                raw_outputs.append(
                    {
                        "service": command["service"],
                        "stdout": completed.stdout,
                        "stderr": completed.stderr,
                    }
                )
                if url:
                    endpoints.append(
                        {
                            "name": command["service"],
                            "url": url,
                        }
                    )

            return {
                "provider": self.name,
                "status": "deployed",
                "service_name": service_names[0] if service_names else None,
                "service_names": service_names,
                "url": endpoints[0]["url"] if endpoints else None,
                "endpoints": endpoints,
                "service_endpoints": endpoints,
                "generated_commands": commands,
                "raw_output": raw_outputs,
                "message": "GCP Cloud Run deployment completed through gcloud.",
                "logs": [f"Executed {len(commands)} GCP Cloud Run command(s)."],
            }
        except subprocess.CalledProcessError as exc:
            return {
                "provider": self.name,
                "status": "failed",
                "message": exc.stderr or str(exc),
                "stderr": exc.stderr,
                "action_hint": "Run gcloud auth login, set the project, enable Cloud Run API, and verify region permissions.",
                "generated_commands": commands,
                "raw_output": {
                    "stdout": exc.stdout,
                    "stderr": exc.stderr,
                },
                "logs": [exc.stderr or str(exc)],
                "endpoints": [],
                "service_endpoints": [],
            }
        except (json.JSONDecodeError, TypeError) as exc:
            return {
                "provider": self.name,
                "status": "failed",
                "message": f"Unable to parse gcloud JSON output: {exc}",
                "stderr": "",
                "action_hint": "Rerun the generated gcloud command and confirm it returns JSON output.",
                "generated_commands": commands,
                "logs": [str(exc)],
                "endpoints": [],
                "service_endpoints": [],
            }
        finally:
            if temp_key_path:
                try:
                    os.unlink(temp_key_path)
                except OSError:
                    pass

    def delete(self, deployment_record: Dict[str, Any], cloud_account: Any = None) -> Dict[str, Any]:
        self._apply_cloud_account(cloud_account)
        service_names = deployment_record.get("service_names") or []
        if not service_names:
            deployment = deployment_record.get("deployment", {})
            if isinstance(deployment, dict):
                service_names = deployment.get("service_names") or []
                if not service_names and deployment.get("service_name"):
                    service_names = [deployment["service_name"]]
        if not service_names and deployment_record.get("app_name"):
            service_names = [_safe_name(deployment_record["app_name"])]

        if not service_names:
            return {
                "provider": self.name,
                "status": "delete_skipped",
                "service_name": None,
                "message": "GCP cleanup skipped because the deployment record does not contain a Cloud Run service name.",
            }

        commands = [
            [
                "gcloud",
                "run",
                "services",
                "delete",
                service_name,
                "--region",
                self.region,
                "--quiet",
            ]
            for service_name in service_names
        ]
        run_kwargs = {"capture_output": True, "text": True, "check": True}
        temp_key_path = None
        env = None

        try:
            env, temp_key_path = self._subprocess_env()
            if env:
                run_kwargs["env"] = env
            for command in commands:
                subprocess.run(command, **run_kwargs)
            return {
                "provider": self.name,
                "status": "deleted",
                "service_name": service_names[0],
                "service_names": service_names,
                "generated_commands": commands,
                "message": f"GCP Cloud Run deletion completed for {', '.join(service_names)}.",
            }
        except subprocess.CalledProcessError as exc:
            return {
                "provider": self.name,
                "status": "delete_failed",
                "service_name": service_names[0],
                "service_names": service_names,
                "generated_commands": commands,
                "message": exc.stderr or str(exc),
            }
        finally:
            if temp_key_path:
                try:
                    os.unlink(temp_key_path)
                except OSError:
                    pass

    def health_check(self, result: Dict[str, Any]) -> Dict[str, Any]:
        endpoints = result.get("service_endpoints") or result.get("endpoints") or []
        urls = [_health_url(endpoint["url"], result.get("health_check_path", "/")) for endpoint in endpoints if endpoint.get("url")]

        if result.get("status") != "deployed" or not urls:
            return {
                "result": "skipped",
                "status": "skipped",
                "passed": None,
                "url": None,
                "status_code": None,
                "response_time_ms": None,
                "attempts": 0,
                "message": "Health check skipped because no public deployment endpoint is available.",
            }

        try:
            import requests
        except ImportError:
            return {
                "result": "skipped",
                "status": "skipped",
                "passed": None,
                "url": urls[0],
                "status_code": None,
                "response_time_ms": None,
                "attempts": 0,
                "message": "Health check skipped because the requests package is not installed.",
            }

        attempts = 0
        last_status_code = None
        last_response_time_ms = None
        last_error = None
        for _ in range(3):
            try:
                attempts += 1
                started = time.perf_counter()
                response = requests.get(urls[0], timeout=5)
                last_response_time_ms = round((time.perf_counter() - started) * 1000, 2)
                last_status_code = response.status_code
                if response.status_code < 400:
                    return {
                        "result": "passed",
                        "status": "passed",
                        "passed": True,
                        "url": urls[0],
                        "status_code": last_status_code,
                        "response_time_ms": last_response_time_ms,
                        "attempts": attempts,
                        "message": "Public endpoint responded successfully.",
                    }
                last_error = f"{urls[0]} returned HTTP {response.status_code}."
            except requests.RequestException as exc:
                last_error = str(exc)
            time.sleep(3)

        return {
            "result": "failed",
            "status": "failed",
            "passed": False,
            "url": urls[0],
            "status_code": last_status_code,
            "response_time_ms": last_response_time_ms,
            "attempts": attempts,
            "message": last_error or "Timed out waiting for public endpoint to respond.",
        }

    def get_logs(self, deployment_record: Dict[str, Any]) -> Dict[str, Any]:
        service_names = deployment_record.get("service_names") or []
        if not service_names and deployment_record.get("app_name"):
            service_names = [_safe_name(deployment_record["app_name"])]
        commands = [
            {
                "label": f"GCP logs for {service_name}",
                "command": [
                    "gcloud",
                    "run",
                    "services",
                    "logs",
                    "read",
                    service_name,
                    "--region",
                    self.region,
                ],
                "command_string": shlex.join(
                    [
                        "gcloud",
                        "run",
                        "services",
                        "logs",
                        "read",
                        service_name,
                        "--region",
                        self.region,
                    ]
                ),
            }
            for service_name in service_names
        ]
        return {
            "provider": self.name,
            "status": "plan_only",
            "commands": commands,
            "message": "GCP log commands are generated only; no gcloud logs command was executed.",
        }

    def _missing_config(self):
        required = {
            "GCP_PROJECT_ID": self.project_id,
            "GCP_REGION": self.region,
            "GCP_PLATFORM": self.platform,
        }
        if self._using_cloud_account:
            required["GCP_SERVICE_ACCOUNT_JSON"] = self.service_account_json
        return [name for name, value in required.items() if not value]

    def _apply_cloud_account(self, cloud_account: Any = None) -> None:
        credentials = _credentials_from_cloud_account(cloud_account)
        if not credentials:
            return
        self._using_cloud_account = True
        self.project_id = credentials.get("GCP_PROJECT_ID") or self.project_id
        self.region = credentials.get("GCP_REGION") or self.region
        self.platform = credentials.get("GCP_PLATFORM") or self.platform
        self.service_account_json = credentials.get("GCP_SERVICE_ACCOUNT_JSON") or self.service_account_json

    def _values_for_account(self, cloud_account: Any = None) -> Dict[str, str]:
        credentials = _credentials_from_cloud_account(cloud_account)
        return {
            "project_id": credentials.get("GCP_PROJECT_ID") or self.project_id,
            "region": credentials.get("GCP_REGION") or self.region,
            "platform": credentials.get("GCP_PLATFORM") or self.platform,
        }

    def _subprocess_env(self):
        if not self._using_cloud_account:
            return None, None
        env = os.environ.copy()
        env["CLOUDSDK_CORE_PROJECT"] = self.project_id
        if not self.service_account_json:
            return env, None
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, prefix="fyp-gcp-", suffix=".json")
        try:
            handle.write(self.service_account_json)
            temp_path = handle.name
        finally:
            handle.close()
        env["GOOGLE_APPLICATION_CREDENTIALS"] = temp_path
        return env, temp_path


def _service_name(config: Dict[str, Any], service: Dict[str, Any]) -> str:
    services = get_service_definitions(config)
    name = config.get("app", {}).get("name") if len(services) == 1 else service.get("name")
    return _safe_name(name or service.get("name") or "service")


def _safe_name(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "-" for character in value).strip("-") or "service"


def _credentials_from_cloud_account(cloud_account: Any = None) -> Dict[str, Any]:
    if not cloud_account:
        return {}
    if isinstance(cloud_account, dict):
        return cloud_account
    if hasattr(cloud_account, "get_credentials"):
        return cloud_account.get_credentials()
    return {}


def _is_public(config: Dict[str, Any], service: Dict[str, Any]) -> bool:
    requirements = config.get("requirements", {})
    return bool(requirements.get("public_access") or service.get("public"))


def _health_url(url: str, path: str) -> str:
    if not path or path == "/":
        return url
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=path, query="", fragment=""))
