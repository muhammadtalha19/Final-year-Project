import os
import sys


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() == "true"


def _normalize_database_url(url: str) -> str:
    if url and url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY")
    DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL", ""))
    SQLALCHEMY_DATABASE_URI = DATABASE_URL or "sqlite:///orchestrator.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    SENTRY_DSN = os.getenv("SENTRY_DSN", "")
    CREDENTIAL_ENCRYPTION_KEY = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "")
    ENABLE_REAL_DEPLOYMENT = _env_bool("ENABLE_REAL_DEPLOYMENT")
    ALLOW_AWS_DEPLOYMENT = _env_bool("ALLOW_AWS_DEPLOYMENT")
    ALLOW_AZURE_DEPLOYMENT = _env_bool("ALLOW_AZURE_DEPLOYMENT")
    ALLOW_GCP_DEPLOYMENT = _env_bool("ALLOW_GCP_DEPLOYMENT")
    MODEL_B_USER_CLOUD_ACCOUNTS = _env_bool("MODEL_B_USER_CLOUD_ACCOUNTS", "true")
    ALLOW_ADMIN_CLOUD_FALLBACK = _env_bool("ALLOW_ADMIN_CLOUD_FALLBACK")
    DEPLOYMENT_TIMEOUT_SECONDS = int(os.getenv("DEPLOYMENT_TIMEOUT_SECONDS", "180"))
    AUTO_TERMINATE_ON_FAILURE = _env_bool("AUTO_TERMINATE_ON_FAILURE")
    MAX_ACTIVE_DEPLOYMENTS_PER_USER = int(os.getenv("MAX_ACTIVE_DEPLOYMENTS_PER_USER", "3"))
    MAX_REAL_DEPLOYMENTS_PER_DAY = int(os.getenv("MAX_REAL_DEPLOYMENTS_PER_DAY", "5"))
    MAX_MONTHLY_COST_LIMIT_USD = float(os.getenv("MAX_MONTHLY_COST_LIMIT_USD", "50"))
    WTF_CSRF_ENABLED = _env_bool("WTF_CSRF_ENABLED", "true")
    RATELIMIT_ENABLED = _env_bool("RATELIMIT_ENABLED", "true")
    BACKGROUND_JOBS_ENABLED = _env_bool("BACKGROUND_JOBS_ENABLED")
    AUTO_CREATE_DB = _env_bool("AUTO_CREATE_DB")

    @classmethod
    def init_app(cls, app):
        if not app.config.get("SECRET_KEY") and not app.config.get("TESTING"):
            raise RuntimeError("SECRET_KEY is required. Set it in environment variables or .env.")


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = BaseConfig.DATABASE_URL or "sqlite:///orchestrator.db"


class TestingConfig(BaseConfig):
    TESTING = True
    SECRET_KEY = os.getenv("SECRET_KEY", "test-only-secret-key")
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///orchestrator-test.db"))
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    BACKGROUND_JOBS_ENABLED = False
    AUTO_CREATE_DB = True


class ProductionConfig(BaseConfig):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = BaseConfig.DATABASE_URL

    @classmethod
    def init_app(cls, app):
        super().init_app(app)
        if not app.config.get("DATABASE_URL"):
            raise RuntimeError("DATABASE_URL is required in production.")


def get_config_class():
    env = os.getenv("FLASK_ENV", "development").strip().lower()
    if "pytest" in sys.modules or env == "testing":
        return TestingConfig
    if env == "production":
        return ProductionConfig
    return DevelopmentConfig
