const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

test('map and management ship without the incident inbox or its background connection', () => {
  for (const asset of ['shared.min.js', 'map-app.min.js', 'admin-app.min.js', 'map.min.css', 'admin.min.css']) {
    const content = readFileSync(join(__dirname, '..', '..', 'frontend', 'dist', asset), 'utf8');
    for (const removed of ['incident-inbox', 'admin-incident-inbox', 'incident-toggle', '/api/incidents', '/ws/operations', 'incidentsRealtime']) {
      expect(content, `${asset} still contains ${removed}`).not.toContain(removed);
    }
  }
});
