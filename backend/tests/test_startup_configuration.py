"""A legacy MQTT credential must not take an existing deployment offline."""
import pytest

from app.config import Settings


def test_production_allows_broker_credential_transition_but_rejects_default_signing_key():
    values = dict(
        _env_file=None, ENVIRONMENT="production", CORS_ORIGINS="https://monitoring.example",
        MQTT_BROKER="broker.example", MQTT_PASSWORD="custom_secure_password_123",
    )
    Settings(**values, SECRET_KEY="a" * 48).validate_security()

    invalid_settings = Settings(**values, SECRET_KEY="super_secret_key_change_me_in_production")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        invalid_settings.validate_security()


def test_cors_origins_and_server_host_properties():
    settings = Settings(
        _env_file=None,
        CORS_ORIGINS="https://site1.example, https://site2.example, ",
        SERVER_HOST="127.0.0.1",
        SERVER_PORT=8001
    )
    assert settings.allowed_cors_origins == ["https://site1.example", "https://site2.example"]
    assert settings.SERVER_HOST == "127.0.0.1"
    assert settings.SERVER_PORT == 8001
