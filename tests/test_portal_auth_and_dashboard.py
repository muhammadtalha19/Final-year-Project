from datetime import datetime, timedelta
from io import BytesIO

import auth as auth_module
import app as app_module
from models import DeploymentRecord, User, find_due_cleanups


VALID_YAML = """
app:
  name: portal-app
  environment: production
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


def fake_result(app_name="portal-app", status="dry_run", mode="dry_run", endpoint=None):
    endpoints = [{"name": app_name, "url": endpoint}] if endpoint else []
    return {
        "app": app_name,
        "app_type": "api",
        "image": "dockertalha19/fyp-books-api:latest",
        "environment": "production",
        "status": status,
        "deployment_mode": mode,
        "validation_errors": [],
        "warnings": [],
        "decision": {
            "selection_mode": "auto",
            "manual_provider": None,
            "recommended_provider": "GCP",
            "selected_provider": "GCP",
            "execution_provider": "GCP",
            "reason": "test",
            "evaluated_providers": [],
        },
        "provider_readiness": {"ready": True, "checks": [], "missing": [], "warnings": []},
        "docker_image_validation": {"valid": True, "errors": [], "warnings": [], "check_type": "syntax_only"},
        "bootstrap_plan": {},
        "approval": {"app_name": app_name} if status == "approval_required" else {},
        "diagnostics": {},
        "deployment": {"status": status, "message": "test"},
        "generated_commands": [],
        "public_endpoints": endpoints,
        "health_check": {"result": "skipped", "status": "skipped", "message": "test"},
    }


def register(client, email="user@example.com", password="secret123", name="User"):
    return client.post("/register", data={"name": name, "email": email, "password": password})


def login(client, email="user@example.com", password="secret123"):
    return client.post("/login", data={"email": email, "password": password})


def create_record(user_id, app_name="owned-app", status="dry_run", mode="dry_run", endpoint=None):
    record = DeploymentRecord(
        user_id=user_id,
        yaml_content=VALID_YAML,
        result_json=fake_result(app_name, status=status, mode=mode, endpoint=endpoint),
    )
    record.apply_result(record.result_json, yaml_content=record.yaml_content)
    app_module.db.session.add(record)
    app_module.db.session.commit()
    return record


def test_register_duplicate_login_failure_and_logout():
    client = app_module.app.test_client()

    assert register(client).status_code == 302
    client.get("/logout")
    duplicate = client.post(
        "/register",
        data={"name": "Second", "email": "user@example.com", "password": "secret123"},
    )
    assert duplicate.status_code == 400
    assert b"already exists" in duplicate.data

    client.get("/logout")
    bad_login = login(client, password="wrong")
    assert bad_login.status_code == 401
    assert b"Invalid email or password" in bad_login.data

    good_login = login(client)
    assert good_login.status_code == 302
    assert client.get("/logout").status_code == 302


def test_protected_routes_redirect_anonymous_user():
    client = app_module.app.test_client()

    for path in ["/dashboard", "/deploy/new", "/deployments", "/providers", "/settings", "/templates"]:
        response = client.get(path)
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


def test_oauth_buttons_render_unconfigured_message():
    response = app_module.app.test_client().get("/login")

    assert response.status_code == 200
    assert b"GitHub not configured" in response.data
    assert b"Google not configured" in response.data
    assert b"Microsoft not configured" in response.data


def test_oauth_callback_creates_user_without_storing_token(monkeypatch):
    class FakeClient:
        def authorize_access_token(self):
            return {"access_token": "secret-token"}

    monkeypatch.setenv("GITHUB_CLIENT_ID", "id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "secret")
    auth_module.oauth_clients["github"] = FakeClient()
    monkeypatch.setattr(
        auth_module,
        "fetch_oauth_profile",
        lambda provider, client, token: {
            "oauth_id": "gh-1",
            "name": "Git User",
            "email": "git@example.com",
            "email_verified": True,
            "avatar_url": "https://example.test/avatar.png",
        },
    )

    response = app_module.app.test_client().get("/auth/github/callback")

    assert response.status_code == 302
    with app_module.app.app_context():
        user = User.query.filter_by(email="git@example.com").first()
        assert user is not None
        assert user.auth_provider == "github"
        assert user.oauth_id == "gh-1"
        assert user.password_hash is None
        assert not hasattr(user, "access_token")


def test_google_and_microsoft_callbacks_create_users(monkeypatch):
    class FakeClient:
        def authorize_access_token(self):
            return {"access_token": "secret-token"}

    for provider, email in [("google", "google@example.com"), ("microsoft", "ms@example.com")]:
        monkeypatch.setenv(f"{provider.upper()}_CLIENT_ID", "id")
        monkeypatch.setenv(f"{provider.upper()}_CLIENT_SECRET", "secret")
        auth_module.oauth_clients[provider] = FakeClient()
        monkeypatch.setattr(
            auth_module,
            "fetch_oauth_profile",
            lambda provider_name, client, token, email=email: {
                "oauth_id": f"{provider}-1",
                "name": provider.title(),
                "email": email,
                "email_verified": True,
                "avatar_url": None,
            },
        )
        client = app_module.app.test_client()
        assert client.get(f"/auth/{provider}/callback").status_code == 302
        client.get("/logout")

    with app_module.app.app_context():
        assert User.query.filter_by(email="google@example.com").first() is not None
        assert User.query.filter_by(email="ms@example.com").first() is not None


def test_user_sees_only_own_deployments_and_cannot_access_other_records():
    client_a = app_module.app.test_client()
    register(client_a, "a@example.com", name="A")
    with app_module.app.app_context():
        user_a = User.query.filter_by(email="a@example.com").first()
        own = create_record(user_a.id, app_name="own-app")
        user_b = User(name="B", email="b@example.com", password_hash="hash")
        app_module.db.session.add(user_b)
        app_module.db.session.commit()
        other = create_record(user_b.id, app_name="other-app")
        own_id = own.id
        other_id = other.id

    response = client_a.get("/deployments")

    assert b"own-app" in response.data
    assert b"other-app" not in response.data
    assert client_a.get(f"/deployments/{other_id}").status_code == 404
    assert client_a.get(f"/deployment-report/{other_id}").status_code == 404
    assert client_a.post(f"/deployments/{other_id}/delete").status_code == 404
    assert client_a.post(f"/deployments/{other_id}/refresh").status_code == 404
    assert client_a.get(f"/deployments/{own_id}").status_code == 200


def test_dashboard_counts_only_current_user():
    client = app_module.app.test_client()
    register(client, "dash@example.com", name="Dash")
    with app_module.app.app_context():
        current = User.query.filter_by(email="dash@example.com").first()
        create_record(current.id, app_name="own-one")
        create_record(current.id, app_name="own-two", status="deployed", mode="real", endpoint="https://own.example")
        other = User(name="Other", email="other@example.com", password_hash="hash")
        app_module.db.session.add(other)
        app_module.db.session.commit()
        create_record(other.id, app_name="other-app")

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b'<span class="label">Total</span><strong>2</strong>' in response.data
    assert b"own-one" in response.data
    assert b"other-app" not in response.data


def test_settings_update_name_and_password_change():
    client = app_module.app.test_client()
    register(client, "settings@example.com", password="oldpass123", name="Old")

    response = client.post(
        "/settings",
        data={"action": "profile", "name": "New Name", "theme_preference": "dark"},
        follow_redirects=True,
    )
    assert b"Settings updated" in response.data

    wrong = client.post(
        "/settings",
        data={"action": "password", "current_password": "bad", "new_password": "newpass123"},
        follow_redirects=True,
    )
    assert b"Current password is incorrect" in wrong.data

    changed = client.post(
        "/settings",
        data={"action": "password", "current_password": "oldpass123", "new_password": "newpass123"},
        follow_redirects=True,
    )
    assert b"Password changed" in changed.data
    client.get("/logout")
    assert login(client, "settings@example.com", "newpass123").status_code == 302


def test_oauth_user_cannot_change_local_password():
    client = app_module.app.test_client()
    with app_module.app.app_context():
        user = User(name="OAuth", email="oauth@example.com", password_hash=None, auth_provider="github", oauth_id="1")
        app_module.db.session.add(user)
        app_module.db.session.commit()
        user_id = user.id
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True

    response = client.post(
        "/settings",
        data={"action": "password", "current_password": "x", "new_password": "newpass123"},
        follow_redirects=True,
    )

    assert b"Password managed by provider" in response.data


def test_templates_page_and_yaml_submission_paths(monkeypatch):
    captured = []
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: captured.append(config) or fake_result())
    client = app_module.app.test_client()
    assert client.get("/templates").status_code == 302
    register(client, "templates@example.com")

    templates_response = client.get("/templates")
    assert templates_response.status_code == 200
    assert b"ML API" in templates_response.data
    prefilled = client.get("/deploy/new?template=ml-api")
    assert b"fyp-ml-api" in prefilled.data

    textarea = client.post("/deploy/new", data={"yaml_content": VALID_YAML, "cloud_selection": "auto"})
    assert textarea.status_code == 200
    assert captured[-1]["selection"] == {"mode": "auto"}

    file_upload = client.post(
        "/deploy/new",
        data={"config_file": (BytesIO(VALID_YAML.encode("utf-8")), "app.yaml"), "cloud_selection": "yaml"},
        content_type="multipart/form-data",
    )
    assert file_upload.status_code == 200


def test_approval_required_is_stored_and_displayed(monkeypatch):
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: fake_result(status="approval_required", mode="real"))
    client = app_module.app.test_client()
    register(client, "approval@example.com")

    response = client.post("/deploy/new", data={"yaml_content": VALID_YAML, "cloud_selection": "yaml"})

    assert response.status_code == 200
    assert b"Confirm Real Deployment" in response.data
    with app_module.app.app_context():
        record = DeploymentRecord.query.filter_by(user_id=User.query.filter_by(email="approval@example.com").first().id).first()
        assert record.status == "approval_required"


def test_refresh_routes_are_owner_only_and_safe(monkeypatch):
    client = app_module.app.test_client()
    register(client, "refresh@example.com")
    with app_module.app.app_context():
        owner = User.query.filter_by(email="refresh@example.com").first()
        dry = create_record(owner.id, app_name="dry-refresh")
        real = create_record(owner.id, app_name="real-refresh", status="deployed", mode="real", endpoint="https://app.example")
        other_user = User(name="Other", email="refresh-other@example.com", password_hash="hash")
        app_module.db.session.add(other_user)
        app_module.db.session.commit()
        other = create_record(other_user.id, app_name="other-refresh", status="deployed", mode="real", endpoint="https://other.example")
        dry_id = dry.id
        real_id = real.id
        other_id = other.id

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(app_module.requests, "get", lambda url, timeout: FakeResponse())

    assert client.post(f"/deployments/{dry_id}/refresh", follow_redirects=True).status_code == 200
    assert client.post(f"/deployments/{other_id}/refresh").status_code == 404
    response = client.post(f"/deployments/{real_id}/refresh", follow_redirects=True)

    assert response.status_code == 200
    with app_module.app.app_context():
        refreshed = app_module.db.session.get(DeploymentRecord, real_id)
        assert refreshed.health_status == "passed"


def test_auto_cleanup_metadata_and_due_detection(monkeypatch):
    monkeypatch.setattr(app_module, "deploy_app", lambda config, **kwargs: fake_result())
    client = app_module.app.test_client()
    register(client, "cleanup@example.com")

    client.post(
        "/deploy/new",
        data={"yaml_content": VALID_YAML, "cloud_selection": "yaml", "auto_cleanup_after": "30m"},
    )
    with app_module.app.app_context():
        user = User.query.filter_by(email="cleanup@example.com").first()
        dry_record = DeploymentRecord.query.filter_by(user_id=user.id).first()
        assert dry_record.auto_cleanup_at is not None
        assert dry_record.cleanup_status == "not_required"
        real_record = create_record(user.id, app_name="due-real", status="deployed", mode="real", endpoint="https://due.example")
        real_record.auto_cleanup_at = datetime.utcnow() - timedelta(minutes=1)
        app_module.db.session.commit()
        due_ids = {record.id for record in find_due_cleanups()}
        assert real_record.id in due_ids
        dry_record_id = dry_record.id

    monkeypatch.setattr(app_module, "cleanup_deployment_record", lambda record: (_ for _ in ()).throw(AssertionError("no cleanup")))
    response = client.post(f"/deployments/{dry_record_id}/cleanup-if-due", follow_redirects=True)
    assert response.status_code == 200


def test_providers_page_masks_environment_values(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "super-secret-region-value")
    client = app_module.app.test_client()
    register(client, "providers@example.com")

    response = client.get("/providers")

    assert response.status_code == 200
    assert b"Deployments run in your connected cloud account" in response.data
    assert b"AWS" in response.data and b"Azure" in response.data and b"GCP" in response.data
    assert b"super-secret-region-value" not in response.data
