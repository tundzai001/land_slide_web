# Backend module map

`main.py` is only the composition root: lifecycle, middleware, router
registration, and static mounts. Business logic belongs to its feature or
processing domain.

## Feature domains

- `features/gnss_adjustment/`: adjustment HTTP workflow, cluster selection,
  run state, compact result persistence, evidence persistence, and failure
  persistence. It does not calculate coordinates and it does not render files.
- `features/data_export/`: all on-demand exports. It is split by responsibility:
  - `database/{job.py,router.py}` — DB-backed ZIP export job and download API;
  - `sensors/{gnss,imu,rain,water}.py` — explicit sensor writers;
  - `reports/adjustment/` — adjustment workbook, failure workbook, artifact
    assembly, and report routes;
  - `reports/{simulation.py,station.py}` — simulation/station reports;
  - `cells.py` — safe chunking of long JSON strings for spreadsheet cells;
  - `filenames.py` — safe archive and station filenames.
- `features/simulation/`: `runs.py` owns run endpoints, `service.py` owns
  lifecycle/input preparation, `exports.py` owns report downloads, and
  `engine.py` owns deterministic calculations.
- `features/stations/`: `crud.py`, `configuration.py`, `commands.py`,
  `audio.py`, `ntrip.py`, `origin.py`, `query_router.py`, and
  `analysis_router.py` each own one station responsibility.
- `features/incidents/`: `read_router.py` and `write_router.py` are HTTP
  boundaries, `common.py` is authorization/query support, `cases.py` is the
  incident domain, and `schemas.py` contains mutation bodies.
- `features/projects/`: public/admin project routes and project-level CORS.
- `features/devices/`: device administration, licensing, and GNSS-origin reset.
- `features/field/`: field-device enrollment, provisioning, and siren control.
- `features/frontend/`: HTML/public assets and WebSockets.
- `features/database_admin/`: database read/write/maintenance endpoints.
- `features/gnss_monitoring/`: GNSS risk mapping and rollups.

The calculation core remains under `backend/processors/gnss_adjustment/`:
geometry, observations, receiver/rover handling, cycle processing, solving,
statistics, and session lifecycle. `gnss_adjustment_runtime.py` is not part of
the architecture. There is no duplicate adjustment implementation in exports.

## Messaging and persistence

- `mqtt/transport.py`: MQTT connection, callbacks, reconnect, and receiver
  transport.
- `mqtt/ntrip_pusher.py`: RTCM3 validation and NTRIP SOURCE fanout used by the
  MQTT transport, station command routes, and adjustment receiver flow.
- `mqtt/bridge/`: bridge composition. `sensor_pipeline/` separates payload
  parsing, GNSS adjustment, other sensors, broadcast, forwarding, alerts, and
  durable persistence.
- `mqtt/persistence/`: persistence mixins grouped into ingest buffering,
  GNSS audit records, alert/incident writes, and latest-sensor cache/baseline.
- `shared/`: access policy, pagination, and station policy shared by features.
- `infrastructure/`: scheduler, cleanup worker, and durable ingest spool.

## Processing layer

- `processors/gnss_processor.py` is the compatibility facade for the GNSS
  processor; `processors/gnss/` owns runtime state, reference transitions,
  velocity quality, origin persistence, payload processing, and NMEA helpers.
- `processors/imu_processor.py` and `water_processor.py`: sensor-specific
  processing engines.
- `processors/geodetic.py`: VN-2000/geodetic conversion.
- `processors/landslide_analyzer.py` is the compatibility facade for
  cross-sensor analysis; `processors/landslide/` owns velocity, rainfall,
  tilt, consensus, displacement, and alert analysis.

There are no `app/services`, `app/routers`, or `app/modules` dumping grounds;
there is no `base`, `generic`, or `registry` fallback layer. Tests live only
under `backend/tests/`. Every route must have one unique `(path, HTTP method)`
registration; `tests/test_app_composition.py` checks this contract.
