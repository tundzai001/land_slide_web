"""A legacy MQTT credential must not take an existing deployment offline."""
import pytest

from app.config import Settings


def test_production_allows_broker_credential_transition_but_rejects_default_signing_key():
    values = dict(
        _env_file=None, ENVIRONMENT="production", CORS_ORIGINS="https://monitoring.example",
        MQTT_BROKER="broker.example", MQTT_PASSWORD="",
    )
    Settings(**values, SECRET_KEY="a" * 48).validate_security()

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        Settings(**values, SECRET_KEY="super_secret_key_change_me_in_production").validate_security()
