import pytest

from config import ProductionConfig, TestingConfig, _normalize_database_url


def test_postgres_url_is_normalized():
    assert _normalize_database_url("postgres://user:pass@host/db") == "postgresql://user:pass@host/db"


def test_testing_config_disables_csrf_and_rate_limiting():
    assert TestingConfig.WTF_CSRF_ENABLED is False
    assert TestingConfig.RATELIMIT_ENABLED is False


def test_production_config_requires_database_url():
    class AppConfig(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class FakeApp:
        config = AppConfig(SECRET_KEY="set", DATABASE_URL="")

    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        ProductionConfig.init_app(FakeApp())
