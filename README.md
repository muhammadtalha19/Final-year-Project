# YAML-Based Multi-Cloud Deployment Orchestrator

Final year project at UAF. The idea is simple: you write one YAML file describing your app — the container image, resource requirements, cost limit, uptime needs, preferred region — and the system picks the best cloud provider (AWS, Azure, or GCP), explains why it picked it, and either generates the deployment commands or actually runs them.

The target audience is small teams or solo developers who don't want to dig through three different cloud consoles to figure out where to deploy a containerised app.

---

## What it does

You upload a YAML file through the Flask dashboard. The decision engine validates it, filters out providers that don't meet your cost or uptime constraints, scores the rest, and picks the winner. From there you can:

- Get a **dry-run plan** — the exact shell commands that *would* be run, without touching any cloud account
- Do a **real deployment** to your own AWS, Azure, or GCP account (behind safety flags, disabled by default)
- See a breakdown of why each provider was chosen or rejected
- Clean up deployed resources from the same dashboard

The portal has user accounts, OAuth login (GitHub, Google, Microsoft), per-user encrypted cloud credential storage, deployment history, an audit log, and a deployment wizard if you don't want to write YAML by hand.

---

## Project structure

```
app.py                 # Flask app factory, all routes
config.py              # Config classes (dev, testing, production)
config_schema.py       # Pydantic YAML validator
decision_engine.py     # Provider scoring and filtering logic
orchestrator.py        # Coordinates validation → decision → deployment
worker.py              # RQ background worker
models.py              # SQLAlchemy models (users, deployments, cloud accounts)
auth.py                # Email/password + OAuth flows
providers/
  aws_provider.py      # Real EC2 + Docker deployment
  azure_mock.py        # Azure Container Apps (real + dry-run)
  gcp_mock.py          # GCP Cloud Run (real + dry-run)
pricing/               # Azure live pricing + static fallbacks for AWS/GCP
tests/                 # 31 pytest files
examples/              # Sample YAML files to try
```

---

## Setup

You need Python 3.10+, and Redis running locally if you want background job support.

```bash
git clone https://github.com/muhammadtalha19/Final-year-Project.git
cd Final-year-Project

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-dev.txt  # only needed for running tests
```

Copy the example env file and fill it in:

```bash
cp .env.example .env
```

The two values you must set before the app will start:

```bash
# Generate SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Generate CREDENTIAL_ENCRYPTION_KEY (used to encrypt stored cloud credentials)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Paste both into your `.env`. Everything else has a sane default for local development.

Set up the database:

```bash
flask db upgrade
```

Run the app:

```bash
flask run --port 5001
```

Open `http://127.0.0.1:5001`, create an account, and try uploading one of the files from `examples/`.

If you want background job support (needed for queued real deployments), run the worker in a second terminal:

```bash
python worker.py
```

---

## Environment variables

The full list is in `.env.example`. The important ones:

| Variable | What it does |
|---|---|
| `SECRET_KEY` | Flask session secret |
| `CREDENTIAL_ENCRYPTION_KEY` | Fernet key for stored cloud credentials |
| `DATABASE_URL` | Defaults to SQLite locally; set to PostgreSQL for production |
| `REDIS_URL` | Defaults to `redis://localhost:6379/0` |
| `ENABLE_REAL_DEPLOYMENT` | Master switch for real deployments — `false` by default |
| `ALLOW_AWS_DEPLOYMENT` | Also needs to be `true` for AWS real deployment |
| `ALLOW_AZURE_DEPLOYMENT` | Same for Azure |
| `ALLOW_GCP_DEPLOYMENT` | Same for GCP |
| `ENABLE_LIVE_PRICING` | Fetch live Azure pricing from the Retail Prices API |

Real deployment is off by default. Dry-run mode works without any cloud credentials at all.

---

## YAML format

Single service:

```yaml
app:
  name: my-api
  environment: production
  type: api   # static-web | api | ml-api

deployment:
  type: container
  image: your-dockerhub-user/your-image:latest
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
  preferred_region: asia
  public_access: true

selection:
  mode: auto  # or manual with provider: AWS | Azure | GCP
```

Multi-service works too — see `examples/valid_multi_service.yaml`.

The `examples/` folder has YAML files for a few real apps (expense tracker, books API, ML API) with auto and manual provider selection, so you can see how the scoring changes.

---

## Connecting your cloud account

In the portal, go to **Cloud Accounts** to connect AWS, Azure, or GCP. Credentials are encrypted with Fernet before being stored — plaintext is never shown anywhere in the UI.

For real deployment you also need the matching CLI authenticated locally on wherever the worker runs:

```bash
# AWS
aws configure

# Azure
az login
az extension add --name containerapp --upgrade

# GCP
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com
```

Real deployment only runs when `ENABLE_REAL_DEPLOYMENT=true` **and** the provider-specific flag is also `true` **and** you explicitly confirm the approval step in the dashboard.

Always run cleanup from the dashboard after demos. EC2 instances and Container Apps aren't free.

---

## OAuth login (optional)

Create OAuth apps on GitHub, Google, and/or Microsoft and set the client IDs and secrets in `.env`. Callback URLs for local development:

```
http://127.0.0.1:5001/auth/github/callback
http://127.0.0.1:5001/auth/google/callback
http://127.0.0.1:5001/auth/microsoft/callback
```

If you don't configure OAuth, email/password login still works fine.

---

## Running tests

```bash
pytest -q
```

The test suite covers YAML validation, decision engine filtering and scoring, dry-run command generation for all three providers, auth flows, cloud account CRUD, approval gates, cleanup, billing quotas, queue reliability, and a few security checks. OAuth callbacks are mocked so tests run without real provider credentials.

---

## Database

The app uses Flask-Migrate for schema changes. Don't delete the database to handle schema updates:

```bash
python manage_db.py backup   # writes to _local_backups/<timestamp>/
flask db upgrade
```

The `CREDENTIAL_ENCRYPTION_KEY` must stay the same across restarts and migrations. If you lose or rotate it, previously saved cloud credentials become unreadable.

---

## Known limitations

- AWS and GCP pricing use static estimates, not live APIs. Azure has a basic live lookup when `ENABLE_LIVE_PRICING=true`.
- GCP and Azure real deployment run CLI subprocesses (`gcloud`, `az`), so those CLIs need to be installed on the same machine as the worker.
- There's no Docker Compose setup yet — the web server, worker, Redis, and database need to be started separately.
- Auto-cleanup is stored as metadata only; there's no background scheduler that runs it automatically.
- Production use would need HTTPS, proper secret management, and PostgreSQL instead of SQLite.

---

## Notes for the demo

1. Register or log in.
2. Go to **Cloud Accounts** and connect a provider, or skip it and use dry-run only.
3. Open **Demo Scenarios** and pick one, or go to **Deploy → New** and upload a file from `examples/`.
4. Run auto provider selection and check the "Why this provider?" section.
5. Generate a dry-run plan to see what would actually be deployed.
6. For a real deployment demo, make sure the safety flags are set and click through the approval step.
7. After any real deployment, use **Cleanup** and verify in the cloud console.
