# YAML-Based Multi-Cloud Orchestrator

Final Year Project: YAML-Based Multi-Cloud Orchestrator for Automated Container Deployment Using Cost and Reliability Constraints.

## Project Overview

This project lets a non-DevOps user upload a YAML file that describes an application, container image, resource needs, cost limits, uptime requirements, region preference, and access requirements. The Flask dashboard validates the YAML, evaluates cloud providers, selects the most suitable provider, optionally deploys through an implemented backend, and returns status, endpoint, health-check output, logs/messages, and decision reasoning.

This project evaluates AWS, GCP, and Azure using a provider catalog. The current real execution backends support AWS EC2 Docker, Azure Container Apps, and GCP Cloud Run behind safety flags and an approval gate.

The portal now uses Model B: user-owned cloud accounts. Users register/login, connect their own AWS, Azure, or GCP account, and real deployments/cleanup run in that user's connected account. Dry-run mode still works without connected cloud accounts. Users own the deployed resources and any cloud billing.

## Security Warning

Never commit `.env`, AWS keys, Azure secrets, GCP service account JSON, OAuth secrets, Fernet keys, private keys, certificates, or runtime databases. If keys were committed, shared, or pasted into chat, rotate them immediately.

User cloud credentials are encrypted with `CREDENTIAL_ENCRYPTION_KEY`. If that key is exposed, rotate it before saving real credentials again. In production, use environment variables or a platform secret manager for all application secrets.

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
      +--> Auth, Sessions, Portal Pages (Flask-Login, SQLite)
      |
      v
YAML Validation (config_schema.py)
      |
      v
Decision Engine (decision_engine.py)
      |
      +--> AWS Provider (providers/aws_provider.py, real EC2 Docker backend)
      +--> GCP Provider (providers/gcp_mock.py, Cloud Run backend)
      +--> Azure Provider (providers/azure_mock.py, Container Apps backend)
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

## Production MVP Architecture

```text
user -> Flask portal -> database -> RQ queue -> worker -> selected cloud provider
                                      |                         |
                                      +-> reports/audit logs    +-> health check -> result
```

The production-MVP path keeps infrastructure hidden from SME users. Users interact with auth, cloud account connection, YAML upload, the deployment wizard, dry-run plans, approval, reports, cleanup, and audit logs. Cloud credentials are encrypted per user and are never shown back in the UI.

Phase 13 Docker/Gunicorn/Sentry packaging was intentionally skipped in this pass to conserve usage and avoid risky backend refactors. The app has Redis/RQ worker support, but Docker Compose files were not added in this phase.

## Supervisor Demo Flow

1. Register or log in.
2. Connect a user-owned cloud account from `/cloud/accounts`, or leave accounts disconnected for dry-run-only demo mode.
3. Open `/demo-scenarios` and choose Static Web App, Backend API, or ML API.
4. Use the template or `/deploy/wizard` to generate YAML.
5. Run auto provider selection and review "Why this provider?".
6. Generate a dry-run plan and show provider-specific commands without creating resources.
7. Review billing acknowledgement, quotas, approval gate, and provider readiness.
8. Open the deployment report and audit log.
9. For controlled real demos only, enable safety flags, confirm deployment, then use cleanup.

## SME Value

- Users do not need to learn AWS, Azure, or GCP consoles for the first deployment plan.
- One YAML/wizard interface works for static web apps, APIs, and small ML APIs.
- Provider choice is cost-aware, reliability-aware, and explainable.
- Model B user-owned accounts keep resources and billing under the SME user's cloud account.
- Dry-run, quotas, billing acknowledgement, approval, readiness checks, audit logs, and cleanup reduce accidental spending.
- Reports and timelines make the deployment process easier to review with a supervisor or SME stakeholder.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

The development SQLite database lives under `instance/orchestrator.db` by default. Create or update it with `flask db upgrade` before running the portal. You can also point `DATABASE_URL` at another SQLite file for local experiments.

Set `CREDENTIAL_ENCRYPTION_KEY` before saving user cloud accounts. Do not commit `.env`, OAuth client secrets, cloud credentials, `.pem`, logs, caches, database files, or virtual environments.

Generate an encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Database migrations use Flask-Migrate. For normal schema changes, migrate the database instead of deleting it:

```bash
python manage_db.py backup
flask db upgrade
```

The helper script also supports:

```bash
python manage_db.py status
python manage_db.py upgrade
```

`python manage_db.py upgrade` creates a local backup first, then runs the Flask-Migrate upgrade path.

## How to Preserve Users and Cloud Credentials

The SQLite database stores registered users, connected cloud accounts, encrypted cloud credentials, deployment records, reports, and audit logs. Do not delete the database for normal model/schema updates.

Before major code changes or migrations, back up the local database and `.env`:

```bash
python manage_db.py backup
```

After pulling or making schema changes, run:

```bash
flask db upgrade
```

or:

```bash
python manage_db.py upgrade
```

Keep the same `CREDENTIAL_ENCRYPTION_KEY` in `.env`. Changing or losing this key makes previously saved cloud credentials unreadable, because AWS/Azure/GCP credential payloads are encrypted with that key. If the key is exposed, rotate the key and reconnect cloud accounts before saving real credentials again.

If the app shows `Database schema is outdated. Run: flask db upgrade`, run the migration command above. Backups are written to `_local_backups/YYYYMMDD_HHMMSS/`, which is ignored by Git.

For production, set `DATABASE_URL` to PostgreSQL. `postgres://` URLs are normalized to `postgresql://`.

Run the worker separately when background jobs are enabled:

```bash
python worker.py
```

Docker Compose packaging is future work in this repository state because the Docker/Gunicorn/Sentry phase was skipped. A future compose setup should run separate `web`, `worker`, `redis`, and `postgres` services.

## Environment Variables

```text
FLASK_ENV=development
SECRET_KEY=
CREDENTIAL_ENCRYPTION_KEY=
DATABASE_URL=
REDIS_URL=redis://localhost:6379/0
SENTRY_DSN=
MODEL_B_USER_CLOUD_ACCOUNTS=true
ALLOW_ADMIN_CLOUD_FALLBACK=false
ENABLE_REAL_DEPLOYMENT=false
ALLOW_AWS_DEPLOYMENT=false
ALLOW_AZURE_DEPLOYMENT=false
ALLOW_GCP_DEPLOYMENT=false
AUTO_TERMINATE_ON_FAILURE=false
DEPLOYMENT_TIMEOUT_SECONDS=300
MAX_ACTIVE_DEPLOYMENTS_PER_USER=3
MAX_REAL_DEPLOYMENTS_PER_DAY=5
MAX_MONTHLY_COST_LIMIT_USD=50
ENABLE_LIVE_PRICING=false
ENABLE_IMAGE_REGISTRY_CHECK=false
ALLOW_HIGH_SCALE=false
OAUTH_REDIRECT_BASE_URL=http://127.0.0.1:5001
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
AWS_REGION=
AWS_AMI_ID=
AWS_INSTANCE_TYPE=t3.micro
AWS_KEY_NAME=
AWS_SECURITY_GROUP_ID=
AWS_SUBNET_ID=
GCP_PROJECT_ID=
GCP_REGION=asia-south1
GCP_PLATFORM=managed
AZURE_RESOURCE_GROUP=
AZURE_LOCATION=eastus
AZURE_CONTAINERAPP_ENV=
```

In Model B, users normally enter provider configuration in `/cloud/accounts`. Admin/server env cloud values are used only when `ALLOW_ADMIN_CLOUD_FALLBACK=true`.

AWS connect fields: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, optional `AWS_AMI_ID`, `AWS_INSTANCE_TYPE`, `AWS_KEY_NAME`, `AWS_SECURITY_GROUP_ID`, and `AWS_SUBNET_ID`.

Azure connect fields: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AZURE_LOCATION`, and `AZURE_CONTAINERAPP_ENV`.

GCP connect fields: `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_PLATFORM`, and `GCP_SERVICE_ACCOUNT_JSON`.

OAuth client IDs/secrets are optional. If a provider is not configured, its login button is shown as unavailable and the app still starts normally.

Local OAuth callback URLs:

```text
http://127.0.0.1:5001/auth/github/callback
http://127.0.0.1:5001/auth/google/callback
http://127.0.0.1:5001/auth/microsoft/callback
```

## Authenticated Portal

The Flask UI is organized as a small multi-page portal:

- `/` public landing page
- `/register`, `/login`, `/logout`
- `/auth/github`, `/auth/google`, `/auth/microsoft` and matching callback routes
- `/dashboard` user analytics and latest deployments
- `/deploy/new` YAML upload/paste form with provider selector
- `/deploy/wizard` guided YAML builder for static-web, api, and ml-api workloads
- `/templates` built-in YAML templates
- `/demo-scenarios` supervisor-friendly demo scenarios
- `/deployments` user-specific history
- `/deployments/<id>` deployment details
- `/deployment-report/<id>` plain text report
- `/providers` user cloud account readiness and bootstrap suggestions
- `/production-readiness` implemented/future production checklist
- `/audit` user-specific audit log
- `/admin`, `/admin/users`, `/admin/deployments` admin-only overview pages
- `/settings` profile, theme, and password settings

Email/password login uses Werkzeug password hashing. OAuth login uses Authlib and stores only provider name, provider user ID, profile metadata, and timestamps; OAuth access tokens are not stored. Users can see, refresh, report, and delete only their own deployment records.

## User-Owned Cloud Accounts

`/cloud/accounts` lets each authenticated user connect one AWS, Azure, and GCP account. Credentials are encrypted with Fernet before storage. Plaintext secrets are never rendered in templates, reports, diagnostics, or history records.

Real deployment requires:

- `ENABLE_REAL_DEPLOYMENT=true`
- the matching `ALLOW_*_DEPLOYMENT=true`
- a connected account for the selected provider
- provider readiness passed
- Docker image validation passed
- explicit deployment approval by POST

If auto mode selects a provider that is not connected, real deployment is blocked with `cloud_account_required`. The user can connect that provider or manually choose a provider they already connected. Dry-run plans remain available without any connected cloud account.

## OAuth Setup

Create OAuth applications in GitHub, Google, and Microsoft Entra ID/Azure Portal as needed, then set the matching variables in `.env`. Keep these values server-side only.

```text
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
```

Use `OAUTH_REDIRECT_BASE_URL=http://127.0.0.1:5001` when running locally on port `5001`, or set it to your deployed portal origin.

## Portal UX Features

The portal uses responsive, mobile-first templates with no external CSS framework. The dashboard cards, cloud account cards, deployment history, provider evaluation tables, generated commands, YAML blocks, diagnostics, and reports adapt for desktop, laptop, tablet, and mobile screens.

Dark mode is controlled with CSS variables and a navbar toggle. The preference is saved in browser `localStorage`; authenticated users can also save `system`, `light`, or `dark` in `/settings`.

The template library provides starter YAML for static web apps, FastAPI APIs, ML APIs, manual AWS, manual Azure, manual GCP, and auto provider selection. `/deploy/new` supports file upload or pasted YAML; if both are provided, the textarea YAML is used.

Deployment analytics are calculated per user and include totals, dry-runs, real deployments, deployed/failed/deleted counts, provider breakdown, app type breakdown, and the latest five records.

Status refresh is available for owned real deployment records. Dry-run, failed, and deleted records refresh safely without cloud API calls. Auto-cleanup metadata can store a future cleanup time, but no background worker is implemented.

## YAML Schema Examples

Single-service:

```yaml
app:
  name: img2pdf-web
  environment: production
  type: api

deployment:
  type: container
  image: dockertalha19/img2pdf
  port: 80
  replicas: 1

resources:
  cpu: 1
  memory: 512Mi
  min_instances: 0
  max_instances: 1

requirements:
  max_monthly_cost_usd: 20
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
```

Supported `app.type` values are `static-web`, `api`, and `ml-api`. If omitted, the orchestrator defaults to `api` for backwards compatibility. Resource fields are optional; `max_instances` is capped at `1` unless `ALLOW_HIGH_SCALE=true`.

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

Real deployment is still controlled by `.env` safety flags such as `ENABLE_REAL_DEPLOYMENT` and `ALLOW_AWS_DEPLOYMENT`; the UI dropdown does not enable real cloud execution.

## Running Locally

```bash
flask run
```

Open the Flask URL, create an account, upload one of the files in `examples/`, and review the selected provider, execution provider, scoring table, deployment status, endpoint, health-check result, diagnostics, and report.

Common commands:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
pytest -q
flask db upgrade
flask run --port 5001
python worker.py
```

Docker Compose command placeholder for future packaging:

```bash
# Future Phase 13 work, not included in this pass:
# docker compose up --build
```

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

To attempt real deployment, `ENABLE_REAL_DEPLOYMENT=true` must be set and the selected provider must also have its allow flag enabled, such as `ALLOW_AWS_DEPLOYMENT=true`, `ALLOW_AZURE_DEPLOYMENT=true`, or `ALLOW_GCP_DEPLOYMENT=true`.

## Real Provider Status

Real deployment is disabled by default and should only be enabled in a controlled demo account:

```text
ENABLE_REAL_DEPLOYMENT=true
ALLOW_AWS_DEPLOYMENT=true
# or
ALLOW_AZURE_DEPLOYMENT=true
# or
ALLOW_GCP_DEPLOYMENT=true
```

AWS real deployment uses EC2 plus Docker. The provider launches an EC2 instance with `boto3`, installs Docker through user data, pulls the configured image, and runs the container. Public apps map host port `80` to the YAML container port, so APIs and ML APIs on port `8000` are reachable through `http://PUBLIC_IP`. The AWS provider also checks instance type availability by subnet/AZ before launch and can fall back to a supported default VPC subnet.

Azure real deployment uses Azure Container Apps through the Azure CLI. The provider runs `az containerapp create` with an argument list and captures the returned FQDN.

GCP real deployment uses Cloud Run through the `gcloud` CLI. The provider runs `gcloud run deploy`, parses JSON output, and captures `status.url`.

Before using real execution, configure the provider CLI/account locally:

```bash
aws configure
az login
az extension add --name containerapp --upgrade
gcloud auth login
gcloud config set project <GCP_PROJECT_ID>
gcloud services enable run.googleapis.com
```

Monitor free-tier usage and billing carefully, and clean up EC2 instances, Container Apps, resource groups, and related networking resources after demos.

## Provider Readiness and Deployment Approval

Dry-run remains the default and does not require approval. When real deployment is enabled, the orchestrator checks the current user's connected account, checks provider readiness, validates the Docker image string, and then asks for explicit confirmation before calling a real provider deployment method.

Readiness checks catch missing cloud setup such as AWS EC2 variables, Azure Container Apps variables, and GCP Cloud Run variables. Docker image validation catches empty images and placeholder values such as `YOUR_DOCKERHUB_USERNAME`; images without tags are shown as warnings.

Real deployment proceeds only when `.env` safety flags are enabled, the selected provider is connected and ready, the Docker image validation passes, and the user confirms the approval step in the dashboard. Use cleanup after real deployments, then verify the AWS, Azure, or GCP console to confirm resources were removed.

Optional Docker Hub image existence checks are disabled by default:

```text
ENABLE_IMAGE_REGISTRY_CHECK=false
```

When enabled, the registry check is still only a best-effort preflight check. It is not a billing or deployment guarantee.

## Provider Bootstrap Plan

When readiness fails, the dashboard shows a bootstrap suggestion plan. These commands are informational and are not executed by the orchestrator. AWS suggestions include credential checks, supported AZ/subnet discovery, security group port `80`, AMI lookup, and key pair status. Azure suggestions include provider registration, resource group creation, and Container Apps environment setup. GCP suggestions include project selection, Cloud Run API enablement, and region verification.

## Cleanup/Delete

Cleanup is available only for the owner of stored real AWS, Azure, or GCP deployments and uses that owner's connected cloud account. AWS cleanup terminates the recorded EC2 instance. Azure cleanup deletes the recorded Container App through the Azure CLI. GCP cleanup deletes the recorded Cloud Run service. Dry-run records do not create cloud resources and do not need deletion.

After using cleanup, verify the result in the AWS, Azure, or GCP console and confirm that associated billable resources no longer remain.

## AWS Deployment

AWS deployment uses `boto3` to launch an EC2 instance and passes Docker setup commands through EC2 user data. For multi-service YAML files, the AWS provider generates one `docker run` command per service. It returns the instance ID, public IP, public service endpoints, status, and a message.

The orchestrator never falls back to AWS when Azure or GCP is selected. In dry-run mode it generates the selected provider's plan. In real mode it executes only the selected provider when the matching allow flag is true.

## ML Demo App

`demo_apps/fyp-ml-api/` contains a lightweight FastAPI ML-style API with deterministic inference logic, no heavy ML dependencies, and routes for `/`, `/health`, `/predict`, and `/docs`. It listens on port `8000`. Example YAML files are available under `examples/fyp_ml_api_*.yaml` and reference:

```text
dockertalha19/fyp-ml-api:latest
```

The repository does not build or push this image automatically.

## Tests

```bash
pytest -q
```

The tests cover YAML validation, decision filtering, pricing fallback behavior, provider selection, dry-run command generation, readiness checks, approval gates, cleanup, diagnostics/reporting, auth, OAuth mocked callbacks, owner-only records, settings, templates, refresh, auto-cleanup metadata, and no-real-cloud-deployment guards.

## Limitations

- AWS and GCP pricing currently use static fallback estimates.
- Azure live pricing is an MVP estimate and may not match exact deployment cost.
- Real deployment is implemented for AWS EC2 Docker, Azure Container Apps, and GCP Cloud Run, but all real execution remains disabled by default.
- Dry-run commands are generated for demonstration and review; they are not executed by the dashboard.
- EC2 networking, security group rules, IAM permissions, and image availability must be configured manually.
- Health checks depend on the public endpoint becoming reachable within `DEPLOYMENT_TIMEOUT_SECONDS`.
- OAuth providers require external configuration in the provider dashboards; local tests use mocks only.
- Auto-cleanup is metadata/helper based and does not run a background worker.
- Model B currently stores encrypted provider credentials directly; production systems should prefer cloud OAuth, short-lived tokens, or role-based access.
- Docker/Gunicorn/Sentry packaging was skipped in this pass and should be added before wider production use.
- Payment/subscription billing, team workspaces, advanced monitoring, managed secrets, and SLA/error-budget tracking are not implemented.

## Future Work

- Add richer deployment backends such as GCP Compute Engine, Azure VM, or Kubernetes.
- Replace static provider data with live pricing and region availability.
- Add richer deployment logs and rollback handling.
- Add production packaging with Docker, Gunicorn, Sentry, security headers, and managed deployment infrastructure.
- Replace raw cloud credential forms with cloud OAuth, role assumption, short-lived credentials, or managed identity flows.
- Add payment/subscription billing, team workspaces, advanced monitoring, SLA/error budgets, and Kubernetes support.
