import os
import re
import shlex
import time
from typing import Any, Dict, List

from config_schema import get_service_definitions
from decision_engine import PROVIDER_CATALOG
from providers.base import CloudProvider

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed in the project environment.
    def load_dotenv() -> None:
        return None


load_dotenv()


class AWSProvider(CloudProvider):
    name = "AWS"

    def __init__(self) -> None:
        self.region = os.getenv("AWS_REGION")
        self.ami_id = os.getenv("AWS_AMI_ID")
        self.instance_type = os.getenv("AWS_INSTANCE_TYPE", "t3.micro")
        self.key_name = os.getenv("AWS_KEY_NAME")
        self.security_group_id = os.getenv("AWS_SECURITY_GROUP_ID")
        self.subnet_id = os.getenv("AWS_SUBNET_ID")
        self.timeout_seconds = int(os.getenv("DEPLOYMENT_TIMEOUT_SECONDS", "180"))

    def estimate(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return PROVIDER_CATALOG[self.name].copy()

    def generate_plan(self, config: Dict[str, Any]) -> Dict[str, Any]:
        services = get_service_definitions(config)
        first_service = services[0] if services else {}
        generated_commands = [
            {
                "service": service["name"],
                "command": [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    _safe_name(service["name"]),
                    "-p",
                    f"{int(service['port'])}:{int(service['port'])}",
                    "--restart",
                    "unless-stopped",
                    service["image"],
                ],
                "command_string": (
                    "docker run -d "
                    f"--name {_safe_name(service['name'])} "
                    f"-p {int(service['port'])}:{int(service['port'])} "
                    f"--restart unless-stopped {shlex.quote(service['image'])}"
                ),
            }
            for service in services
        ]

        return {
            "provider": self.name,
            "deployment_type": "EC2_DOCKER",
            "status": "dry_run",
            "deployment_mode": "dry_run",
            "image": first_service.get("image"),
            "port": first_service.get("port"),
            "region": self.region or "",
            "instance_type": self.instance_type,
            "required_env_vars": [
                "AWS_REGION",
                "AWS_AMI_ID",
                "AWS_KEY_NAME",
                "AWS_SECURITY_GROUP_ID",
                "AWS_SUBNET_ID",
            ],
            "services": services,
            "generated_commands": generated_commands,
            "message": "AWS EC2 Docker dry-run plan generated. No EC2 instance was launched.",
            "logs": ["Dry-run only; boto3 was not called."],
            "service_endpoints": [],
        }

    def deploy(self, config: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._missing_config()
        if missing:
            return {
                "provider": self.name,
                "status": "configuration_error",
                "missing_vars": missing,
                "message": "Missing AWS environment variables: " + ", ".join(missing),
                "logs": [],
                "generated_commands": [],
                "endpoints": [],
                "service_endpoints": [],
            }

        services = get_service_definitions(config)
        if not services:
            return {
                "provider": self.name,
                "status": "validation_error",
                "message": "No services were found to deploy.",
                "logs": [],
                "generated_commands": [],
                "endpoints": [],
                "service_endpoints": [],
            }

        app_name = config["app"]["name"]
        user_data = self._build_user_data(services)
        generated_commands = self.generate_plan(config).get("generated_commands", [])

        try:
            ec2 = self._client()
            response = ec2.run_instances(
                ImageId=self.ami_id,
                InstanceType=self.instance_type,
                KeyName=self.key_name,
                SecurityGroupIds=[self.security_group_id],
                SubnetId=self.subnet_id,
                UserData=user_data,
                MinCount=1,
                MaxCount=1,
                TagSpecifications=[
                    {
                        "ResourceType": "instance",
                        "Tags": [
                            {"Key": "Name", "Value": _safe_name(f"fyp-{app_name}")},
                        ],
                    }
                ],
            )

            instance_id = response["Instances"][0]["InstanceId"]
            ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])
            time.sleep(40)

            description = ec2.describe_instances(InstanceIds=[instance_id])
            instance = description["Reservations"][0]["Instances"][0]
            public_ip = instance.get("PublicIpAddress")
            endpoints = _service_endpoints(public_ip, services)

            return {
                "provider": self.name,
                "status": "deployed",
                "instance_id": instance_id,
                "public_ip": public_ip,
                "endpoints": endpoints,
                "service_endpoints": endpoints,
                "generated_commands": generated_commands,
                "user_data_summary": [
                    "Install Docker",
                    "Start and enable Docker",
                    f"Pull and run {len(services)} container image(s)",
                ],
                "message": "EC2 instance launched and Docker containers requested through user data.",
                "logs": [
                    f"EC2 instance launched: {instance_id}",
                    f"Configured {len(services)} Docker container command(s) through user data.",
                ],
            }
        except Exception as exc:  # pragma: no cover - real cloud failures are environment dependent.
            return {
                "provider": self.name,
                "status": "failed",
                "message": str(exc),
                "logs": [str(exc)],
                "generated_commands": generated_commands,
                "endpoints": [],
                "service_endpoints": [],
            }

    def delete(self, deployment_record: Dict[str, Any]) -> Dict[str, Any]:
        instance_id = deployment_record.get("instance_id")
        if not instance_id:
            deployment = deployment_record.get("deployment", {})
            instance_id = deployment.get("instance_id") if isinstance(deployment, dict) else None

        if not instance_id:
            return {
                "provider": self.name,
                "status": "delete_skipped",
                "instance_id": None,
                "message": "AWS cleanup skipped because the deployment record does not contain an instance ID.",
            }

        if not self.region:
            return {
                "provider": self.name,
                "status": "delete_failed",
                "instance_id": instance_id,
                "message": "AWS cleanup failed because AWS_REGION is not configured.",
            }

        try:
            ec2 = self._client()
            ec2.terminate_instances(InstanceIds=[instance_id])
            return {
                "provider": self.name,
                "status": "deleted",
                "instance_id": instance_id,
                "message": f"AWS EC2 termination requested for instance {instance_id}.",
            }
        except Exception as exc:  # pragma: no cover - real cloud failures are environment dependent.
            return {
                "provider": self.name,
                "status": "delete_failed",
                "instance_id": instance_id,
                "message": str(exc),
            }

    def health_check(self, result: Dict[str, Any]) -> Dict[str, Any]:
        endpoints = result.get("service_endpoints") or []
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

        deadline = time.time() + self.timeout_seconds
        last_error = None

        while time.time() < deadline:
            passed = True
            for url in urls:
                try:
                    response = requests.get(url, timeout=5)
                    if response.status_code >= 400:
                        passed = False
                        last_error = f"{url} returned HTTP {response.status_code}."
                        break
                except requests.RequestException as exc:
                    passed = False
                    last_error = str(exc)
                    break

            if passed:
                return {
                    "status": "passed",
                    "passed": True,
                    "message": "All public endpoints responded successfully.",
                }
            time.sleep(5)

        return {
            "status": "failed",
            "passed": False,
            "message": last_error or "Timed out waiting for public endpoints to respond.",
        }

    def _missing_config(self) -> List[str]:
        required = {
            "AWS_REGION": self.region,
            "AWS_AMI_ID": self.ami_id,
            "AWS_KEY_NAME": self.key_name,
            "AWS_SECURITY_GROUP_ID": self.security_group_id,
            "AWS_SUBNET_ID": self.subnet_id,
        }
        return [name for name, value in required.items() if not value]

    def _client(self) -> Any:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required for AWS deployment. Run pip install -r requirements.txt.") from exc
        return boto3.client("ec2", region_name=self.region)

    def _build_user_data(self, services: List[Dict[str, Any]]) -> str:
        lines = [
            "#!/bin/bash",
            "set -xe",
            "dnf update -y",
            "dnf install docker -y",
            "systemctl start docker",
            "systemctl enable docker",
            "sleep 25",
        ]

        for service in services:
            container_name = _safe_name(service["name"])
            image = shlex.quote(service["image"])
            port = int(service["port"])

            lines.extend(
                [
                    f"docker rm -f {container_name} || true",
                    f"docker pull {image}",
                    (
                        "docker run -d "
                        f"--name {container_name} "
                        f"-p {port}:{port} "
                        "--restart unless-stopped "
                        f"{image}"
                    ),
                ]
            )

        return "\n".join(lines) + "\n"


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9-]+", "-", value).strip("-").lower()
    return cleaned[:60] or "app"


def _service_endpoints(public_ip: str, services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not public_ip:
        return []

    endpoints = []
    for service in services:
        if not service.get("public"):
            continue
        port = int(service["port"])
        suffix = "" if port == 80 else f":{port}"
        endpoints.append(
            {
                "name": service["name"],
                "url": f"http://{public_ip}{suffix}",
                "port": port,
            }
        )
    return endpoints
