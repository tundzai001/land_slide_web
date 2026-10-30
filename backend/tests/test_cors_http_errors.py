import io
import urllib.error
from unittest.mock import patch

import pytest

from processors.gnss_adjustment.cors import RoundRobinCorsMixin


def test_proxy_error_keeps_status_without_html_and_closes_response():
    cors = RoundRobinCorsMixin()
    cors.web_cors_api_base_url = "https://cors.example"
    body = io.BytesIO(b"<html>upstream internal details</html>")
    error = urllib.error.HTTPError("https://cors.example/api/integrations/stations", 502, "Bad Gateway", {}, body)
    with patch("processors.gnss_adjustment.cors.urllib.request.urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="CORS API HTTP 502 for /api/integrations/stations: Bad Gateway") as raised:
            cors._cors_api_request_sync("GET", "/api/integrations/stations")
    assert "<html>" not in str(raised.value)
    assert body.closed


def test_api_validation_error_retains_detail():
    cors = RoundRobinCorsMixin()
    cors.web_cors_api_base_url = "https://cors.example"
    body = io.BytesIO(b'{"detail":"station is not configured"}')
    error = urllib.error.HTTPError("https://cors.example/api/integrations/stations", 422, "Unprocessable Entity", {}, body)
    with patch("processors.gnss_adjustment.cors.urllib.request.urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="station is not configured"):
            cors._cors_api_request_sync("GET", "/api/integrations/stations")
    assert body.closed
