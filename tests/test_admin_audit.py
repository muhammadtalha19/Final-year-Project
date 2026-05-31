import app as app_module
from models import AuditLog, CloudAccount, User


def _register(client, email, name="User"):
    return client.post("/register", data={"name": name, "email": email, "password": "secret123"})


def _login(email):
    client = app_module.app.test_client()
    _register(client, email)
    with app_module.app.app_context():
        user = User.query.filter_by(email=email).first()
        return client, user.id


def _make_admin(user_id):
    with app_module.app.app_context():
        user = User.query.get(user_id)
        user.role = "admin"
        app_module.db.session.commit()


def test_normal_user_denied_admin_pages():
    client, _ = _login("normal-admin-denied@example.com")

    response = client.get("/admin")

    assert response.status_code == 403


def test_admin_can_access_admin_pages_and_no_secrets_rendered():
    client, admin_id = _login("admin@example.com",)
    _make_admin(admin_id)
    with app_module.app.app_context():
        user = User(name="Cloud User", email="cloud-user@example.com", password_hash="hash")
        app_module.db.session.add(user)
        app_module.db.session.commit()
        account = CloudAccount(user_id=user.id, provider="AWS", display_name="AWS SME")
        account.set_credentials(
            {
                "AWS_ACCESS_KEY_ID": "AKIA_TEST_VISIBLE_ID",
                "AWS_SECRET_ACCESS_KEY": "super-secret-value",
                "AWS_REGION": "us-east-1",
            }
        )
        app_module.db.session.add(account)
        app_module.db.session.commit()

    response = client.get("/admin/users")

    assert response.status_code == 200
    assert b"Cloud User" in response.data
    assert b"super-secret-value" not in response.data
    assert b"AKIA_TEST_VISIBLE_ID" not in response.data


def test_audit_event_created_for_registration():
    client = app_module.app.test_client()
    _register(client, "audit-register@example.com")

    with app_module.app.app_context():
        user = User.query.filter_by(email="audit-register@example.com").first()
        event = AuditLog.query.filter_by(user_id=user.id, action="user_registered").first()
        assert event is not None
        assert event.metadata_json == {}


def test_audit_metadata_redacts_secret_keys():
    with app_module.app.app_context():
        user = User(name="Audit", email="audit-secret@example.com", password_hash="hash")
        app_module.db.session.add(user)
        app_module.db.session.commit()
        app_module.record_audit_event(
            "cloud_account_connected",
            entity_type="cloud_account",
            provider="Azure",
            user_id=user.id,
            metadata={"AZURE_CLIENT_SECRET": "plain-secret", "nested": {"private_key": "-----BEGIN PRIVATE KEY-----abc"}},
        )
        event = AuditLog.query.filter_by(user_id=user.id, action="cloud_account_connected").first()
        assert event.metadata_json["AZURE_CLIENT_SECRET"] == "[redacted]"
        assert event.metadata_json["nested"]["private_key"] == "[redacted]"
        assert "plain-secret" not in str(event.metadata_json)


def test_user_sees_only_own_audit_logs():
    client, user_id = _login("own-audit@example.com")
    with app_module.app.app_context():
        other = User(name="Other", email="other-audit@example.com", password_hash="hash")
        app_module.db.session.add(other)
        app_module.db.session.commit()
        app_module.record_audit_event("deployment_dry_run", user_id=user_id, message="visible event")
        app_module.record_audit_event("deployment_dry_run", user_id=other.id, message="hidden event")

    response = client.get("/audit")

    assert response.status_code == 200
    assert b"visible event" in response.data
    assert b"hidden event" not in response.data
