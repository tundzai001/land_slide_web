const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const root = join(__dirname, '..', '..');
const source = file => readFileSync(join(root, file), 'utf8');
const css = [
  'frontend/css/theme-variables.css',
  'frontend/css/components.css',
  'frontend/css/admin/base.css',
  'frontend/css/admin/premium-light.css',
].map(source).join('\n');

async function mountManagement(page, width = 1366) {
  await page.setViewportSize({ width, height: 900 });
  await page.setContent(`<!doctype html><html data-app-view="admin"><head><style>${css}</style></head><body></body></html>`);
  await page.addScriptTag({ content: source('frontend/js/templates/admin/shell.js') });
  await page.evaluate(() => { document.body.innerHTML = window.LegacyTemplateParts.shell; });
}

test('database explorer loads one paginated dataset and opens the inspector', async ({ page }) => {
  await mountManagement(page);
  await page.evaluate(() => {
    window.authSession = { getToken: () => 'test-token' };
    window.bootstrap = { Modal: class { show() {} hide() {} } };
    Object.defineProperty(window, 'localStorage', { value: { getItem: () => null, setItem() {}, removeItem() {} } });
    window.fetch = async url => String(url).includes('/stats')
      ? new Response(JSON.stringify({ stations: 12, devices: 12, sensor_data: 817874, alerts: 1 }), { status: 200 })
      : new Response(JSON.stringify([{ id: 7, station_code: 'DAP-01', name: 'Đập 1', project_id: 2, status: 'online', created_at: 1787100000 }]), { status: 200, headers: { 'X-Total-Count': '12' } });
  });
  await page.addScriptTag({ content: source('frontend/js/db-manager.js') });
  await page.evaluate(() => { window.bootstrapDatabaseManager(); return window.dbManager.loadAllData(); });

  await expect(page.locator('#db-current-meta')).toContainText('12 bản ghi');
  await expect(page.locator('#db-table-body .db-row')).toHaveCount(1);
  await page.locator('#db-table-body .db-row').click();
  await expect(page.locator('#db-inspector')).toHaveClass(/open/);
  await expect(page.locator('#db-inspector-content')).toContainText('DAP-01');
  await expect(page.locator('#db-page-next')).toBeDisabled();
});

test('rescue queue prioritizes pending cases and becomes a bottom sheet on mobile', async ({ page }) => {
  await mountManagement(page, 375);
  await page.addScriptTag({ content: source('frontend/js/admin/core.js') });
  await page.evaluate(() => {
    window.adminManager = Object.create(window.AdminManager.prototype);
    window.adminManager.rescueState = { status: 'pending', offset: 0, limit: 25, total: 1, rows: [] };
    const row = {
      id: 9, created_at: Math.floor(Date.now() / 1000) - 3600, requester_name: 'Nguyễn Văn A',
      phone: '0900000000', message: 'Cần hỗ trợ khẩn cấp', latitude: 21.5, longitude: 104.5,
      accuracy_m: 8, status: 'pending', rescue_type: 'can_cuu_ho', province_city: 'Lào Cai',
    };
    window.adminManager.rescueState.rows = [row];
    window.adminManager.renderRescueRequests([row]);
  });

  await expect(page.locator('.rescue-case')).toHaveClass(/is-critical/);
  await page.locator('.rescue-case').click();
  await expect(page.locator('#rescue-inspector')).toHaveClass(/open/);
  await expect(page.locator('#rescue-inspector-content')).toContainText('Nguyễn Văn A');
  const drawer = await page.locator('#rescue-inspector').evaluate(el => ({
    width: el.getBoundingClientRect().width,
    bottom: getComputedStyle(el).bottom,
  }));
  expect(drawer.width).toBeLessThanOrEqual(375);
  expect(drawer.bottom).toBe('0px');
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
});
