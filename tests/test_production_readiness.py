import app as app_module


def test_production_readiness_requires_login():
    response = app_module.app.test_client().get("/production-readiness")

    assert response.status_code == 302


def test_production_readiness_renders_checklist_without_secrets():
    client = app_module.app.test_client()
    client.post("/register", data={"name": "Ready", "email": "prod-ready@example.com", "password": "secret123"})

    response = client.get("/production-readiness")

    assert response.status_code == 200
    assert b"Production Readiness Checklist" in response.data
    assert b"encrypted cloud credentials" in response.data
    assert b"user-owned cloud accounts" in response.data
    assert b"Production Future Work" in response.data
    assert b"SECRET_KEY=" not in response.data
    assert b"CREDENTIAL_ENCRYPTION_KEY=" not in response.data
