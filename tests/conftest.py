import pytest


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
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.app_context():
        app_module.db.session.remove()
        app_module.db.drop_all()
        app_module.db.create_all()
    yield
    with app_module.app.app_context():
        app_module.db.session.remove()
