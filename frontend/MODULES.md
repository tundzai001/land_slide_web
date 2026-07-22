# Frontend module layout

The React CDN shell in `js/react-app.js` lazy-loads only the assets required by
the active route. Keep the listed order when adding modules because the legacy
features still share a global runtime while they are migrated incrementally.

## Map

- Entry: `js/map-main.js`
- Runtime and adjustment workflow: `js/map/runtime.js`
- WebSocket and realtime sensor UI: `js/map/realtime.js`
- Station/map layers: `js/map/stations.js`, `js/map/map-layers.js`
- User interactions: `js/map/map-interactions.js`
- Station details and charts: `js/map/station-detail.js`
- Long-term analysis and 3D: `js/map/long-term.js`, `js/map/analysis.js`
- Alerts and rescue: `js/map/marker-alerts.js`, `js/map/ui-alerts.js`,
  `js/map/guest-rescue.js`
- Optional tools: `js/map/tools.js`

Map styles live under `css/map/` in cascade order and are loaded by the SPA.

## Administration

- Entry: `js/admin-manager.js`
- Base class and feature composer: `js/admin/core.js`
- One feature per file under `js/admin/` (projects, stations, wizard, users,
  Pi devices, provisioning, and lifecycle)
- Final bootstrap: `js/admin/bootstrap.js`

Admin styles live under `css/admin/` in cascade order and are loaded by the SPA.

## Templates

Map and admin template partials live under `js/templates/map/` and
`js/templates/admin/`; their small route aggregators are `map-template.js` and
`admin-template.js`. The SPA owns the template registry.

Do not load feature files directly from HTML. Add them to the relevant manifest
in `js/react-app.js`, `js/map-main.js`, or `js/admin-manager.js` so loading,
cache-busting, and initialization order stay deterministic.
