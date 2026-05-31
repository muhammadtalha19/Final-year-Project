# YAML-Based Multi-Cloud Orchestrator

Final Year Project: YAML-Based Multi-Cloud Orchestrator for Automated Container Deployment Using Cost and Reliability Constraints.

## Project Overview

This project lets a non-DevOps user upload a YAML file that describes an application, container image, resource needs, cost limits, uptime requirements, region preference, and access requirements. The Flask dashboard validates the YAML, evaluates cloud providers, selects the most suitable provider, optionally deploys through an implemented backend, and returns status, endpoint, health-check output, logs/messages, and decision reasoning.

This project evaluates AWS, GCP, and Azure using a provider catalog. The current real execution backends support AWS EC2 Docker deployment and Azure Container Apps deployment behind safety flags. GCP remains dry-run only for now.

## Problem Statement

Small teams and non-DevOps users often struggle to decide where to deploy containerized applications while balancing cost and reliability. Manual provider comparison and infrastructure setup can be error-prone. This project explores whether a YAML-driven orchestrator can simplify deployment decisions and automate the first execution path.

## Hypothesis

A structured YAML input combined with rule-based provider filtering and scoring can make cloud selection understandable, repeatable, and extensible while preserving a safe deployment workflow.

## Architecture

```text
User YAML Upload
      |
      v
Flask Dashboard (app.py)
      |
      v
YAML Validation (config_schema.py)
      |
      v
Decision Engine (decision_engine.py)
      |
      +--> AWS Provider (providers/aws_provider.py, real EC2 Docker backend)
      +--> GCP Mock (providers/gcp_mock.py, decision only)
      +--> Azure Mock (providers/azure_mock.py, decision only)
      |
      v
Orchestrator (orchestrator.py)
      |
      +--> Health Check
      +--> Deployment History (deployment_history.py)
      |
      v
Dashboard Result
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in AWS values in `.env` only when you intend to run the real AWS backend. Do not commit `.env`, `.pem`, logs, caches, or virtual environments.

## Environment Variables

```text
FLASK_ENV=development
AWS_REGION=
AWS_AMI_ID=
AWS_INSTANCE_TYPE=t3.micro
AWS_KEY_NAME=
AWS_SECURITY_GROUP_ID=
AWS_SUBNET_ID=
DEPLOYMENT_TIMEOUT_SECONDS=180
ENABLE_LIVE_PRICING=false
ENABLE_REAL_DEPLOYMENT=false
ALLOW_AWS_DEPLOYMENT=false
ALLOW_AZURE_DEPLOYMENT=false
ALLOW_GCP_DEPLOYMENT=false
GCP_PROJECT_ID=
GCP_REGION=asia-south1
GCP_PLATFORM=managed
AZURE_RESOURCE_GROUP=
AZURE_LOCATION=eastus
AZURE_CONTAINERAPP_ENV=
```

Required for real AWS EC2 deployment: `AWS_REGION`, `AWS_AMI_ID`, `AWS_KEY_NAME`, `AWS_SECURITY_GROUP_ID`, and `AWS_SUBNET_ID`.

Required for real Azure Container Apps deployment: `AZURE_RESOURCE_GROUP`, `AZURE_LOCATION`, and `AZURE_CONTAINERAPP_ENV`.

## YAML Schema Examples

Single-service:

```yaml
app:
  name: img2pdf-web
  environment: production

deployment:
  type: container
  image: dockertalha19/img2pdf
  port: 80
  replicas: 1

resources:
  cpu: 1
  memory: 512Mi

requirements:
  max_monthly_cost_usd: 20
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
```

Multi-service:

```yaml
app:
  name: ecommerce-platform
  environment: production

services:
  - name: login-service
    image: myrepo/login
    port: 5000
    public: true
  - name: order-service
    image: myrepo/orders
    port: 5001
    public: false

requirements:
  max_monthly_cost_usd: 30
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
```

## Cloud Selection Modes

By default, YAML files use auto mode, where the system evaluates AWS, GCP, and Azure and selects the highest-scoring eligible provider:

```yaml
selection:
  mode: auto
```

Manual mode lets the user request a specific provider:

```yaml
selection:
  mode: manual
  provider: AWS
```

Manual provider values must be `AWS`, `GCP`, or `Azure`. Manual selection does not bypass safety checks: the selected provider is still validated against cost, uptime, preferred region, and deployment support. If the manual provider is blocked, the orchestrator stops before generating a deployment plan and shows a recommended eligible provider when one exists.

## Frontend Cloud Selection

The deployment form includes a cloud provider dropdown. `Use YAML selection` leaves the uploaded YAML unchanged. Choosing `Auto select best provider`, `AWS`, `Azure`, or `GCP` writes the matching `selection` block before validation, so the UI choice overrides YAML only when a non-YAML option is selected.

Real deployment is still controlled only by `.env` safety flags such as `ENABLE_REAL_DEPLOYMENT` and `ALLOW_AWS_DEPLOYMENT`; the UI dropdown does not enable real cloud execution.

## Running Locally

```bash
flask run
```

Open the Flask URL, upload one of the files in `examples/`, and review the selected provider, execution provider, scoring table, deployment status, endpoint, and health-check result.

## Decision Engine

The decision engine first applies hard filters:

- provider cost must be less than or equal to `max_monthly_cost_usd`
- provider uptime must be greater than or equal to `min_uptime_percent`
- provider must support container deployment
- provider must support `preferred_region` when specified

Eligible providers are scored using lower cost, higher uptime, preferred region match, and a small execution-backend bonus. The execution bonus is intentionally small so a better logical cloud selection is not hidden by AWS-only execution support.

## Dynamic Pricing MVP

The decision engine now reads provider cost estimates from the pricing layer. By default, `ENABLE_LIVE_PRICING=false`, so AWS, GCP, and Azure use static fallback estimates.

Azure Retail Prices API lookup can be enabled with:

```text
ENABLE_LIVE_PRICING=true
```

For this MVP, Azure live pricing is approximate and currently uses a simple Azure Retail Prices API lookup. AWS and GCP still use fallback pricing; AWS Pricing API and GCP Pricing API are not implemented yet. These estimates are not exact bills, and the final cloud bill may differ because of region, usage duration, networking, storage, discounts, free tiers, taxes, and provider-specific charges.

## Multi-cloud Dry Run Mode

Real deployment is disabled by default:

```text
ENABLE_REAL_DEPLOYMENT=false
```

In dry-run mode, the orchestrator uses the selected provider directly and generates a safe provider-specific deployment plan without executing cloud commands. AWS shows an EC2 Docker plan, GCP shows a Cloud Run `gcloud run deploy` command, and Azure shows an Azure Container Apps `az containerapp create` command. No EC2 instance is launched, and no `gcloud` or `az` command is executed.

To attempt real deployment, `ENABLE_REAL_DEPLOYMENT=true` must be set and the selected provider must also have its allow flag enabled, such as `ALLOW_AWS_DEPLOYMENT=true` or `ALLOW_AZURE_DEPLOYMENT=true`. GCP real execution is still not implemented; it remains dry-run or blocked.

## Real AWS and Azure Deployment

Real deployment is disabled by default and should only be enabled in a controlled demo account:

```text
ENABLE_REAL_DEPLOYMENT=true
ALLOW_AWS_DEPLOYMENT=true
# or
ALLOW_AZURE_DEPLOYMENT=true
```

AWS real deployment uses EC2 plus Docker. The provider launches an EC2 instance with `boto3`, installs Docker through user data, pulls the configured image, and runs the container with `PORT:PORT` mapping.

Azure real deployment uses Azure Container Apps through the Azure CLI. The provider runs `az containerapp create` with an argument list and captures the returned FQDN.

GCP remains dry-run only for now; no real `gcloud` deployment is performed.

Before using real execution, configure the provider CLI/account locally:

```bash
aws configure
az login
az extension add --name containerapp --upgrade
```

Monitor free-tier usage and billing carefully, and clean up EC2 instances, Container Apps, resource groups, and related networking resources after demos.

## Provider Readiness and Deployment Approval

Dry-run remains the default and does not require approval. When real deployment is enabled, the orchestrator first checks provider readiness, validates the Docker image string, and then asks for explicit confirmation before calling a real provider deployment method.

Readiness checks catch missing cloud setup such as AWS EC2 variables, Azure Container Apps variables, and the fact that GCP real deployment is not implemented yet. Docker image validation catches empty images and placeholder values such as `YOUR_DOCKERHUB_USERNAME`; images without tags are shown as warnings.

Real deployment proceeds only when `.env` safety flags are enabled, the selected provider is ready, the Docker image validation passes, and the user confirms the approval step in the dashboard. Use cleanup after real deployments, then verify the AWS or Azure console to confirm resources were removed.

## Cleanup/Delete

Cleanup is available only for stored real AWS or Azure deployments. AWS cleanup terminates the recorded EC2 instance. Azure cleanup deletes the recorded Container App through the Azure CLI. Dry-run records do not create cloud resources and do not need deletion; GCP cleanup is not implemented because GCP remains dry-run only.

After using cleanup, verify the result in the AWS or Azure console and confirm that associated billable resources no longer remain.

## AWS Deployment

AWS deployment uses `boto3` to launch an EC2 instance and passes Docker setup commands through EC2 user data. For multi-service YAML files, the AWS provider generates one `docker run` command per service. It returns the instance ID, public IP, public service endpoints, status, and a message.

The orchestrator never falls back to AWS when Azure or GCP is selected. In dry-run mode it generates the selected provider's plan. In real mode it executes only the selected provider when the matching allow flag is true.

## Tests

```bash
pytest
```

The tests cover YAML validation, decision filtering, pricing fallback behavior, provider selection, dry-run command generation, and a no-real-cloud-deployment guard.

## Limitations

- AWS and GCP pricing currently use static fallback estimates.
- Azure live pricing is an MVP estimate and may not match exact deployment cost.
- Real deployment is implemented for AWS EC2 Docker and Azure Container Apps only.
- GCP remains dry-run only.
- Dry-run commands are generated for demonstration and review; they are not executed by the dashboard.
- EC2 networking, security group rules, IAM permissions, and image availability must be configured manually.
- Health checks depend on the public endpoint becoming reachable within `DEPLOYMENT_TIMEOUT_SECONDS`.

## Future Work

- Add real GCP Cloud Run or Compute Engine deployment.
- Add real Azure Container Apps or VM deployment.
- Replace static provider data with live pricing and region availability.
- Add authentication for dashboard access.
- Add richer deployment logs and rollback handling.
- Store history in SQLite for stronger querying and reporting.
