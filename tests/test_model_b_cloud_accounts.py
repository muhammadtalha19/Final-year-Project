import json
import subprocess

import pytest
import yaml
from cryptography.fernet import Fernet

import app as app_module
import orchestrator
from config_schema import validate_config
from credential_vault import decrypt_credentials, encrypt_credentials, mask_secret
from models import CloudAccount, DeploymentRecord, User
from providers.aws_provider import AWSProvider
from providers.azure_mock import AzureMockProvider
from providers.gcp_mock import GCPMockProvider


VALID_YAML = """
app:
  name: model-b-app
  environment: production
selection:
  mode: manual
  provider: GCP
deployment:
  type: container
  image: dockertalha19/fyp-books-api:latest
  port: 8000
requirements:
  max_monthly_cost_usd: 20
  min_uptime_percent: 99.9
  preferred_region: asia
  public_access: true
"""


def register(client, email="modelb@example.com"):
    client.post("/register", data={"name": "Model B", "email": email, "password": "secret123"})


def aws_form(secret="aws-secret"):
    return {
        "display_name": "AWS Mine",
        "AWS_ACCESS_KEY_ID": "AKIATEST",
        "AWS_SECRET_ACCESS_KEY": secret,
        "AWS_REGION": "us-east-1",
        "AWS_AMI_ID": "ami-test",
        "AWS_INSTANCE_TYPE": "t3.micro",
        "AWS_KEY_NAME": "key",
        "AWS_SECURITY_GROUP_ID": "sg-test",
        "AWS_SUBNET_ID": "subnet-test",
    }


def azure_form(secret="azure-secret"):
    return {
        "display_name": "Azure Mine",
        "AZURE_TENANT_ID": "tenant",
        "AZURE_CLIENT_ID": "client",
        "AZURE_CLIENT_SECRET": secret,
        "AZURE_SUBSCRIPTION_ID": "subscription",
        "AZURE_RESOURCE_GROUP": "rg",
        "AZURE_LOCATION": "eastus",
        "AZURE_CONTAINERAPP_ENV": "env",
    }


def gcp_form(secret=None):
    return {
        "display_name": "GCP Mine",
        "GCP_PROJECT_ID": "project",
        "GCP_REGION": "asia-south1",
        "GCP_PLATFORM": "managed",
        "GCP_SERVICE_ACCOUNT_JSON": secret or '{"type":"service_account","private_key":"secret-key"}',
    }


def create_account(user_id, provider, credentials):
    account = CloudAccount(user_id=user_id, provider=provider, display_name=f"{provider} account")
    account.set_credentials(credentials)
    app_module.db.session.add(account)
    app_module.db.session.commit()
    return account


def test_encrypt_decrypt_round_trip_and_masking(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())

    encrypted = encrypt_credentials({"AWS_SECRET_ACCESS_KEY": "plain-secret", "AWS_REGION": "us-east-1"})

    assert "plain-secret" not in encrypted
    assert decrypt_credentials(encrypted)["AWS_SECRET_ACCESS_KEY"] == "plain-secret"
    assert mask_secret("abcdef") == "ab****ef"


def test_missing_key_blocks_saving_credentials(monkeypatch):
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    client = app_module.app.test_client()
    register(client)

    response = client.post("/cloud/aws/connect", data=aws_form())

    assert response.status_code == 400
    assert b"CREDENTIAL_ENCRYPTION_KEY" in response.data


def test_cloud_account_crud_and_secret_rendering(monkeypatch):
    client = app_module.app.test_client()
    assert client.get("/cloud/accounts").status_code == 302
    register(client)

    assert client.post("/cloud/aws/connect", data=aws_form()).status_code == 302
    assert client.post("/cloud/azure/connect", data=azure_form()).status_code == 302
    assert client.post("/cloud/gcp/connect", data=gcp_form()).status_code == 302

    response = client.get("/cloud/accounts")
    assert response.status_code == 200
    assert b"connected" in response.data
    assert b"aws-secret" not in response.data
    assert b"azure-secret" not in response.data
    assert b"secret-key" not in response.data

    with app_module.app.app_context():
        account = CloudAccount.query.filter_by(provider="AWS").first()
        assert "aws-secret" not in account.encrypted_credentials
        assert account.get_credentials()["AWS_SECRET_ACCESS_KEY"] == "aws-secret"
        account_id = account.id

    assert client.post(f"/cloud/accounts/{account_id}/delete").status_code == 302


def test_one_provider_account_per_user_updates_existing_account():
    client = app_module.app.test_client()
    register(client)

    client.post("/cloud/aws/connect", data=aws_form("first-secret"))
    client.post("/cloud/aws/connect", data=aws_form("second-secret"))

    with app_module.app.app_context():
        accounts = CloudAccount.query.filter_by(provider="AWS").all()
        assert len(accounts) == 1
        assert accounts[0].get_credentials()["AWS_SECRET_ACCESS_KEY"] == "second-secret"


def test_users_see_only_own_cloud_accounts_and_cannot_delete_others():
    client_a = app_module.app.test_client()
    register(client_a, "a@example.com")
    client_a.post("/cloud/aws/connect", data=aws_form())

    client_b = app_module.app.test_client()
    register(client_b, "b@example.com")
    client_b.post("/cloud/azure/connect", data=azure_form())

    with app_module.app.app_context():
        azure = CloudAccount.query.filter_by(provider="Azure").first()
        azure_id = azure.id

    response = client_a.get("/cloud/accounts")
    assert b"AWS Mine" in response.data
    assert b"Azure Mine" not in response.data
    assert client_a.post(f"/cloud/accounts/{azure_id}/delete").status_code == 404


def test_readiness_page_uses_user_account_and_hides_secrets(monkeypatch):
    monkeypatch.setenv("MODEL_B_USER_CLOUD_ACCOUNTS", "true")
    monkeypatch.setenv("ALLOW_ADMIN_CLOUD_FALLBACK", "false")
    client = app_module.app.test_client()
    register(client)

    not_connected = client.get("/providers")
    assert b"Cloud account not connected" in not_connected.data

    client.post("/cloud/aws/connect", data=aws_form())
    connected = client.get("/providers")
    assert b"AWS Mine" in connected.data
    assert b"aws-secret" not in connected.data
    assert b"AWS_ACCESS_KEY_ID is saved" in connected.data


def test_dry_run_allowed_without_connected_account(monkeypatch):
    monkeypatch.setenv("MODEL_B_USER_CLOUD_ACCOUNTS", "true")
    monkeypatch.setenv("ALLOW_ADMIN_CLOUD_FALLBACK", "false")
    monkeypatch.setenv("ENABLE_REAL_DEPLOYMENT", "false")
    client = app_module.app.test_client()
    register(client)

    response = client.post("/deploy/new", data={"yaml_content": VALID_YAML, "cloud_selection": "yaml"})

    assert response.status_code == 200
    assert b"Cloud account not connected" in response.data
    assert b"dry_run" in response.data


def test_real_deploy_blocked_when_selected_provider_not_connected(monkeypatch):
    monkeypatch.setenv("MODEL_B_USER_CLOUD_ACCOUNTS", "true")
    monkeypatch.setenv("ALLOW_ADMIN_CLOUD_FALLBACK", "false")
    monkeypatch.setenv("ENABLE_REAL_DEPLOYMENT", "true")
    monkeypatch.setenv("ALLOW_GCP_DEPLOYMENT", "true")
    monkeypatch.setattr(GCPMockProvider, "deploy", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no deploy")))
    client = app_module.app.test_client()
    register(client)

    response = client.post("/deploy/new", data={"yaml_content": VALID_YAML, "cloud_selection": "yaml"})

    assert response.status_code == 200
    assert b"cloud_account_required" in response.data


def test_real_provider_deploys_use_current_user_cloud_account(monkeypatch):
    monkeypatch.setenv("MODEL_B_USER_CLOUD_ACCOUNTS", "true")
    monkeypatch.setenv("ALLOW_ADMIN_CLOUD_FALLBACK", "false")
    monkeypatch.setenv("ENABLE_REAL_DEPLOYMENT", "true")
    monkeypatch.setenv("ALLOW_AWS_DEPLOYMENT", "true")
    monkeypatch.setenv("ALLOW_AZURE_DEPLOYMENT", "true")
    monkeypatch.setenv("ALLOW_GCP_DEPLOYMENT", "true")

    with app_module.app.app_context():
        user = User(name="Deploy", email="deploy@example.com", password_hash="hash")
        app_module.db.session.add(user)
        app_module.db.session.commit()
        create_account(user.id, "AWS", aws_form())
        create_account(user.id, "Azure", azure_form())
        create_account(user.id, "GCP", gcp_form())
        accounts = {account.provider: account for account in CloudAccount.query.filter_by(user_id=user.id).all()}

    captured = {}

    def fake_aws_deploy(self, config, cloud_account=None):
        captured["AWS"] = cloud_account.get_credentials()["AWS_SECRET_ACCESS_KEY"]
        return {"provider": "AWS", "status": "deployed", "generated_commands": [], "service_endpoints": []}

    def fake_azure_deploy(self, config, cloud_account=None):
        captured["Azure"] = cloud_account.get_credentials()["AZURE_CLIENT_SECRET"]
        return {"provider": "Azure", "status": "deployed", "generated_commands": [], "service_endpoints": []}

    def fake_gcp_deploy(self, config, cloud_account=None):
        captured["GCP"] = cloud_account.get_credentials()["GCP_SERVICE_ACCOUNT_JSON"]
        return {"provider": "GCP", "status": "deployed", "generated_commands": [], "service_endpoints": []}

    monkeypatch.setattr(AWSProvider, "_select_supported_subnet", lambda self, ec2: "subnet-test")
    monkeypatch.setattr(AWSProvider, "deploy", fake_aws_deploy)
    monkeypatch.setattr(AzureMockProvider, "deploy", fake_azure_deploy)
    monkeypatch.setattr(GCPMockProvider, "deploy", fake_gcp_deploy)

    for provider in ["AWS", "Azure", "GCP"]:
        config = yaml.safe_load(VALID_YAML)
        config["selection"] = {"mode": "manual", "provider": provider}
        result = orchestrator.deploy_app(
            config,
            confirm_real_deployment=True,
            cloud_accounts=accounts,
            require_cloud_account=True,
        )
        assert result["status"] == "deployed"

    assert captured["AWS"] == "aws-secret"
    assert captured["Azure"] == "azure-secret"
    assert "secret-key" in captured["GCP"]


def test_provider_subprocess_paths_accept_cloud_account(monkeypatch):
    calls = []

    class Completed:
        stdout = '{"status": {"url": "https://gcp.example"}}'
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    monkeypatch.setattr(subprocess, "run", fake_run)

    config = validate_config(yaml.safe_load(VALID_YAML))
    azure_result = AzureMockProvider().deploy(config, azure_form())
    gcp_result = GCPMockProvider().deploy(config, gcp_form())

    assert azure_result["status"] == "deployed"
    assert gcp_result["status"] == "deployed"
    assert all(isinstance(call[0], list) for call in calls)
    assert any("env" in call[1] for call in calls)


def test_cleanup_requires_and_uses_owner_cloud_account(monkeypatch):
    with app_module.app.app_context():
        user = User(name="Owner", email="owner@example.com", password_hash="hash")
        app_module.db.session.add(user)
        app_module.db.session.commit()
        account = create_account(user.id, "Azure", azure_form())
        record = DeploymentRecord(
            user_id=user.id,
            yaml_content=VALID_YAML,
            result_json={
                "app": "cleanup-app",
                "status": "deployed",
                "deployment_mode": "real",
                "decision": {"selected_provider": "Azure", "execution_provider": "Azure"},
                "deployment": {"status": "deployed", "app_names": ["cleanup-app"]},
                "health_check": {"result": "skipped"},
                "public_endpoints": [],
            },
        )
        record.apply_result(record.result_json, yaml_content=record.yaml_content)
        app_module.db.session.add(record)
        app_module.db.session.commit()
        cleanup_record = record.to_cleanup_record()
        account_id = account.id

    called = {}

    def fake_delete(self, record, cloud_account=None):
        called["secret"] = cloud_account.get_credentials()["AZURE_CLIENT_SECRET"]
        return {"provider": "Azure", "status": "deleted", "message": "deleted"}

    monkeypatch.setattr(AzureMockProvider, "delete", fake_delete)
    with app_module.app.app_context():
        account = app_module.db.session.get(CloudAccount, account_id)
        result = orchestrator.cleanup_deployment_record(cleanup_record, cloud_account=account, require_cloud_account=True)

    assert result["status"] == "deleted"
    assert called["secret"] == "azure-secret"
    blocked = orchestrator.cleanup_deployment_record(cleanup_record, cloud_account=None, require_cloud_account=True)
    assert blocked["status"] == "cloud_account_required"


def test_reports_and_templates_do_not_contain_saved_secrets():
    client = app_module.app.test_client()
    register(client)
    client.post("/cloud/aws/connect", data=aws_form())
    response = client.get("/templates")
    assert b"aws-secret" not in response.data

    with app_module.app.app_context():
        user = User.query.filter_by(email="modelb@example.com").first()
        record = DeploymentRecord(
            user_id=user.id,
            yaml_content=VALID_YAML,
            result_json={
                "app": "safe-report",
                "status": "dry_run",
                "deployment_mode": "dry_run",
                "decision": {"selected_provider": "AWS", "execution_provider": "AWS", "evaluated_providers": []},
                "deployment": {"status": "dry_run"},
                "cloud_account": {"provider": "AWS", "connected": True, "display_name": "AWS Mine"},
                "generated_commands": [],
                "public_endpoints": [],
                "health_check": {"result": "skipped"},
                "provider_readiness": {},
                "docker_image_validation": {},
                "diagnostics": {"provider_messages": ["safe"], "next_steps": [], "log_commands": []},
            },
        )
        record.apply_result(record.result_json, yaml_content=record.yaml_content)
        app_module.db.session.add(record)
        app_module.db.session.commit()
        record_id = record.id

    report = client.get(f"/deployment-report/{record_id}")
    assert b"aws-secret" not in report.data
    assert b"safe-report" in report.data
