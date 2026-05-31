from typing import Any, Dict, List


def generate_provider_bootstrap_plan(provider: str) -> Dict[str, Any]:
    normalized = _normalize_provider(provider)
    if normalized == "AWS":
        return _plan(
            "AWS",
            [
                "aws sts get-caller-identity",
                "aws ec2 describe-instance-type-offerings --location-type availability-zone",
                "aws ec2 describe-subnets --filters Name=default-for-az,Values=true",
                "aws ec2 describe-security-groups --group-names fyp-orchestrator",
                "aws ec2 authorize-security-group-ingress --protocol tcp --port 80 --cidr 0.0.0.0/0",
                "aws ec2 describe-images --owners amazon --filters Name=name,Values='al2023-ami-*'",
            ],
            [
                "AWS credentials",
                "supported availability zone/subnet",
                "security group with inbound TCP 80",
                "valid AMI",
                "key pair",
            ],
        )
    if normalized == "Azure":
        return _plan(
            "Azure",
            [
                "az provider register --namespace Microsoft.App",
                "az provider register --namespace Microsoft.OperationalInsights",
                "az group create --name <AZURE_RESOURCE_GROUP> --location <AZURE_LOCATION>",
                "az containerapp env create --name <AZURE_CONTAINERAPP_ENV> --resource-group <AZURE_RESOURCE_GROUP> --location <AZURE_LOCATION>",
            ],
            [
                "Azure login",
                "resource group",
                "Container Apps environment",
                "Microsoft.App provider registration",
            ],
        )
    if normalized == "GCP":
        return _plan(
            "GCP",
            [
                "gcloud config set project <GCP_PROJECT_ID>",
                "gcloud services enable run.googleapis.com",
                "gcloud run regions list",
            ],
            [
                "GCP project",
                "Cloud Run API enabled",
                "supported Cloud Run region",
            ],
        )

    return _plan(provider, [], ["supported provider name"])


def _plan(provider: str, commands: List[str], missing_resources: List[str]) -> Dict[str, Any]:
    return {
        "provider": provider,
        "status": "plan_only",
        "commands": commands,
        "missing_resources": missing_resources,
        "message": "Bootstrap suggestions only; no commands were executed.",
    }


def _normalize_provider(provider: str) -> str:
    providers = {
        "aws": "AWS",
        "azure": "Azure",
        "gcp": "GCP",
    }
    return providers.get(str(provider).strip().lower(), provider)
