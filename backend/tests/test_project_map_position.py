"""HTTP/RBAC and real SQLite persistence checks for saved project map positions."""
import json
import tempfile
import unittest

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import auth
from app.database import BaseAuth, BaseConfig, get_auth_db, get_config_db
from app.models.auth import User
from app.models.config import Project, Station
from app.features.projects import admin, public
from app.features.database_admin.write_router import router as database_router
from app.features.stations.configuration import router as station_config_router
from app.shared.project_location import backfill_project_map_positions


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

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()
        self.directory.cleanup()
        auth.invalidate_user_cache()

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
