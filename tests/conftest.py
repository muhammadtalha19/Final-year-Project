import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def safe_test_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_LIVE_PRICING", "false")
    monkeypatch.setenv("ENABLE_IMAGE_REGISTRY_CHECK", "false")
    monkeypatch.setenv("ENABLE_REAL_DEPLOYMENT", "false")
    monkeypatch.setenv("ALLOW_HIGH_SCALE", "false")
    monkeypatch.setenv("ALLOW_AWS_DEPLOYMENT", "false")
    monkeypatch.setenv("ALLOW_GCP_DEPLOYMENT", "false")
    monkeypatch.setenv("ALLOW_AZURE_DEPLOYMENT", "false")
    monkeypatch.setenv("DEPLOYMENT_HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("MODEL_B_USER_CLOUD_ACCOUNTS", "false")
    monkeypatch.setenv("ALLOW_ADMIN_CLOUD_FALLBACK", "true")
    for name in [
        "GITHUB_CLIENT_ID",
        "GITHUB_CLIENT_SECRET",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "MICROSOFT_CLIENT_ID",
        "MICROSOFT_CLIENT_SECRET",
    ]:
        monkeypatch.delenv(name, raising=False)

    try:
        import app as app_module
        import auth as auth_module

        app_module.app.config["TESTING"] = True
        auth_module.oauth_clients.clear()
        with app_module.app.app_context():
            app_module.db.session.remove()
            app_module.db.drop_all()
            app_module.db.create_all()
        yield
        with app_module.app.app_context():
            app_module.db.session.remove()
    except ImportError:
        yield
