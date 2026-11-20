"""Tests for public map configuration endpoint."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.features.stations.query_router import router
from app.config import settings


class MapConfigTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_public_token_is_available_without_exposing_secrets(self):
        with patch.object(settings, 'MAPBOX_PUBLIC_TOKEN', 'pk.test-public-token'), \
             patch.object(settings, 'MAPBOX_ACCESS_TOKEN', ''):
            response = self.client.get('/api/public/map-config')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'mapbox_public_token': 'pk.test-public-token'})
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_fallback_to_mapbox_access_token_if_starts_with_pk(self):
        with patch.object(settings, 'MAPBOX_PUBLIC_TOKEN', ''), \
             patch.object(settings, 'MAPBOX_ACCESS_TOKEN', 'pk.legacy-token'):
            response = self.client.get('/api/public/map-config')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'mapbox_public_token': 'pk.legacy-token'})
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_secret_or_invalid_tokens_are_never_published(self):
        for invalid_val in ('sk.secret-key', 'secret', '', 'invalid.token'):
            with self.subTest(invalid_val=invalid_val), \
                 patch.object(settings, 'MAPBOX_PUBLIC_TOKEN', invalid_val), \
                 patch.object(settings, 'MAPBOX_ACCESS_TOKEN', invalid_val):
                response = self.client.get('/api/public/map-config')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {'mapbox_public_token': ''})
                self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_vietnam_provinces_geojson_endpoint(self):
        response = self.client.get('/api/public/vietnam-provinces-geojson')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'application/json')
        data = response.json()
        self.assertEqual(data.get('type'), 'FeatureCollection')
        self.assertGreaterEqual(len(data.get('features', [])), 1)
