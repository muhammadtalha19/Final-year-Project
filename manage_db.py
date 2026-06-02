import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv():
        return None


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BACKUP_ROOT = PROJECT_ROOT / "_local_backups"
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


def resolve_sqlite_db_path(uri: Optional[str] = None, instance_path: Optional[str] = None) -> Optional[Path]:
    if not uri:
        return PROJECT_ROOT / "instance" / "orchestrator.db"

    url = make_url(uri)
    if not url.drivername.startswith("sqlite"):
        return None
    if not url.database or url.database == ":memory:":
        return None

    path = Path(url.database)
    if path.is_absolute():
        return path
    base = Path(instance_path) if instance_path else PROJECT_ROOT / "instance"
    return base / path


def create_backup(
    backup_root: Path = DEFAULT_BACKUP_ROOT,
    env_path: Path = PROJECT_ROOT / ".env",
    db_path: Optional[Path] = None,
    timestamp: Optional[str] = None,
) -> Path:
    timestamp = timestamp or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    if env_path.exists():
        shutil.copy2(env_path, backup_dir / ".env")
        copied.append(".env")

    resolved_db_path = db_path or _current_sqlite_db_path()
    if resolved_db_path and resolved_db_path.exists():
        shutil.copy2(resolved_db_path, backup_dir / resolved_db_path.name)
        copied.append("SQLite database")

    if copied:
        print(f"Backup created at {backup_dir}")
        print("Copied: " + ", ".join(copied))
    else:
        print(f"Backup folder created at {backup_dir}; no .env or SQLite database found.")
    return backup_dir


def upgrade_database(backup_first: bool = True) -> None:
    load_dotenv()
    if backup_first:
        create_backup()

    from app import app
    try:
        from flask_migrate import upgrade as migrate_upgrade
    except ModuleNotFoundError:
        with app.app_context():
            from database import db

            db.create_all()
        print("Flask-Migrate is not installed. Ran a non-destructive table creation fallback.")
        print("Install requirements.txt, then run: flask db upgrade")
        return

    with app.app_context():
        migrate_upgrade(directory=str(MIGRATIONS_DIR))
    print("Database upgrade complete. Existing users and cloud accounts were preserved.")


def database_status() -> dict:
    load_dotenv()
    try:
        from app import app

        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        instance_path = app.instance_path
    except Exception:
        uri = None
        instance_path = str(PROJECT_ROOT / "instance")

    db_path = resolve_sqlite_db_path(uri, instance_path)
    status = {
        "database_path": str(db_path) if db_path else "non-sqlite database",
        "database_exists": bool(db_path and db_path.exists()) if db_path else None,
        "migration_version": "",
        "tables": [],
    }

    if db_path and db_path.exists():
        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect() as connection:
            inspector = inspect(connection)
            status["tables"] = sorted(inspector.get_table_names())
            if "alembic_version" in status["tables"]:
                status["migration_version"] = connection.execute(text("select version_num from alembic_version")).scalar() or ""
    return status


def print_status() -> None:
    status = database_status()
    print(f"Database: {status['database_path']}")
    print(f"Exists: {status['database_exists']}")
    print(f"Migration version: {status['migration_version'] or 'not stamped'}")
    print(f"Tables: {len(status['tables'])}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Safe local database backup and migration helper.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("backup", help="Copy .env and the local SQLite database into _local_backups/.")
    subparsers.add_parser("upgrade", help="Back up local files, then run Flask-Migrate upgrade.")
    subparsers.add_parser("status", help="Show database and migration status without printing secrets.")
    args = parser.parse_args(argv)

    if args.command == "backup":
        create_backup()
        return 0
    if args.command == "upgrade":
        upgrade_database(backup_first=True)
        return 0
    if args.command == "status":
        print_status()
        return 0
    return 1


def _current_sqlite_db_path() -> Optional[Path]:
    try:
        from app import app

        return resolve_sqlite_db_path(app.config["SQLALCHEMY_DATABASE_URI"], app.instance_path)
    except Exception:
        return resolve_sqlite_db_path()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
