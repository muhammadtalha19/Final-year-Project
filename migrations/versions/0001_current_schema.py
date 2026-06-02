"""baseline current portal schema

Revision ID: 0001_current_schema
Revises:
Create Date: 2026-06-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_current_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=True),
            sa.Column("auth_provider", sa.String(length=40), nullable=False, server_default="password"),
            sa.Column("oauth_id", sa.String(length=255), nullable=True),
            sa.Column("avatar_url", sa.String(length=500), nullable=True),
            sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("theme_preference", sa.String(length=20), nullable=False, server_default="system"),
            sa.Column("role", sa.String(length=20), nullable=False, server_default="user"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email"),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)
        op.create_index("ix_users_oauth_id", "users", ["oauth_id"], unique=False)
    else:
        _add_missing_columns(
            "users",
            [
                sa.Column("name", sa.String(length=120), nullable=False, server_default="User"),
                sa.Column("email", sa.String(length=255), nullable=False, server_default=""),
                sa.Column("password_hash", sa.String(length=255), nullable=True),
                sa.Column("auth_provider", sa.String(length=40), nullable=False, server_default="password"),
                sa.Column("oauth_id", sa.String(length=255), nullable=True),
                sa.Column("avatar_url", sa.String(length=500), nullable=True),
                sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
                sa.Column("theme_preference", sa.String(length=20), nullable=False, server_default="system"),
                sa.Column("role", sa.String(length=20), nullable=False, server_default="user"),
                sa.Column("created_at", sa.DateTime(), nullable=True),
                sa.Column("last_login_at", sa.DateTime(), nullable=True),
            ],
        )

    if "deployment_records" not in tables:
        op.create_table(
            "deployment_records",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("app_name", sa.String(length=200), nullable=True),
            sa.Column("app_type", sa.String(length=50), nullable=True),
            sa.Column("environment", sa.String(length=80), nullable=True),
            sa.Column("image", sa.String(length=500), nullable=True),
            sa.Column("selected_provider", sa.String(length=50), nullable=True),
            sa.Column("execution_provider", sa.String(length=50), nullable=True),
            sa.Column("selection_mode", sa.String(length=50), nullable=True),
            sa.Column("deployment_mode", sa.String(length=50), nullable=True),
            sa.Column("status", sa.String(length=80), nullable=True),
            sa.Column("rq_job_id", sa.String(length=120), nullable=True),
            sa.Column("queued_at", sa.DateTime(), nullable=True),
            sa.Column("endpoint", sa.String(length=500), nullable=True),
            sa.Column("health_status", sa.String(length=80), nullable=True),
            sa.Column("health_checked_at", sa.DateTime(), nullable=True),
            sa.Column("health_message", sa.String(length=500), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("yaml_content", sa.Text(), nullable=False),
            sa.Column("result_json", sa.JSON(), nullable=False),
            sa.Column("health_result_json", sa.JSON(), nullable=True),
            sa.Column("cleanup_status", sa.String(length=80), nullable=True),
            sa.Column("auto_cleanup_at", sa.DateTime(), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(), nullable=True),
                sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_deployment_records_user_id", "deployment_records", ["user_id"], unique=False)
        op.create_index("ix_deployment_records_status", "deployment_records", ["status"], unique=False)
        op.create_index("ix_deployment_records_rq_job_id", "deployment_records", ["rq_job_id"], unique=False)
    else:
        _add_missing_columns(
            "deployment_records",
            [
                sa.Column("user_id", sa.Integer(), nullable=True),
                sa.Column("app_name", sa.String(length=200), nullable=True),
                sa.Column("app_type", sa.String(length=50), nullable=True),
                sa.Column("environment", sa.String(length=80), nullable=True),
                sa.Column("image", sa.String(length=500), nullable=True),
                sa.Column("selected_provider", sa.String(length=50), nullable=True),
                sa.Column("execution_provider", sa.String(length=50), nullable=True),
                sa.Column("selection_mode", sa.String(length=50), nullable=True),
                sa.Column("deployment_mode", sa.String(length=50), nullable=True),
                sa.Column("status", sa.String(length=80), nullable=True),
                sa.Column("rq_job_id", sa.String(length=120), nullable=True),
                sa.Column("queued_at", sa.DateTime(), nullable=True),
                sa.Column("endpoint", sa.String(length=500), nullable=True),
                sa.Column("health_status", sa.String(length=80), nullable=True),
                sa.Column("health_checked_at", sa.DateTime(), nullable=True),
                sa.Column("health_message", sa.String(length=500), nullable=True),
                sa.Column("last_error", sa.Text(), nullable=True),
                sa.Column("started_at", sa.DateTime(), nullable=True),
                sa.Column("completed_at", sa.DateTime(), nullable=True),
                sa.Column("yaml_content", sa.Text(), nullable=True),
                sa.Column("result_json", sa.JSON(), nullable=True),
                sa.Column("health_result_json", sa.JSON(), nullable=True),
                sa.Column("cleanup_status", sa.String(length=80), nullable=True),
                sa.Column("auto_cleanup_at", sa.DateTime(), nullable=True),
                sa.Column("last_checked_at", sa.DateTime(), nullable=True),
                sa.Column("created_at", sa.DateTime(), nullable=True),
                sa.Column("updated_at", sa.DateTime(), nullable=True),
            ],
        )

    if "cloud_accounts" not in tables:
        op.create_table(
            "cloud_accounts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=20), nullable=False),
            sa.Column("display_name", sa.String(length=120), nullable=True),
            sa.Column("encrypted_credentials", sa.Text(), nullable=False),
            sa.Column("region", sa.String(length=120), nullable=True),
            sa.Column("project_id", sa.String(length=200), nullable=True),
            sa.Column("subscription_id", sa.String(length=200), nullable=True),
            sa.Column("status", sa.String(length=80), nullable=False, server_default="connected"),
            sa.Column("last_checked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "provider", name="uq_cloud_account_user_provider"),
        )
        op.create_index("ix_cloud_accounts_user_id", "cloud_accounts", ["user_id"], unique=False)
        op.create_index("ix_cloud_accounts_provider", "cloud_accounts", ["provider"], unique=False)
    else:
        _add_missing_columns(
            "cloud_accounts",
            [
                sa.Column("user_id", sa.Integer(), nullable=True),
                sa.Column("provider", sa.String(length=20), nullable=True),
                sa.Column("display_name", sa.String(length=120), nullable=True),
                sa.Column("encrypted_credentials", sa.Text(), nullable=True),
                sa.Column("region", sa.String(length=120), nullable=True),
                sa.Column("project_id", sa.String(length=200), nullable=True),
                sa.Column("subscription_id", sa.String(length=200), nullable=True),
                sa.Column("status", sa.String(length=80), nullable=False, server_default="connected"),
                sa.Column("last_checked_at", sa.DateTime(), nullable=True),
                sa.Column("created_at", sa.DateTime(), nullable=True),
                sa.Column("updated_at", sa.DateTime(), nullable=True),
            ],
        )

    if "audit_logs" not in tables:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(length=120), nullable=False),
            sa.Column("entity_type", sa.String(length=80), nullable=True),
            sa.Column("entity_id", sa.String(length=120), nullable=True),
            sa.Column("provider", sa.String(length=40), nullable=True),
            sa.Column("message", sa.String(length=500), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("request_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"], unique=False)
        op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)
        op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"], unique=False)
    else:
        _add_missing_columns(
            "audit_logs",
            [
                sa.Column("user_id", sa.Integer(), nullable=True),
                sa.Column("action", sa.String(length=120), nullable=True),
                sa.Column("entity_type", sa.String(length=80), nullable=True),
                sa.Column("entity_id", sa.String(length=120), nullable=True),
                sa.Column("provider", sa.String(length=40), nullable=True),
                sa.Column("message", sa.String(length=500), nullable=True),
                sa.Column("metadata_json", sa.JSON(), nullable=True),
                sa.Column("request_id", sa.String(length=64), nullable=True),
                sa.Column("created_at", sa.DateTime(), nullable=True),
            ],
        )


def downgrade():
    op.drop_table("audit_logs")
    op.drop_table("cloud_accounts")
    op.drop_table("deployment_records")
    op.drop_table("users")


def _add_missing_columns(table_name, columns):
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table_name, column)
