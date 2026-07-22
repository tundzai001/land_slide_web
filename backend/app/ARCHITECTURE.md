# Backend module map

`main.py` is only the application composition root: process lifecycle,
middleware, router registration, and static mounts. Endpoint logic must not be
added there.

## HTTP layer

- `routers/authentication.py`: login and current-user session API.
- `routers/database_admin.py`: administrative database browser CRUD API.
- `routers/frontend.py`: HTML documents, health check, and WebSockets.
- `routers/rescue.py`: public rescue intake and the admin rescue workflow.
- `routers/gnss_adjustment.py`: GNSS adjustment start/status/stop workflow.
- `routers/devices.py`: administrative device CRUD for a station.
- `routers/cors_stations.py`: public CORS discovery, normalization, and cache.
- `routers/projects.py`: public/admin project APIs and CORS project settings.
- `routers/stations.py`: station lists, details, analysis, and GNSS summaries.
- `routers/field_provisioning.py`: legacy device provisioning/config/status API.
- `routers/admin.py`: remaining administrative features.
- `routers/field.py`: field-device enrollment and control API.

## Services and infrastructure

- `services/rescue_storage.py`: rescue metadata encoding and image storage.
- `services/station_policy.py`: shared station RBAC and offline thresholds.
- `services/access.py`: optional authentication and project visibility policy.
- `services/gnss_rollup.py`: daily/weekly GNSS aggregation daemon.
- `mqtt/transport.py`: MQTT callbacks, reconnect, and NTRIP route transport.
- `mqtt/persistence.py`: sensor buffers, alerts, cache, and heartbeat writes.
- `runtime.py`: process-wide analyzer and MQTT service instances.
- `middleware.py`: HTTP charset and versioned-asset cache policy.
- `logging_config.py`: process logging and console configuration.
- `auth.py`: authentication, authorization, and user cache.
- `database.py`: database engines and session providers.
- `config.py`: typed environment settings; deployment URLs/hosts belong in
  `backend/.env`, never in routers, processors, or `main.py`.

Every route must have one unique `(path, HTTP method)` registration. The
composition regression check in `test_app_composition.py` enforces this rule.
