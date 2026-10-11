"""HTTP/RBAC and real SQLite persistence checks for saved project map positions."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import auth
from app.features.authentication import sessions as auth_sessions
from app.shared import access
from app.database import BaseAuth, BaseConfig, get_auth_db, get_config_db
from app.models.auth import User
from app.models.config import GlobalConfig, Project, Station
from app.features.projects import admin, public
from app.features.database_admin.write_router import router as database_router
from app.features.stations.configuration import router as station_config_router
from app.shared.project_location import backfill_project_map_positions
from app.shared import project_dem


class ProjectMapPositionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='project-map-db-')
        self.engine = create_async_engine(f'sqlite+aiosqlite:///{self.directory.name}/test.db')
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(BaseAuth.metadata.create_all)
            await connection.run_sync(BaseConfig.metadata.create_all)
        async with self.sessions() as db:
            for username, role, assigned in [('admin', 'admin', []), ('operator', 'operator', [1]), ('empty', 'operator', []), ('viewer', 'viewer', [2])]:
                db.add(User(username=username, role=role, assigned_projects=assigned, is_active=True, hashed_password='unused'))
            db.add_all([
                Project(id=1, project_code='P1', name='Dự án 1', location='Lào Cai', created_at=1, updated_at=1,
                    gnss_clusters=[{'name': 'Cụm 1', 'stations': [1, 2], 'base_service_config': {'password': 'DO_NOT_EXPOSE'}}],
                    auto_adjustment_config={'token': 'DO_NOT_EXPOSE'}),
                Project(id=2, project_code='P2', name='Dự án 2', location={'address': 'Hà Nội', 'lat': 21, 'lon': 105, 'legacy': 'preserve'}, created_at=1, updated_at=1),
                Project(id=3, project_code='P3', name='Chưa có trạm', created_at=1, updated_at=1),
                Station(id=1, project_id=1, station_code='S1', name='S1', location={'lat': 22, 'lon': 103}, created_at=1, updated_at=1),
                Station(id=2, project_id=1, station_code='S2', name='S2', location={'lat': 24, 'lon': 105}, created_at=1, updated_at=1),
                Station(id=3, project_id=1, station_code='S3', name='S3', location={'lat': None, 'lon': None}, created_at=1, updated_at=1),
            ])
            await db.commit()
            await backfill_project_map_positions(db)
        app = FastAPI()
        for router in (admin.router, public.router, database_router, station_config_router):
            app.include_router(router)

        async def session():
            async with self.sessions() as db:
                yield db
        app.dependency_overrides[get_config_db] = session
        app.dependency_overrides[get_auth_db] = session
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')
        auth.invalidate_user_cache()
        # These tests exercise project RBAC; durable session behavior has its own suite.
        self.session_check = patch.object(auth_sessions, 'valid', return_value=True)
        self.session_check.start()
        self.public_monitoring = patch.object(access.config.settings, 'PUBLIC_MONITORING_ENABLED', True)
        self.public_monitoring.start()

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()
        self.directory.cleanup()
        auth.invalidate_user_cache()
        self.session_check.stop()
        self.public_monitoring.stop()

    def headers(self, username='admin'):
        return {'Authorization': f'Bearer {auth.create_access_token({"sub": username})}'}

    async def location(self, project_id=1):
        async with self.sessions() as db:
            return (await db.get(Project, project_id)).location

    async def test_backfill_is_persisted_idempotent_and_preserves_legacy_address(self):
        self.assertEqual(await self.location(), {'address': 'Lào Cai', 'map_mode': 'auto', 'lat': 23.0, 'lon': 104.0})
        legacy = await self.location(2)
        self.assertEqual(legacy, {'address': 'Hà Nội', 'lat': 21.0, 'lon': 105.0, 'map_mode': 'manual', 'legacy': 'preserve'})
        async with self.sessions() as db:
            await backfill_project_map_positions(db)
        self.assertEqual(await self.location(2), legacy)
        self.assertIsNone((await self.location(3))['lat'])

    async def test_write_permissions_and_project_read_scope(self):
        payload = {'map_position': {'mode': 'manual', 'lat': 10, 'lon': 106}}
        self.assertEqual((await self.client.put('/api/admin/projects/1', json=payload)).status_code, 401)
        for user in ('operator', 'viewer', 'empty'):
            self.assertEqual((await self.client.put('/api/admin/projects/1', json=payload, headers=self.headers(user))).status_code, 403)
            self.assertEqual((await self.client.post('/api/admin/projects', json=payload, headers=self.headers(user))).status_code, 403)
        for user, ids in [('operator', [1]), ('empty', []), ('viewer', [2])]:
            for endpoint in ('/api/admin/projects', '/api/projects'):
                response = await self.client.get(endpoint, headers=self.headers(user))
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('DO_NOT_EXPOSE', response.text)
                self.assertEqual([row['id'] for row in response.json()], ids)
        self.assertEqual((await self.location())['lat'], 23)

    async def test_manual_auto_station_edits_and_legacy_client_round_trip(self):
        response = await self.client.put('/api/admin/projects/1', headers=self.headers(), json={
            'map_position': {'mode': 'manual', 'lat': 10, 'lon': 106}, 'location': 'Địa chỉ mới'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.location())['lat'], 10)
        response = await self.client.put('/api/admin/db/stations/1', headers=self.headers(), json={'location': {'lat': 20, 'lon': 100}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.location())['lat'], 10)
        await self.client.put('/api/admin/projects/1', headers=self.headers(), json={'location': {'address': 'Legacy edit', 'map_mode': 'auto', 'lat': 99, 'lon': 99}})
        self.assertEqual((await self.location())['map_mode'], 'manual')
        self.assertEqual((await self.location())['lat'], 10)
        response = await self.client.put('/api/admin/projects/1', headers=self.headers(), json={'map_position': {'mode': 'auto'}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.location())['lat'], 22)
        await self.client.put('/api/admin/db/stations/1', headers=self.headers(), json={'project_id': 3})
        self.assertEqual((await self.location())['lat'], 24)
        self.assertEqual((await self.location(3))['lat'], 20)
        await self.client.delete('/api/admin/db/stations/2', headers=self.headers())
        self.assertIsNone((await self.location())['lat'])

    async def test_invalid_coordinates_return_422_without_changing_saved_data(self):
        before = await self.location()
        invalid = [None, {}, {'mode': 'other'}, {'mode': 'auto', 'lat': 1},
            {'mode': 'manual'}, {'mode': 'manual', 'lat': 0, 'lon': 0},
            *({'mode': 'manual', 'lat': value, 'lon': 103} for value in (None, '', '22', True, 91, -91, float('nan'), float('inf'))),
            {'mode': 'manual', 'lat': 22, 'lon': 181}]
        for position in invalid:
            response = await self.client.put('/api/admin/projects/1', headers={**self.headers(), 'Content-Type': 'application/json'},
                content=json.dumps({'map_position': position}))
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(await self.location(), before)

    async def test_manual_point_without_sensors_and_public_response_has_no_base_secrets(self):
        response = await self.client.post('/api/admin/projects', headers=self.headers(), json={
            'project_code': 'P4', 'name': 'Điểm nhập tay', 'location': 'Địa chỉ',
            'map_position': {'mode': 'manual', 'lat': 0, 'lon': 105}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.location(response.json()['id']))['lon'], 105)
        response = await self.client.get('/api/projects')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('DO_NOT_EXPOSE', response.text)
        project = next(row for row in response.json() if row['id'] == 1)
        self.assertEqual(project['gnss_clusters'], [{'name': 'Cụm 1', 'stations': [1, 2]}])
        self.assertEqual(project['location'], await self.location())

    async def test_project_search_treats_wildcards_as_literal_text(self):
        async with self.sessions() as db:
            db.add(Project(project_code='P_%', name='Đập 100%', created_at=2, updated_at=2))
            await db.commit()
        for query in ('%', '_'):
            response = await self.client.get('/api/projects', params={'q': query})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual([row['project_code'] for row in response.json()], ['P_%'])
        too_long = await self.client.get('/api/projects', params={'q': 'x' * 101})
        self.assertEqual(too_long.status_code, 422)

    async def test_project_dem_upload_readback_and_project_scope(self):
        grid = (
            b"ncols 2\nnrows 2\nxllcorner 454959.202\nyllcorner 2326094.284\n"
            b"cellsize 1\nNODATA_value -9999\n100 101\n98 99\n"
        )
        with tempfile.TemporaryDirectory(prefix="project-dem-test-") as directory:
            with patch.object(project_dem, "PROJECT_DEM_DIR", Path(directory)):
                uploaded = await self.client.post(
                    "/api/admin/projects/1/dems",
                    headers=self.headers(),
                    data={"dem_name": "Thân đập"},
                    files={"dem_file": ("dam.asc", grid, "text/plain")},
                )
                self.assertEqual(uploaded.status_code, 200, uploaded.text)
                self.assertEqual(uploaded.json()["dem"]["crs"], "EPSG:32648")
                self.assertEqual(uploaded.json()["dem"]["name"], "Thân đập")
                dem_id = uploaded.json()["dem_id"]
                added_slope = await self.client.post(
                    "/api/admin/projects/1/dems",
                    headers=self.headers(),
                    data={"dem_name": "Bờ mỏ"},
                    files={"dem_file": ("slope.asc", grid, "text/plain")},
                )
                self.assertEqual(added_slope.status_code, 200, added_slope.text)
                self.assertNotEqual(added_slope.json()["dem_id"], dem_id)
                async with self.sessions() as db:
                    catalog = await db.get(GlobalConfig, "project_dem:1")
                    self.assertEqual([item["name"] for item in catalog.value["models"]], ["Thân đập", "Bờ mỏ"])

                models = await self.client.get("/api/projects/1/dems", headers=self.headers("operator"))
                self.assertEqual(models.json()["models"][0]["id"], dem_id)
                self.assertEqual([model["name"] for model in models.json()["models"]], ["Thân đập", "Bờ mỏ"])
                readback = await self.client.get(f"/api/projects/1/dems/{dem_id}", headers=self.headers("operator"))
                self.assertEqual(readback.status_code, 200, readback.text)
                self.assertEqual(readback.content, grid)

                hidden = await self.client.get("/api/projects/1/dems", headers=self.headers("empty"))
                self.assertEqual(hidden.status_code, 404)
                project_list = await self.client.get("/api/projects")
                project = next(row for row in project_list.json() if row["id"] == 1)
                self.assertTrue(project["has_dem"])

    async def test_dem_placed_station_location_survives_sensor_config_updates(self):
        selected = {
            "lat": 22.6, "lon": 103.8, "h": 101.5,
            "source": "project-dem-grid", "dem_name": "Thân đập",
        }
        async with self.sessions() as db:
            station = await db.get(Station, 1)
            station.location = selected
            await db.commit()

        response = await self.client.put(
            "/api/admin/stations/1/config",
            headers=self.headers(),
            json={
                "config": {"gnss_origin": {"lat": 22.7, "lon": 103.9, "h": 90}},
                "sensors": {},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Station, 1)).location, selected)

    async def test_public_cluster_projection_drops_unexpected_nested_lists(self):
        async with self.sessions() as db:
            project = await db.get(Project, 1)
            project.gnss_clusters = [
                {'name': 'Safe', 'stations': [1], 'base_service_config': {'password': 'DO_NOT_EXPOSE'}},
                [{'base_service_config': {'password': 'DO_NOT_EXPOSE'}}],
            ]
            await db.commit()
        response = await self.client.get('/api/projects')
        self.assertEqual(response.status_code, 200, response.text)
        project = next(row for row in response.json() if row['id'] == 1)
        self.assertEqual(project['gnss_clusters'], [{'name': 'Safe', 'stations': [1]}])
        self.assertNotIn('DO_NOT_EXPOSE', response.text)

    async def test_station_config_cannot_change_another_projects_position(self):
        response = await self.client.put('/api/admin/stations/1/config', headers=self.headers('empty'),
            json={'config': {'gnss_origin': {'lat': 10, 'lon': 106}}})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual((await self.location())['lat'], 23)
        response = await self.client.put('/api/admin/stations/1/config', headers=self.headers('operator'),
            json={'config': {'gnss_origin': {'lat': 20, 'lon': 101}}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.location())['lat'], 22)


if __name__ == '__main__':
    unittest.main()
