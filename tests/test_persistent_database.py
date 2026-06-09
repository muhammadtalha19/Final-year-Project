from pathlib import Path

from sqlalchemy.exc import OperationalError
from werkzeug.security import generate_password_hash

import app as app_module
import manage_db
from models import User


def test_manage_db_upgrade_preserves_existing_users():
    with app_module.app.app_context():
        user = User(name="Persisted", email="persisted@example.com", password_hash=generate_password_hash("secret123"))
        app_module.db.session.add(user)
        app_module.db.session.commit()
        user_id = user.id

    manage_db.upgrade_database(backup_first=False)

    with app_module.app.app_context():
        preserved = app_module.db.session.get(User, user_id)
        assert preserved is not None
        assert preserved.email == "persisted@example.com"


def test_manage_db_backup_copies_env_and_db_without_printing_secrets(tmp_path, capsys):
    env_path = tmp_path / ".env"
    db_path = tmp_path / "orchestrator.db"
    backup_root = tmp_path / "_local_backups"
    env_path.write_text("SECRET_KEY=super-secret\nCREDENTIAL_ENCRYPTION_KEY=fernet-secret\n", encoding="utf-8")
    db_path.write_bytes(b"sqlite-data")

    backup_dir = manage_db.create_backup(
        backup_root=backup_root,
        env_path=env_path,
        db_path=db_path,
        timestamp="20260601_120000",
    )
    output = capsys.readouterr().out

    assert (backup_dir / ".env").exists()
    assert (backup_dir / "orchestrator.db").exists()
    assert "super-secret" not in output
    assert "fernet-secret" not in output


def test_outdated_schema_error_message_points_to_flask_db_upgrade():
    error = OperationalError("select users.role", {}, Exception("no such column: users.role"))

    message, status_code = app_module.handle_database_schema_error(error)

    assert status_code == 500
    assert "Database schema is outdated. Run: flask db upgrade" in message
    assert "delete" not in message.lower()


def test_gitignore_protects_local_database_backups_and_secret_files():
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    for pattern in [
        ".env",
        "*.db",
        "instance/*.db",
        "_local_backups/",
        "fyp_safe_backup/",
        "*.pem",
        "*.key",
        "*credentials*.json",
        "*service-account*.json",
    ]:
        assert pattern in gitignore
