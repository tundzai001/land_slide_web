# Project map positions

The project point is stored in the configuration database, in the existing
`projects.location` JSON column. No new column or DDL migration is required.

```json
{"address":"Lào Cai","map_mode":"auto","lat":22.5,"lon":103.8}
```

Admins choose automatic or manual positioning in the create/edit project form.
Project POST/PUT accepts `map_position: {"mode":"auto"}` or
`map_position: {"mode":"manual","lat":22.5,"lon":103.8}`. The backend calculates
automatic positions; submitted automatic coordinates are rejected. Manual
coordinates must be finite JSON numbers within WGS84 bounds. `(0, 0)` is reserved
for an unknown location in this application.

Automatic coordinates average valid station locations, including stations outside
GNSS clusters. Station locations already represent the sensor origins associated
with each station. Station create, configuration edit, database edit, reassignment,
and delete refresh the automatic point within the same database transaction.
Manual coordinates remain fixed. An automatic project without valid station
coordinates stores null coordinates and has no map pin.

Startup backfills legacy project locations idempotently. Address strings become
objects with an `address` field; existing metadata and valid legacy coordinates
are preserved. Existing coordinates become manual points. Old clients sending
only an address cannot erase a point through the updated API. Existing readers
can continue reading the JSON column. Rolling back does not require deleting the
new JSON keys; restore the previous location JSON from a backup only if an older
client strictly requires strings. Avoid project edits through older backend
instances during a mixed-version rollout: those instances replace location JSON.

The map prefers the saved point, with a temporary centroid fallback for older API
responses. Clicking a pin flies to sensor bounds in 1.2 seconds; reduced-motion
users receive an immediate move. CORS bases stay enabled and become visible at
the project detail scale. Zooming out hides base and sensor markers again.

Project writes require the existing admin permission. Project lists respect
assigned project scope; non-admin responses omit base connection settings and
auto-adjustment configuration. Station configuration writes check operator scope.
Project card text is HTML-escaped; tooltip names use `textContent`.

Verification: `backend.tests.test_project_map_position` exercises real isolated
SQLite persistence and authenticated HTTP requests, including invalid coordinates,
legacy data, station changes, permission denial, and sensitive-field filtering.
Playwright project-map tests cover saved coordinates, animated/reduced-motion
zoom, CORS visibility, form validation, mobile layout, and stored HTML input.
These checks do not exercise a deployed database or a live PostgreSQL lock race.
