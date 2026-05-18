# YAML-Based Multi-Cloud Orchestrator

Final Year Project: YAML-Based Multi-Cloud Orchestrator for Automated Container Deployment Using Cost and Reliability Constraints.

## Project Overview

This project lets a non-DevOps user upload a YAML file that describes an application, container image, resource needs, cost limits, uptime requirements, region preference, and access requirements. The Flask dashboard validates the YAML, evaluates cloud providers, selects the most suitable provider, optionally deploys through an implemented backend, and returns status, endpoint, health-check output, logs/messages, and decision reasoning.

This project evaluates AWS, GCP, and Azure using a provider catalog. The current real execution backend supports AWS EC2 Docker deployment. GCP and Azure are included in the decision layer as mock providers to demonstrate multi-cloud extensibility.

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
```

Required for real AWS EC2 deployment: `AWS_REGION`, `AWS_AMI_ID`, `AWS_KEY_NAME`, `AWS_SECURITY_GROUP_ID`, and `AWS_SUBNET_ID`.

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

## AWS Deployment

AWS deployment uses `boto3` to launch an EC2 instance and passes Docker setup commands through EC2 user data. For multi-service YAML files, the AWS provider generates one `docker run` command per service. It returns the instance ID, public IP, public service endpoints, status, and a message.

The orchestrator never pretends that GCP or Azure deployment exists. If GCP or Azure is selected but AWS is also eligible, AWS may be used as the execution provider for the current backend. If AWS is not eligible, deployment stops before execution.

## Tests

```bash
pytest
```

The tests cover YAML validation, decision filtering, provider selection, and a no-real-cloud-deployment guard.

## Limitations

- Provider cost and uptime values are static catalog entries.
- Real deployment is implemented only for AWS EC2 Docker.
- GCP and Azure are mock providers for decision-layer extensibility.
- EC2 networking, security group rules, IAM permissions, and image availability must be configured manually.
- Health checks depend on the public endpoint becoming reachable within `DEPLOYMENT_TIMEOUT_SECONDS`.

## Future Work

- Add real GCP Cloud Run or Compute Engine deployment.
- Add real Azure Container Apps or VM deployment.
- Replace static provider data with live pricing and region availability.
- Add authentication for dashboard access.
- Add richer deployment logs and rollback handling.
- Store history in SQLite for stronger querying and reporting.
