const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const incidentsSource = readFileSync(
  join(__dirname, '..', '..', 'frontend/js/map/incidents.js'),
  'utf8',
);

test('operations inbox stays outside Leaflet pane stacking', async ({ page }) => {
  await page.setContent(`<!doctype html><html data-app-view="map"><body>
    <div id="app-root"><div id="map"><div class="leaflet-tile-pane"></div></div></div>
  </body></html>`);
  await page.evaluate(() => {
    window.authManager = {
      isAuthenticated: () => true,
      getUserInfo: () => ({ role: 'viewer' }),
      apiFetch: async () => ({ ok: true, json: async () => ({ items: [] }) }),
    };
  });
  await page.addScriptTag({ content: incidentsSource });

  const inbox = page.locator('#incident-inbox');
  await expect(inbox).toBeVisible();
  expect(await inbox.evaluate(node => node.parentElement?.id)).toBe('app-root');
  await expect(page.locator('#map > #incident-inbox')).toHaveCount(0);
});
