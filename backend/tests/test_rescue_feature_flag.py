import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from app.config import Settings, settings
from app.database import get_data_db
from app.features.rescue.router import router


class RescueFeatureFlagTests(unittest.IsolatedAsyncioTestCase):
    async def test_flag_controls_public_config_and_blocks_intake_before_parsing(self):
        app = FastAPI()
        app.include_router(router)

        async def unused_db():
            yield None

        app.dependency_overrides[get_data_db] = unused_db
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for enabled in (False, True):
                with patch.object(settings, 'RESCUE_REQUEST_ENABLED', enabled):
                    response = await client.get('/api/public/rescue-config')
                    self.assertEqual(response.json(), {'enabled': enabled})
                    self.assertEqual(response.headers['cache-control'], 'no-store')
                    if not enabled:
                        for content_type in ('application/json', 'multipart/form-data'):
                            response = await client.post('/api/public/rescue-requests', content=b'invalid body', headers={'Content-Type': content_type})
                            self.assertEqual(response.status_code, 404)

    def test_env_boolean_parsing(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertIs(Settings(_env_file=None).RESCUE_REQUEST_ENABLED, False)
        for value, expected in [('false', False), ('true', True)]:
            with patch.dict('os.environ', {'RESCUE_REQUEST_ENABLED': value}):
                self.assertIs(Settings(_env_file=None).RESCUE_REQUEST_ENABLED, expected)
