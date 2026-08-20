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
  'frontend/css/admin/pi-devices.css',
].map(source).join('\n');

async function mountManagement(page, width = 1366) {
  await page.setViewportSize({ width, height: 900 });
  await page.setContent(`<!doctype html><html data-app-view="admin"><head><style>${css}</style></head><body></body></html>`);
  await page.addScriptTag({ content: source('frontend/js/templates/admin/pi-devices.js') });
  await page.addScriptTag({ content: source('frontend/js/templates/admin/shell.js') });
  await page.evaluate(() => { document.body.innerHTML = window.LegacyTemplateParts.shell; });
}

test('database explorer loads one paginated dataset and opens the inspector', async ({ page }) => {
  await mountManagement(page);
  await page.evaluate(() => {
    window.authSession = { getToken: () => 'test-token' };
    window.bootstrap = { Modal: class { show() {} hide() {} } };
    Object.defineProperty(window, 'localStorage', { value: { getItem: () => null, setItem() {}, removeItem() {} } });
    window.fetch = async url => {
      const target = String(url);
      if (target.includes('/stats')) return new Response(JSON.stringify({ stations: 12, devices: 12, sensor_data: 817874, alerts: 1 }), { status: 200 });
      if (target.includes('/api/admin/projects')) return new Response(JSON.stringify([{ id: 2, name: 'Sín Quyền' }]), { status: 200 });
      return new Response(JSON.stringify([{ id: 7, station_code: 'DAP-01', name: 'Đập 1', project_id: 2, status: 'offline', age_seconds: 3600, created_at: 1787100000 }]), { status: 200, headers: { 'X-Total-Count': '12' } });
    };
  });
  await page.addScriptTag({ content: source('frontend/js/db-manager.js') });
  await page.evaluate(() => { window.bootstrapDatabaseManager(); return window.dbManager.loadAllData(); });

  await expect(page.locator('#db-current-meta')).toContainText('12 bản ghi');
  await expect(page.locator('#db-table-body .db-row')).toHaveCount(1);
  await expect(page.locator('#db-table-body .management-status')).toContainText('Offline');
  await expect(page.locator('#db-context-filters select')).toHaveCount(2);
  await page.locator('.db-dataset[data-dataset="devices"]').click();
  await expect(page.locator('#db-context-filters select')).toHaveCount(3);
  await page.locator('.db-dataset[data-dataset="sensor_data"]').click();
  await expect(page.locator('#db-context-filters select')).toHaveCount(2);
  await page.locator('.db-dataset[data-dataset="alerts"]').click();
  await expect(page.locator('#db-context-filters select')).toHaveCount(3);
  await page.locator('.db-dataset[data-dataset="stations"]').click();
  await page.locator('#db-table-body .db-row').click();
  await expect(page.locator('#db-inspector')).toHaveClass(/open/);
  await expect(page.locator('#db-inspector-content')).toContainText('DAP-01');
  await expect(page.locator('#db-page-next')).toBeDisabled();
});

test('user management filters and edits account configuration', async ({ page }) => {
  await mountManagement(page);
  await page.addScriptTag({ content: source('frontend/js/templates/admin/gnss-project-modals.js') });
  await page.evaluate(() => { document.body.insertAdjacentHTML('beforeend', window.LegacyTemplateParts['gnss-project-modals']); });
  await page.addScriptTag({ content: source('frontend/js/admin/core.js') });
  await page.addScriptTag({ content: source('frontend/js/admin/users.js') });
  await page.evaluate(() => {
    window.bootstrap = { Modal: class { static getOrCreateInstance() { return new this(); } static getInstance() { return new this(); } show() {} hide() {} } };
    window.adminManager = Object.create(window.AdminManager.prototype);
    window.adminManager.token = 'test-token';
    window.adminManager.getProjectName = projectId => projectId === 2 ? 'Sín Quyền' : `#${projectId}`;
    window.adminManager.usersData = [{ id: 4, username: 'operator1', full_name: 'Vận hành', role: 'operator', is_active: true, assigned_projects: [2] }];
    window.fetch = async url => String(url).includes('/projects')
      ? new Response(JSON.stringify([{ id: 2, name: 'Sín Quyền', project_code: 'SQ-2026' }]), { status: 200 })
      : new Response(JSON.stringify(window.adminManager.usersData), { status: 200 });
    window.adminManager.renderUsers(window.adminManager.usersData);
  });

  await expect(page.locator('#user-search')).toBeVisible();
  await expect(page.locator('#user-role-filter')).toBeVisible();
  await expect(page.locator('#user-status-filter')).toBeVisible();
  await page.locator('button[title="Sửa cấu hình"]').click();
  await expect(page.locator('#edit-user-username')).toHaveValue('operator1');
  await expect(page.locator('#edit-user-role')).toHaveValue('operator');
  await expect(page.locator('#edit-user-projects input[value="2"]')).toBeChecked();
  const checkboxSize = await page.locator('#edit-user-projects input[value="2"]').evaluate(element => ({ width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height }));
  expect(checkboxSize).toEqual({ width: 18, height: 18 });
});

test('Pi Devices is localized, filterable and responsive', async ({ page }) => {
  await mountManagement(page);
  await page.addScriptTag({ content: source('frontend/js/admin/core.js') });
  await page.addScriptTag({ content: source('frontend/js/admin/pi-devices.js') });
  await page.addScriptTag({ content: source('frontend/js/admin/pi-device-actions.js') });
  await page.evaluate(() => {
    window.adminManager = Object.create(window.AdminManager.prototype);
    window.adminManager.token = 'test-token';
    window.adminManager.currentUserRole = 'admin';
    const now = Math.floor(Date.now() / 1000);
    const devices = [
      { id: 1, name: 'Pi trung tâm 01', serial: 'pi-001', device_type: 'pi', status: 'assigned', station_name: 'Đập 1', project_name: 'Sín Quyền', last_seen: now - 7200, pi_center_id: null, is_locked: false },
      { id: 2, name: 'Điểm hiện trường 01', serial: 'point-001', device_type: 'pi_point', status: 'activated', last_seen: now - 20, pi_center_id: null, is_locked: false },
    ];
    window.adminManager._piDevicesData = devices;
    window.adminManager._updatePiSummary(devices);
    window.adminManager._renderPiGrid(devices);
    window.adminManager._ensurePiActionBar();
    window.piFetchCount = 0;
    window.fetch = async () => {
      window.piFetchCount += 1;
      return new Response(JSON.stringify(devices), { status: 200 });
    };
  });

  await expect(page.locator('#tab-pi')).toContainText('Quản lý thiết bị Pi');
  await expect(page.locator('.pi-grid-row')).toHaveCount(2);
  await page.locator('[data-tab="tab-pi"]').click();
  await expect.poll(() => page.evaluate(() => window.piFetchCount)).toBe(1);
  await expect(page.locator('#pi-sync-button')).toBeEnabled();
  await expect(page.locator('#pi-sync-button')).toHaveText('Đồng bộ');
  await expect(page.locator('.pi-device-list')).not.toContainText('â—');
  await expect(page.locator('.pi-device-list')).not.toContainText('â€”');
  await expect(page.locator('.pi-connection.is-offline')).toContainText('Mất kết nối');
  await page.locator('#pi-status-filter').selectOption('online');
  await expect(page.locator('.pi-grid-row:visible')).toHaveCount(1);
  await page.locator('#pi-select-toggle').click();
  const piCheckboxSize = await page.locator('.pi-grid-row:visible .pi-checkbox').evaluate(element => ({ width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height }));
  expect(piCheckboxSize).toEqual({ width: 18, height: 18 });
  await page.setViewportSize({ width: 375, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
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
