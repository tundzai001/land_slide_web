import json,time,tempfile
from sqlalchemy import create_engine,Integer,MetaData,select
from app.models.data import SensorData
from app.features.stations.history_query import build_sensor_history_query
from app.shared.sensor_catalog import SENSOR_CATALOG
with tempfile.TemporaryDirectory(prefix='monitoring-load-') as directory:
 engine=create_engine(f'sqlite:///{directory}/load.db')
 table=SensorData.__table__.to_metadata(MetaData()); table.c.id.type=Integer()
 table.metadata.create_all(engine)
 kinds=list(SENSOR_CATALOG); base=1700000000
 start=time.perf_counter()
 with engine.begin() as connection:
  for offset in range(0,100000,1000):
   rows=[]
   for index in range(offset,offset+1000):
    kind=kinds[index%len(kinds)]
    payload={field:index%100 for field in SENSOR_CATALOG[kind]['fields']}
    if kind=='extensometer':payload={'points':{'A1':index%100,'A2':0}}
    rows.append({'id':index+1,'station_id':1,'sensor_type':kind,'timestamp':base+index,
      'data':payload,'value_1':index%100,'value_2':-(index%50),'value_3':index%25})
   connection.execute(table.insert(),rows)
 inserted=time.perf_counter()-start
 with engine.connect() as connection:
  start=time.perf_counter()
  rows=connection.execute(build_sensor_history_query(table,1,set(kinds),base,500,'sqlite')).all()
  elapsed=time.perf_counter()-start
  counts={kind:sum(row.sensor_type==kind for row in rows) for kind in kinds}
  assert max(counts.values())<=500
  result={'database':'isolated SQLite','input_rows':100000,'sensor_types':14,'insert_seconds':round(inserted,3),'history_seconds':round(elapsed,3),'history_rows':len(rows),'maximum_per_sensor':max(counts.values()),'response_json_bytes':len(json.dumps([dict(row._mapping) for row in rows],ensure_ascii=False).encode())}
  print(json.dumps(result))
 wave={'start_at':base,'sample_rate_hz':250,'x':[0.01]*1024,'y':[-0.02]*1024,'z':[0.03]*1024}
 data={'x':0,'y':0,'z':0,'waveform':wave}
 size=len(json.dumps(data,separators=(',',':')).encode())
 print(json.dumps({'waveform_example_bytes':size,'samples_per_packet':1024,'sampling_hz':250,'continuous_payload_MB_per_day_per_sensor':round(size*250/1024*86400/1e6,1),'note':'JSON example only; excludes DB indexes, WAL, backups and compression'}))
 engine.dispose()
