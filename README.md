# ☁️ YAML-Based Multi-Cloud Deployment Orchestrator

> **Final Year Project** — Automated container deployment across AWS, Azure, and GCP driven by a single YAML file and a cost-aware decision engine.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.x-black?logo=flask)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-Academic-lightgrey)](#)
[![Tests](https://img.shields.io/badge/Tests-pytest-green?logo=pytest)](#running-tests)

---

## 📌 Table of Contents

1. [Overview](#-overview)
2. [Key Features](#-key-features)
3. [Architecture](#-architecture)
4. [Tech Stack](#-tech-stack)
5. [Prerequisites](#-prerequisites)
6. [Quick Start](#-quick-start)
7. [Environment Variables](#-environment-variables)
8. [Database Setup](#-database-setup)
9. [Running the App](#-running-the-app)
10. [YAML Schema Reference](#-yaml-schema-reference)
11. [Cloud Provider Setup](#-cloud-provider-setup)
12. [OAuth Login (Optional)](#-oauth-login-optional)
13. [Running Tests](#-running-tests)
14. [Portal Routes](#-portal-routes)
15. [Security Guide](#-security-guide)
16. [Limitations & Future Work](#-limitations--future-work)

---

## 🔭 Overview

Small teams and solo developers often struggle to pick the right cloud platform for a containerised app — comparing pricing, uptime SLAs, and regional availability across AWS, Azure, and GCP is time-consuming and error-prone.

This project solves that with a **YAML-driven orchestrator**:

- Describe your app, container image, resource needs, cost ceiling, and uptime requirement in a single YAML file.
- Upload it to the Flask dashboard.
- The **Decision Engine** validates the YAML, scores all three providers against your constraints, selects the best match, and either generates a dry-run deployment plan or executes real deployment — all with an explainable "Why this provider?" breakdown.

**Model B** (the current mode) is user-centric: every user connects their own AWS/Azure/GCP account. Real deployments and billing happen inside *their* cloud account, not a shared admin account.

---

## ✨ Key Features

| Feature | Description |
|---|---|
| 🧠 Decision Engine | Scores AWS, GCP, Azure against cost, uptime, region, and deployment support |
| 📄 YAML-First UX | Single/multi-service YAML schema; wizard builder for non-DevOps users |
| ☁️ Real Deployment | AWS EC2+Docker, Azure Container Apps, GCP Cloud Run — all behind safety flags |
| 🔒 Dry-Run Mode | Default safe mode — generates provider-specific shell commands without executing them |
| 💰 Dynamic Pricing | Azure Retail Prices API (optional); AWS/GCP use calibrated static fallbacks |
| 👤 User Cloud Accounts | Per-user Fernet-encrypted cloud credential storage (Model B) |
| 🔐 Auth | Email/password + optional GitHub, Google, Microsoft OAuth |
| 📊 Dashboard | Analytics, deployment history, provider scoring tables, audit log |
| 🧹 Cleanup | One-click teardown of real EC2/Container App/Cloud Run resources |
| ✅ Test Suite | 31 pytest files covering validation, decisions, pricing, auth, queue, cleanup |

---

## 🏗️ Architecture

```
User YAML / Wizard
        │
        ▼
Flask Dashboard (app.py)
  ├── Auth & Sessions (Flask-Login, SQLite)
  │
  ▼
YAML Validator (config_schema.py)
  │
  ▼
Decision Engine (decision_engine.py)
  ├── AWS  Provider  (providers/aws_provider.py)
  ├── Azure Provider (providers/azure_mock.py)
  └── GCP  Provider  (providers/gcp_mock.py)
  │
  ▼
Orchestrator (orchestrator.py)
  ├── Provider Readiness Check
  ├── Docker Image Validation
  ├── Approval Gate
  ├── Real / Dry-Run Deployment
  └── Health Check → Result
  │
  ▼
RQ Worker (worker.py) ← Redis Queue
  │
  ▼
Deployment History & Audit Log
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Web Framework | Flask 3, Flask-Login, Flask-Migrate, Flask-WTF, Flask-Limiter |
| Database | SQLite (dev) / PostgreSQL (prod) via SQLAlchemy + Alembic |
| Task Queue | Redis + RQ (python-rq) |
| Cloud SDKs | boto3 (AWS), Azure CLI (subprocess), gcloud CLI (subprocess) |
| Auth | Werkzeug hashing, Authlib (OAuth 2.0) |
| Encryption | cryptography (Fernet) for stored cloud credentials |
| Validation | Pydantic v2, PyYAML |
| Pricing | Azure Retail Prices REST API |
| Tests | pytest |
| Server | Gunicorn (production) |

---

## 📋 Prerequisites

- **Python 3.10+**
- **Redis** running locally on `localhost:6379` (for background jobs)
- *(Optional)* AWS CLI / Azure CLI / gcloud CLI for real deployments
- *(Optional)* Docker Hub account + public image for real deployments

---

## 🚀 Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/muhammadtalha19/Final-year-Project.git
cd Final-year-Project

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt   # for pytest

# 4. Configure environment
cp .env.example .env
# Open .env and fill in the required values (see Environment Variables below)

# 5. Generate required secret keys
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32))"
python -c "from cryptography.fernet import Fernet; print('CREDENTIAL_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
# Paste both values into your .env

# 6. Set up the database
flask db upgrade

# 7. Run the app
flask run --port 5001
```

Open **http://127.0.0.1:5001**, register an account, and try uploading one of the YAML files from the `examples/` folder.

---

## 🔧 Environment Variables

Copy `.env.example` to `.env` and fill in the values. **Never commit `.env`.**

### Required

| Variable | Description |
|---|---|
| `SECRET_KEY` | Flask session secret — generate with `secrets.token_urlsafe(32)` |
| `CREDENTIAL_ENCRYPTION_KEY` | Fernet key for encrypting stored cloud credentials |

### Database & Queue

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///orchestrator.db` | PostgreSQL URL for production |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `SENTRY_DSN` | *(empty)* | Optional Sentry error tracking |

### Deployment Safety Flags

All real deployment flags default to **`false`** (dry-run only).

| Variable | Default | Description |
|---|---|---|
| `ENABLE_REAL_DEPLOYMENT` | `false` | Master switch for real cloud deployment |
| `ALLOW_AWS_DEPLOYMENT` | `false` | Enable AWS EC2 real deployment |
| `ALLOW_AZURE_DEPLOYMENT` | `false` | Enable Azure Container Apps deployment |
| `ALLOW_GCP_DEPLOYMENT` | `false` | Enable GCP Cloud Run deployment |
| `AUTO_TERMINATE_ON_FAILURE` | `false` | Auto-cleanup on failed real deployment |
| `DEPLOYMENT_TIMEOUT_SECONDS` | `300` | Max wait for health-check after deploy |

### Usage Limits

| Variable | Default | Description |
|---|---|---|
| `MAX_ACTIVE_DEPLOYMENTS_PER_USER` | `3` | Concurrent active deployments per user |
| `MAX_REAL_DEPLOYMENTS_PER_DAY` | `5` | Real deployments per user per day |
| `MAX_MONTHLY_COST_LIMIT_USD` | `50` | Hard cost ceiling for orchestrator |

### Feature Flags

| Variable | Default | Description |
|---|---|---|
| `MODEL_B_USER_CLOUD_ACCOUNTS` | `true` | Enable per-user cloud accounts (Model B) |
| `ALLOW_ADMIN_CLOUD_FALLBACK` | `false` | Let server-level cloud env vars act as fallback |
| `ENABLE_LIVE_PRICING` | `false` | Fetch live Azure pricing (Azure Retail Prices API) |
| `ENABLE_IMAGE_REGISTRY_CHECK` | `false` | Preflight Docker Hub image existence check |
| `ALLOW_HIGH_SCALE` | `false` | Allow `max_instances > 1` in YAML |

### OAuth (Optional)

| Variable | Description |
|---|---|
| `OAUTH_REDIRECT_BASE_URL` | Base URL for OAuth callbacks (e.g. `http://127.0.0.1:5001`) |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub OAuth app credentials |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth app credentials |
| `MICROSOFT_CLIENT_ID` / `MICROSOFT_CLIENT_SECRET` | Microsoft Entra/Azure AD app credentials |

---

## 🗄️ Database Setup

The app uses **Flask-Migrate** (Alembic) for schema management.

```bash
# First-time setup
flask db upgrade

# After pulling schema changes
python manage_db.py backup    # creates _local_backups/<timestamp>/
flask db upgrade

# Check migration status
python manage_db.py status
```

> ⚠️ **Never delete the database** for schema changes — always migrate. The database stores registered users, encrypted cloud credentials, deployment history, and audit logs.

**Production:** set `DATABASE_URL` to a PostgreSQL connection string. `postgres://` URLs are automatically normalised to `postgresql://`.

---

## ▶️ Running the App

### Development

```bash
# Terminal 1 — Flask web server
flask run --port 5001

# Terminal 2 — RQ background worker (needed for queued deployments)
python worker.py
```

### Production (Gunicorn)

```bash
gunicorn -w 4 -b 0.0.0.0:8000 "app:create_app()"
```

> Docker Compose packaging is planned as future work.

---

## 📄 YAML Schema Reference

### Single-Service (most common)

```yaml
app:
  name: my-api
  environment: production
  type: api            # static-web | api | ml-api

deployment:
  type: container
  image: dockerhub-user/my-image:latest
  port: 8000
  replicas: 1

resources:
  cpu: 1
  memory: 512Mi
  min_instances: 0
  max_instances: 1

requirements:
  max_monthly_cost_usd: 20
  min_uptime_percent: 99.9
  preferred_region: asia   # asia | us | eu | any
  public_access: true

selection:
  mode: auto             # auto | manual
  # provider: AWS        # only for mode: manual  (AWS | Azure | GCP)
```

### Multi-Service

```yaml
app:
  name: ecommerce-platform
  environment: production

services:
  - name: api-service
    image: myrepo/api:latest
    port: 5000
    public: true
  - name: worker-service
    image: myrepo/worker:latest
    port: 5001
    public: false

requirements:
  max_monthly_cost_usd: 30
  min_uptime_percent: 99.9
  preferred_region: us
  public_access: true
```

More working examples are in the [`examples/`](examples/) directory.

---

## ☁️ Cloud Provider Setup

### AWS (EC2 + Docker)

1. Create an IAM user with `AmazonEC2FullAccess`.
2. Note: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`.
3. In the portal go to **Cloud Accounts → Connect AWS** and enter the credentials.
4. Optionally pre-configure CLI locally: `aws configure`

Required AWS resources (create once):
```bash
# Security group allowing ports 22 and 80
# Key pair (.pem) for SSH
# VPC/Subnet in your preferred region
```

### Azure (Container Apps)

1. Create a Service Principal: `az ad sp create-for-rbac --name fyp-sp --role Contributor`
2. Note the output (`appId`, `password`, `tenant`) and your Subscription ID.
3. In the portal go to **Cloud Accounts → Connect Azure**.

CLI setup:
```bash
az login
az extension add --name containerapp --upgrade
az group create --name fyp-rg --location eastus
az containerapp env create --name fyp-container-env --resource-group fyp-rg --location eastus
```

### GCP (Cloud Run)

1. Create a Service Account with `Cloud Run Admin` + `Storage Object Viewer`.
2. Download the JSON key.
3. In the portal go to **Cloud Accounts → Connect GCP** and paste the JSON.

CLI setup:
```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com
```

> 🧹 Always run **Cleanup** in the dashboard after demos to avoid unexpected charges.

---

## 🔐 OAuth Login (Optional)

Register OAuth apps with each provider, then set the client ID/secret in `.env`.

| Provider | Register at | Callback URL |
|---|---|---|
| GitHub | [github.com/settings/applications](https://github.com/settings/applications/new) | `http://127.0.0.1:5001/auth/github/callback` |
| Google | [console.cloud.google.com](https://console.cloud.google.com/) → Credentials | `http://127.0.0.1:5001/auth/google/callback` |
| Microsoft | [portal.azure.com](https://portal.azure.com/) → Entra ID → App Registrations | `http://127.0.0.1:5001/auth/microsoft/callback` |

OAuth is **optional** — email/password login works without any OAuth configuration.

---

## 🧪 Running Tests

```bash
# Run all tests (quiet)
pytest -q

# Run a specific test file
pytest tests/test_decision_engine.py -v

# Run with coverage
pip install pytest-cov
pytest --cov=. --cov-report=term-missing -q
```

The test suite (31 files) covers:
- YAML validation & schema edge cases
- Decision engine filtering and scoring
- Dry-run plan generation (AWS / Azure / GCP)
- Provider readiness & approval gate
- Docker image validation
- Auth flows (email + OAuth mocked callbacks)
- User-owned cloud accounts (Model B)
- Queue reliability and background jobs
- Cleanup / delete operations
- Billing quotas and rate limits
- Admin and audit log access control

---

## 🗺️ Portal Routes

| Route | Access | Description |
|---|---|---|
| `/` | Public | Landing page |
| `/register`, `/login`, `/logout` | Public | Auth |
| `/auth/github`, `/auth/google`, `/auth/microsoft` | Public | OAuth login |
| `/dashboard` | Auth | Analytics & latest deployments |
| `/deploy/new` | Auth | YAML upload / paste form |
| `/deploy/wizard` | Auth | Guided YAML builder |
| `/templates` | Auth | Built-in YAML templates |
| `/demo-scenarios` | Auth | Demo scenario launcher |
| `/deployments` | Auth | Deployment history |
| `/deployments/<id>` | Auth (owner) | Deployment detail & actions |
| `/deployment-report/<id>` | Auth (owner) | Plain-text deployment report |
| `/cloud/accounts` | Auth | Connect/manage cloud accounts |
| `/providers` | Auth | Provider readiness & bootstrap |
| `/audit` | Auth | Audit log |
| `/settings` | Auth | Profile, theme, password |
| `/admin`, `/admin/users`, `/admin/deployments` | Admin only | Admin overview |

---

## 🛡️ Security Guide

### What is protected
- `.env` is in `.gitignore` and must **never** be committed.
- User cloud credentials are **Fernet-encrypted** at rest; plaintext is never rendered in templates, reports, or logs.
- OAuth access tokens are **not stored** — only provider name, provider user ID, and profile metadata.
- CSRF protection is enabled by default (`Flask-WTF`).
- Rate limiting is enabled by default (`Flask-Limiter`).

### Rotate credentials immediately if
- You accidentally committed `.env`, pasted keys in a chat, or shared them in a screenshot.
- `CREDENTIAL_ENCRYPTION_KEY` is exposed (re-encrypt or ask users to reconnect accounts).
- Any AWS/Azure/GCP credentials were leaked.

### Production checklist
- [ ] Use PostgreSQL — not SQLite — for `DATABASE_URL`
- [ ] Set `FLASK_ENV=production`
- [ ] Use a platform secret manager (AWS Secrets Manager, Azure Key Vault, GCP Secret Manager) instead of `.env`
- [ ] Serve behind HTTPS with a reverse proxy (nginx / Caddy)
- [ ] Set `SESSION_COOKIE_SECURE=True` and `SESSION_COOKIE_HTTPONLY=True`
- [ ] Configure Sentry (`SENTRY_DSN`) for error tracking

---

## ⚠️ Limitations & Future Work

### Current Limitations

- AWS and GCP pricing use static fallback estimates (not live APIs).
- Azure live pricing is MVP-level — a single REST lookup, not a full billing estimate.
- Real deployment for GCP and Azure requires the respective CLI to be installed and authenticated on the server.
- Auto-cleanup is metadata-based; no background scheduler runs cleanup automatically.
- Docker/Gunicorn/Sentry containerisation was deferred and is not included in this release.
- Payment billing, team workspaces, Kubernetes support, and advanced monitoring are not implemented.

### Planned Future Work

- [ ] Live AWS Pricing API and GCP Pricing API integration
- [ ] Docker Compose + Gunicorn + Sentry production packaging
- [ ] Kubernetes deployment target (EKS / AKS / GKE)
- [ ] Replace raw credential forms with cloud OAuth / managed identity flows
- [ ] Team workspaces and role-based access control
- [ ] Advanced deployment monitoring, rollback, and SLA tracking
- [ ] Payment and subscription billing integration

---

## 👨‍💻 Author

**Muhammad Talha**  
Final Year Project — Computer Science  
University of Agriculture, Faisalabad (UAF)

---

## 📜 License

This project is submitted as an academic Final Year Project. All rights reserved by the author. Contact the author for reuse permissions.
