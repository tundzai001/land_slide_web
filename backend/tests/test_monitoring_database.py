"""Real isolated SQLite read/write tests; production PostgreSQL SQL is compiled too."""
import json
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Response
from sqlalchemy import Integer, event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import BaseConfig, BaseData
from app.models import config as config_models, data as data_models
from app.models.pi_device import PiDevice
from app.features.stations import query_router
from app.features.stations.history_query import build_sensor_history_query
from app.features.stations.common import _load_station_runtime_maps
from app.features.database_admin.read_router import admin_get_sensor_data, PUBLIC_SENSOR_TYPES
from app.features.data_export.sensors import export_sensor_record
from app.mqtt.persistence.ingest import SensorIngestPersistenceMixin
from app.shared.sensor_catalog import MONITORING_TYPES, SENSOR_CATALOG, process_monitoring_payload


class MonitoringDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='monitoring-db-')
        self.engine = create_async_engine(f'sqlite+aiosqlite:///{self.directory.name}/isolated.db')
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.old_id_type = data_models.SensorData.__table__.c.id.type
        data_models.SensorData.__table__.c.id.type = self.old_id_type.with_variant(Integer(), 'sqlite')
        async with self.engine.begin() as connection:
            await connection.run_sync(BaseData.metadata.create_all)
            await connection.run_sync(BaseConfig.metadata.create_all)
        self.now = int(time.time())
        async with self.sessions() as session:
            session.add(config_models.Project(id=1,project_code='P1',name='Project',created_at=self.now,updated_at=self.now))
            session.add(config_models.Station(id=1,station_code='ST1',name='Monitoring',project_id=1,
                        config={},created_at=self.now,updated_at=self.now))
            for index, kind in enumerate(SENSOR_CATALOG,1):
                session.add(config_models.Device(id=index,device_code=f'D{index}',name=kind,device_type=kind,
                    station_id=1,created_at=self.now,updated_at=self.now,is_active=True))
            await session.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()
        data_models.SensorData.__table__.c.id.type = self.old_id_type
        self.directory.cleanup()

    async def seed(self, count=1):
        records = []
        self.payloads = {}
        for kind, spec in SENSOR_CATALOG.items():
            if kind in MONITORING_TYPES:
                payload = {field:0 for field in spec['fields']}
                if kind == 'extensometer': payload = {'points':{f'A{i}':i/100 for i in range(64)}}
                payload = process_monitoring_payload(kind,payload)
            else: payload = {spec['field']:0}
            self.payloads[kind] = payload
            records.append({'station_id':1,'sensor_type':kind,'timestamp':self.now,'data':payload,
                'value_1':0,'value_2':0,'value_3':0,'ingest_id':kind})
        wave = {'start_at':self.now-5000,'sample_rate_hz':250,
                'x':[0.01]*1024,'y':[-0.02]*1024,'z':[0.03]*1024}
        for index in range(count):
            records.append({'station_id':1,'sensor_type':'accelerometer','timestamp':self.now-count+index,
                'data':{'x':index,'y':-index,'z':index/2,'unit':'m/s²','waveform':wave,'sequence':index},
                'value_1':index,'value_2':-index,'value_3':index/2,'ingest_id':f'wave-{index}'})
        writer = SensorIngestPersistenceMixin()
        with patch('app.mqtt.persistence.ingest.DataSessionLocal', self.sessions):
            result = await writer._persist_sensor_batch(records)
        self.assertEqual(result['inserted'], len(records))
        async with self.sessions() as session:
            session.add(data_models.LatestSensorCache(station_id=1,sensor_type='accelerometer',timestamp=self.now,data=records[-1]['data']))
            await session.commit()
        return records

    async def test_all_sensor_types_are_written_listed_and_exported(self):
        await self.seed()
        self.assertEqual(set(PUBLIC_SENSOR_TYPES),set(SENSOR_CATALOG))
        async with self.sessions() as session:
            page = await admin_get_sensor_data(Response(),limit=100,include_total=False,include_data=False,db=session,current_user=None)
            self.assertEqual({row['sensor_type'] for row in page},set(SENSOR_CATALOG))
            self.assertTrue(all('data' not in row for row in page))
            rows = (await session.execute(select(data_models.SensorData))).scalars().all()
            for row in rows:
                self.assertIsNotNone(export_sensor_record(row, {}))
            ext = next(row for row in rows if row.sensor_type=='extensometer')
            self.assertEqual(len(ext.data['points']),64)

    async def test_history_and_detail_do_not_load_waveforms_in_trends(self):
        records = await self.seed(count=1000)
        with patch.object(query_router,'get_optional_current_user_from_request',AsyncMock(return_value=None)):
            async with self.sessions() as session:
                for limit in [1,7,8,50,500]:
                    response = await query_router.get_station_history(1,None,sensor_types='accelerometer,extensometer',hours=24,
                        limit=limit,db_config=session,db_data=session,db_auth=None)
                    for sensor in response['sensors'].values():
                        self.assertLessEqual(len(sensor['history']),limit)
                        self.assertTrue(all('waveform' not in row['data'] for row in sensor['history']))
                    if limit==500:
                        waves=response['sensors']['accelerometer']['history']
                        self.assertEqual(waves[0]['timestamp'],self.now-1000)
                        self.assertEqual(waves[-1]['timestamp'],self.now)
                        self.assertLess(len(json.dumps(response)),150000)
                detail = await query_router.get_station_detail(1,None,db_config=session,db_data=session,db_auth=None)
                sensor=detail['sensors']['accelerometer']
                self.assertEqual(len(sensor['latest']['waveform']['x']),1024)
                self.assertTrue(all('waveform' not in row['data'] for row in sensor['history']))
                self.assertEqual(len(detail['sensors']['extensometer']['latest']['points']),64)
                stored=(await session.execute(select(data_models.SensorData).where(data_models.SensorData.ingest_id=='wave-0'))).scalar_one()
                self.assertEqual(stored.data['waveform'],records[-1]['data']['waveform'])

    async def test_station_list_reads_timestamps_without_payloads(self):
        await self.seed()
        queries=[]
        def capture(connection,cursor,statement,parameters,context,executemany): queries.append(statement)
        event.listen(self.engine.sync_engine,'before_cursor_execute',capture)
        try:
            async with self.sessions() as session:
                stations=(await session.execute(select(config_models.Station))).scalars().all()
                _,latest,_=await _load_station_runtime_maps(stations,session,session)
                self.assertEqual(latest[(1,'accelerometer')],self.now)
            cache_queries=[sql for sql in queries if 'FROM latest_sensor_cache' in sql]
            self.assertEqual(len(cache_queries),1)
            self.assertNotIn('latest_sensor_cache.data',cache_queries[0])
        finally: event.remove(self.engine.sync_engine,'before_cursor_execute',capture)

    def test_postgres_history_keeps_json_out_of_ranking(self):
        query=build_sensor_history_query(data_models.SensorData.__table__,1,{'accelerometer'},0,500,'postgresql')
        sql=str(query.compile(dialect=postgresql.dialect(),compile_kwargs={'literal_binds':True}))
        self.assertIn("AS JSONB) - 'waveform'",sql)
        self.assertNotIn('sensor_data.data',sql[sql.index('\nFROM '):])


class MonitoringPostgresBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_burst_is_split_into_bounded_statements_in_one_transaction(self):
        class Session:
            bind=SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            async def execute(self,statement):
                compiled=statement.compile(dialect=postgresql.dialect())
                counts.append(len([key for key in compiled.params if key.startswith('station_id_m')]))
                self_test.assertIn('ON CONFLICT DO NOTHING',str(compiled))
                return SimpleNamespace(rowcount=counts[-1])
            async def commit(self): commits.append(True)
        self_test=self; counts=[]; commits=[]
        rows=[{'station_id':1,'timestamp':i,'sensor_type':'accelerometer','data':{'x':0},'ingest_id':str(i)} for i in range(700)]
        with patch('app.mqtt.persistence.ingest.DataSessionLocal',return_value=Session()):
            result=await SensorIngestPersistenceMixin()._persist_sensor_batch(rows)
        self.assertEqual(counts,[256,256,188])
        self.assertEqual(len(commits),1)
        self.assertEqual(result['inserted'],700)


class MonitoringOutageTests(unittest.IsolatedAsyncioTestCase):
    def make_writer(self, spool):
        import asyncio
        writer=SensorIngestPersistenceMixin()
        writer._ingest_spool=spool
        writer._buffer_lock=asyncio.Lock()
        writer._sensor_buffer=[{'station_id':1,'timestamp':1,'sensor_type':'accelerometer','data':{'waveform':{'x':[0,-2,1]}}}]
        writer._latest_cache_buffer={}
        writer._station_update_buffer={}
        writer._device_update_buffer={}
        writer._persist_sensor_batch=AsyncMock(side_effect=RuntimeError('synthetic DB outage'))
        return writer

    async def test_failed_flush_hands_waveform_to_disk_without_ram_duplicate(self):
        from app.infrastructure.ingest_spool import IngestSpool
        with tempfile.TemporaryDirectory() as directory:
            spool=IngestSpool(directory)
            writer=self.make_writer(spool)
            expected=writer._sensor_buffer[0]['data']
            await writer._flush_write_buffer()
            self.assertEqual(writer._sensor_buffer,[])
            pending=await IngestSpool(directory).pending()
            self.assertEqual(len(pending),1)
            self.assertEqual(pending[0]['records'][0]['data'],expected)
            await writer._flush_write_buffer()
            self.assertEqual(len(await spool.pending()),1)

    async def test_rejected_disk_write_keeps_ram_record_and_retries(self):
        spool=SimpleNamespace(append=AsyncMock(return_value=False))
        writer=self.make_writer(spool)
        for _ in range(2):
            await writer._flush_write_buffer()
            self.assertEqual(len(writer._sensor_buffer),1)
            self.assertNotIn('_spool_id',writer._sensor_buffer[0])
        self.assertEqual(spool.append.await_count,2)

    async def test_disk_error_also_keeps_record_for_retry(self):
        spool=SimpleNamespace(append=AsyncMock(side_effect=OSError('synthetic disk error')))
        writer=self.make_writer(spool)
        await writer._flush_write_buffer()
        self.assertEqual(len(writer._sensor_buffer),1)
        self.assertNotIn('_spool_id',writer._sensor_buffer[0])

    def test_gateway_redelivery_uses_measurement_identity(self):
        writer=SensorIngestPersistenceMixin()
        payload={'x':0,'y':1,'z':2,'waveform':{'start_at':100.125,'x':[0]},'received_at':200}
        first=writer._make_ingest_id(1,1,'accelerometer',200,payload)
        second=writer._make_ingest_id(1,1,'accelerometer',300,{**payload,'received_at':300})
        other=writer._make_ingest_id(1,1,'accelerometer',300,{**payload,'waveform':{'start_at':100.129,'x':[0]}})
        self.assertEqual(first,second)
        self.assertNotEqual(first,other)


class MonitoringCacheBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_cache_burst_is_bounded(self):
        import asyncio
        counts=[]; commits=[]
        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            async def execute(self,statement):
                compiled=statement.compile(dialect=postgresql.dialect())
                counts.append(len([key for key in compiled.params if key.startswith('station_id_m')]))
            async def commit(self): commits.append(True)
        writer=SensorIngestPersistenceMixin()
        writer._buffer_lock=asyncio.Lock()
        writer._sensor_buffer=[]
        writer._station_update_buffer={}
        writer._device_update_buffer={}
        writer._latest_cache_buffer={(i,'temperature'):{'station_id':i,'sensor_type':'temperature','timestamp':1,'data':{'temperature':0}} for i in range(700)}
        with patch('app.mqtt.persistence.ingest.DataSessionLocal',return_value=Session()):
            await writer._flush_write_buffer()
        self.assertEqual(counts,[256,256,188])
        self.assertEqual(commits,[True])
        self.assertEqual(writer._latest_cache_buffer,{})


class MonitoringSpoolReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_stops_before_reading_the_entire_file(self):
        from app.infrastructure.ingest_spool import IngestSpool
        def rows():
            yield {'batch_id':'first','records':[{'x':0}]}
            raise AssertionError('Read past requested envelope limit')
        spool=IngestSpool()
        with patch.object(spool,'_iter_sync',rows):
            self.assertEqual((await spool.pending(limit=1))[0]['batch_id'],'first')

    async def test_stats_and_ack_preserve_unacknowledged_batches(self):
        from app.infrastructure.ingest_spool import IngestSpool
        with tempfile.TemporaryDirectory() as directory:
            spool=IngestSpool(directory)
            for i in range(20):
                await spool.append(str(i),[{'value':i}])
            await spool.acknowledge('0','10','19')
            stats=await spool.stats()
            self.assertEqual(stats['batches'],17)
            self.assertEqual(stats['records'],17)
            pending=await spool.pending(limit=20)
            self.assertEqual([batch['batch_id'] for batch in pending],[str(i) for i in range(20) if i not in (0,10,19)])
