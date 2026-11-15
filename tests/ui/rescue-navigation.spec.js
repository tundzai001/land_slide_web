const { test, expect } = require('./coverage-fixture');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const runtime = readFileSync(join(__dirname, '../../frontend/js/app-runtime.js'), 'utf8');
const adminCore = readFileSync(join(__dirname, '../../frontend/js/admin/core.js'), 'utf8');
const mapHtml = `<label class="layer-toggle-switch"><input id="layer-mode-toggle"><span>Cứu hộ</span></label>
  <fieldset><label><input id="layer-rescue">Cứu hộ</label><label><input id="layer-heatmap">Heatmap trạng thái trạm</label></fieldset>
  <button data-map-action="rescue">Cứu hộ</button><button id="btn-guest-rescue">Yêu cầu cứu hộ</button><div id="guestRescueModal"></div>`;
const adminHtml = `<nav><div class="nav-item"><a data-tab="tab-rescue">Cứu hộ</a></div></nav>
  <div id="admin-tab-content"><div id="tab-rescue">Yêu cầu cứu hộ</div></div><div id="mobile-bottom-nav"></div>`;

async function mount(page, view, enabled) {
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/public/rescue-config') return route.fulfill({ json: { enabled } });
    if (url.pathname.endsWith('/shared.min.js')) return route.fulfill({ contentType: 'application/javascript', body: 'window.authManager={updateAuthUI(){},openSessions(){}};' });
    if (url.pathname.endsWith('/map-app.min.js')) return route.fulfill({ contentType: 'application/javascript', body: `window.LegacyTemplates={map:${JSON.stringify(mapHtml)}};window.flushMapReadyQueue=()=>{};` });
    if (url.pathname.endsWith('/admin-app.min.js')) return route.fulfill({ contentType: 'application/javascript', body: `window.LegacyTemplates={admin:${JSON.stringify(adminHtml)}};window.bootstrapAdminManager=async()=>{};` });
    if (url.pathname.endsWith('.css')) return route.fulfill({ contentType: 'text/css', body: '' });
    if (url.pathname.endsWith('.js')) return route.fulfill({ contentType: 'application/javascript', body: '' });
    return route.fulfill({ contentType: 'text/html', body: '<!doctype html><html><body><div id="app-root"></div></body></html>' });
  });
  await page.goto(`https://feature.test/${view === 'admin' ? 'management' : 'map'}`);
  await page.evaluate(() => { window.authSession = { inspect: async () => ({ status: 'authenticated' }) }; });
  await page.addScriptTag({ content: runtime });
  await expect.poll(() => page.evaluate(() => window.rescueFeatureEnabled)).toBe(enabled);
}

for (const enabled of [false, true]) {
  test(`rescue ${enabled ? 'enabled' : 'disabled'} across map and management`, async ({ page }) => {
    await mount(page, 'map', enabled);
    await expect(page.locator('.layer-toggle-switch')).toHaveCount(enabled ? 1 : 0);
    await expect(page.locator('#layer-rescue')).toHaveCount(enabled ? 1 : 0);
    await expect(page.locator('#layer-heatmap')).toHaveCount(1);
    await expect(page.locator('[data-map-action="rescue"]')).toHaveCount(enabled ? 1 : 0);
    await expect(page.locator('#guestRescueModal')).toHaveCount(enabled ? 1 : 0);
  });
  test(`rescue ${enabled ? 'enabled' : 'disabled'} in management navigation`, async ({ page }) => {
    await mount(page, 'admin', enabled);
    await expect(page.locator('.nav-item [data-tab="tab-rescue"]')).toHaveCount(enabled ? 1 : 0);
    await expect(page.locator('#mobile-bottom-nav [data-tab="tab-rescue"]')).toHaveCount(enabled ? 1 : 0);
    await expect(page.locator('#tab-rescue')).toHaveCount(enabled ? 1 : 0);
    await page.addScriptTag({ content: adminCore });
    expect(await page.evaluate(() => {
      const manager = Object.create(window.AdminManager.prototype);
      manager.currentUserRole = 'admin';
      return manager.canAccessTab('tab-rescue');
    })).toBe(enabled);
  });
}
