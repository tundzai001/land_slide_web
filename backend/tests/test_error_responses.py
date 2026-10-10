"""API failures must not echo credentials or server exception details."""
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.errors import install_error_handlers


class SecretPayload(BaseModel):
    password: str = Field(min_length=12)


def test_validation_and_server_errors_are_bounded():
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/validate")
    def validate(_payload: SecretPayload):
        return {"ok": True}

    @app.get("/http-error")
    def http_error():
        raise HTTPException(500, "database connection string and secret")

    @app.get("/unexpected")
    def unexpected():
        raise RuntimeError("private internal message")

    with TestClient(app, raise_server_exceptions=False) as client:
        invalid = client.post("/validate", json={"password": "topsecret"})
        assert invalid.status_code == 422
        assert "topsecret" not in invalid.text
        assert "input" not in invalid.json()["detail"][0]
        failure = client.get("/http-error")
        assert failure.status_code == 500
        assert "secret" not in failure.text
        unexpected_response = client.get("/unexpected")
        assert unexpected_response.status_code == 500
        assert "private internal" not in unexpected_response.text
