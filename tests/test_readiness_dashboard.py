import app as app_module
from models import CloudAccount, User


def _login(email="readiness@example.com"):
    client = app_module.app.test_client()
    client.post("/register", data={"name": "Ready", "email": email, "password": "secret123"})
    with app_module.app.app_context():
        user = User.query.filter_by(email=email).first()
        return client, user.id


def test_cloud_accounts_page_renders_connected_and_not_connected():
    client, user_id = _login()
    with app_module.app.app_context():
        account = CloudAccount(user_id=user_id, provider="AWS", display_name="AWS Ready")
        account.set_credentials(
            {
                "AWS_ACCESS_KEY_ID": "AKIA_TEST_ID",
                "AWS_SECRET_ACCESS_KEY": "secret-should-hide",
                "AWS_REGION": "us-east-1",
            }
        )
        app_module.db.session.add(account)
        app_module.db.session.commit()

    response = client.get("/cloud/accounts")

    assert response.status_code == 200
    assert b"AWS Ready" in response.data
    assert b"not connected" in response.data
    assert b"secret-should-hide" not in response.data
    assert b"AKIA_TEST_ID" not in response.data


def test_provider_readiness_page_does_not_expose_secrets():
    client, user_id = _login("providers-ready@example.com")
    with app_module.app.app_context():
        account = CloudAccount(user_id=user_id, provider="Azure", display_name="Azure Ready")
        account.set_credentials(
            {
                "AZURE_TENANT_ID": "tenant",
                "AZURE_CLIENT_ID": "client",
                "AZURE_CLIENT_SECRET": "azure-secret-should-hide",
                "AZURE_SUBSCRIPTION_ID": "subscription",
                "AZURE_RESOURCE_GROUP": "rg",
                "AZURE_LOCATION": "eastus",
                "AZURE_CONTAINERAPP_ENV": "env",
            }
        )
        app_module.db.session.add(account)
        app_module.db.session.commit()

    response = client.get("/providers")

    assert response.status_code == 200
    assert b"Readiness Score" in response.data
    assert b"Azure Ready" in response.data
    assert b"azure-secret-should-hide" not in response.data
    assert b"Deployments run in your connected cloud account" in response.data
