const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const root = join(__dirname, '..', '..');
const source = file => readFileSync(join(root, file), 'utf8');
const css = [
  'frontend/css/theme-variables.css',
  'frontend/css/components.css',
  'frontend/css/admin/base.css',
  'frontend/css/admin/pi-devices.css',
  'frontend/css/admin/premium-light.css',
].map(source).join('\n');

async function mountManagement(page, width = 1366) {
  await page.setViewportSize({ width, height: 900 });
  await page.setContent(`<!doctype html><html data-app-view="admin"><head><style>${css}</style></head><body></body></html>`);
  await page.addScriptTag({ content: source('frontend/js/templates/admin/pi-devices.js') });
  await page.addScriptTag({ content: source('frontend/js/templates/admin/shell.js') });
  await page.evaluate(() => { document.body.innerHTML = window.LegacyTemplateParts.shell; });
}

test('station settings show the persisted GNSS tracking offset, not only the latest shift', async ({ page }) => {
  await page.setContent('<!doctype html><html><body></body></html>');
  await page.addScriptTag({ content: source('frontend/js/templates/admin/station-connectivity.js') });
  await page.evaluate(() => {
    document.body.innerHTML = window.LegacyTemplateParts['station-connectivity'];
    document.getElementById('mqtt-gnss-section').style.display = 'block';
  });
  await page.addScriptTag({ content: source('frontend/js/admin/core.js') });
  await page.addScriptTag({ content: source('frontend/js/admin/station-presets.js') });
  await page.evaluate(() => {
    window.adminManager = Object.create(window.AdminManager.prototype);
    window.adminManager.renderGnssTrackingOffset([0.00125, -0.0025, 3.49597667]);
  });

  await expect(page.locator('#gnss-offset-result')).toBeVisible();
  await expect(page.locator('#gnss-offset-state')).toHaveText('Đang áp dụng');
  await expect(page.locator('#gnss-offset-e')).toHaveText('1.250');
  await expect(page.locator('#gnss-offset-n')).toHaveText('-2.500');
  await expect(page.locator('#gnss-offset-u')).toHaveText('3495.977');
  await expect(page.locator('#gnss-offset-2d')).toHaveText('2.795');
});

test('GNSS calibration keeps waiting for realtime completion after a gateway 504', async ({ page }) => {
  await page.setContent('<!doctype html><html><body><button id="btn-reset-origin"></button><small id="origin-status"></small></body></html>');
  await page.addScriptTag({ content: source('frontend/js/admin/core.js') });
  await page.addScriptTag({ content: source('frontend/js/admin/station-presets.js') });
  await page.evaluate(() => {
    window.confirm = () => true;
    window.calibrationToasts = [];
    window.toast = {
      info: message => window.calibrationToasts.push({ type: 'info', message }),
      error: message => window.calibrationToasts.push({ type: 'error', message }),
    };
    window.fetch = async () => new Response('', { status: 504 });
    window.adminManager = Object.create(window.AdminManager.prototype);
    window.adminManager.token = 'test-token';
  });

  await page.evaluate(() => window.adminManager.resetGnssOrigin(7));

  await expect(page.locator('#btn-reset-origin')).toBeDisabled();
  await expect(page.locator('#origin-status')).toContainText('Gateway');
  const state = await page.evaluate(() => ({
    inProgress: window.adminManager._gnssCalibrationInProgress,
    toasts: window.calibrationToasts,
  }));
  expect(state.inProgress).toBe(true);
  expect(state.toasts.some(toast => toast.type === 'info')).toBe(true);
  expect(state.toasts.some(toast => toast.type === 'error')).toBe(false);
  await page.evaluate(() => { window.adminManager._gnssCalibrationInProgress = false; });
});

test('database explorer loads one paginated dataset and opens the inspector', async ({ page }) => {
  await mountManagement(page);
  await page.evaluate(() => {
    window.authSession = { getToken: () => 'test-token' };
    window.bootstrap = { Modal: class { show() {} hide() {} } };
    Object.defineProperty(window, 'localStorage', { value: { getItem: () => null, setItem() {}, removeItem() {} } });
    window.fetch = async url => {
      const target = String(url);
      if (target.includes('/stats')) return new Response(JSON.stringify({ stations: 12, devices: 12, sensor_data: 817874, sensor_data_estimated: true, alerts: 1 }), { status: 200 });
      if (target.includes('/api/admin/projects')) return new Response(JSON.stringify([{ id: 2, name: 'Sín Quyền' }]), { status: 200 });
      return new Response(JSON.stringify([{ id: 7, station_code: 'DAP-01', name: 'Đập 1', project_id: 2, status: 'offline', age_seconds: 3600, created_at: 1787100000 }]), { status: 200, headers: { 'X-Total-Count': '12' } });
    };
  });
  await page.addScriptTag({ content: source('frontend/js/db-manager.js') });
  await page.evaluate(() => { window.bootstrapDatabaseManager(); return window.dbManager.loadAllData(); });

  await expect(page.locator('#db-current-meta')).toContainText('12 bản ghi');
  await expect(page.locator('#stat-data')).toHaveText('≈817.874');
  await expect(page.locator('#db-table-body .db-row')).toHaveCount(1);
  await expect(page.locator('.db-dataset[data-dataset="simulations"]')).toHaveCount(0);
  await expect(page.locator('[data-tab="tab-simulations"]')).toHaveText('Mô phỏng');
  await expect(page.locator('#db-table-body .management-status')).toContainText('Offline');
  await expect(page.locator('#db-context-filters select')).toHaveCount(2);
  await page.locator('.db-dataset[data-dataset="devices"]').click();
  await expect(page.locator('#db-context-filters select')).toHaveCount(3);
  await page.locator('.db-dataset[data-dataset="sensor_data"]').click();
  await expect(page.locator('#db-context-filters select')).toHaveCount(2);
  const sensorTypeValues = await page.locator('#db-context-filters select').nth(1).locator('option').evaluateAll(options => options.map(option => option.value));
  expect(sensorTypeValues).toEqual(['', 'gnss', 'imu', 'rain', 'water']);
  await page.locator('.db-dataset[data-dataset="alerts"]').click();
  await expect(page.locator('#db-context-filters select')).toHaveCount(3);
  await page.locator('.db-dataset[data-dataset="stations"]').click();
  await page.locator('#db-table-body .db-row').click();
  await expect(page.locator('#db-inspector')).toHaveClass(/open/);
  await expect(page.locator('#db-inspector-content')).toContainText('DAP-01');
  await expect(page.locator('#db-page-next')).toBeDisabled();
});

test('database explorer prefetches the next 100-row page', async ({ page }) => {
  await mountManagement(page);
  await page.evaluate(() => {
    window.authSession = { getToken: () => 'test-token' };
    window.bootstrap = { Modal: class { show() {} hide() {} } };
    Object.defineProperty(window, 'localStorage', { value: { getItem: () => null, setItem() {}, removeItem() {} } });
    window.datasetPageRequests = 0;
    window.fetch = async url => {
      const target = String(url);
      if (target.includes('/stats')) return new Response('{}', { status: 200 });
      if (target.includes('/api/admin/projects') || target.includes('summary_only=true')) return new Response('[]', { status: 200 });
      window.datasetPageRequests += 1;
      const offset = Number(new URL(target, 'https://test.local').searchParams.get('offset') || 0);
      return new Response(JSON.stringify([{ id: offset + 1, station_code: `DAP-${offset + 1}`, name: `Trạm ${offset + 1}`, status: 'online' }]), {
        status: 200,
        headers: { 'X-Total-Count': '200' },
      });
    };
  });
  await page.addScriptTag({ content: source('frontend/js/db-manager.js') });
  await page.evaluate(() => { window.bootstrapDatabaseManager(); return window.dbManager.loadAllData(); });

  await expect.poll(() => page.evaluate(() => window.datasetPageRequests)).toBe(2);
  await page.locator('#db-page-next').click();
  await expect(page.locator('#db-table-body')).toContainText('DAP-101');
  expect(await page.evaluate(() => window.datasetPageRequests)).toBe(2);
});

test('sensor pages load lightweight rows and GNSS details open as a downloadable table', async ({ page }) => {
  await mountManagement(page);
  await page.evaluate(() => {
    window.authSession = { getToken: () => 'test-token' };
    window.bootstrap = { Modal: class { show() {} hide() {} } };
    Object.defineProperty(window, 'localStorage', { value: { getItem: () => null, setItem() {}, removeItem() {} } });
    window.downloadAuthenticatedFile = async url => { window.downloadedAdjustmentUrl = url; };
    window.fetch = async url => {
      const target = String(url);
      if (target.includes('/api/admin/projects')) return new Response('[]', { status: 200 });
      if (target.includes('/api/admin/db/stations?sort=station_code')) return new Response('[]', { status: 200 });
      if (target.includes('/stats')) return new Response(JSON.stringify({ sensor_data: 864872, gnss_adjustments: 196 }), { status: 200 });
      if (target.endsWith('/api/admin/db/sensor-data/77')) {
        return new Response(JSON.stringify({
          id: 77,
          station_id: 7,
          timestamp: 1787419040,
          sensor_type: 'gnss_adjusted',
          data: {
            type: 'gnss_adjusted',
            project_code: 'SQ-2026',
            cluster_name: 'Cụm Bắc',
            quality_gate: { passed: true },
            points: {
              ROVER_07: { station_id: 7, adjusted_x: 123.4567, adjusted_y: 234.5678, adjusted_z: 345.6789, dx: 0.0012, dy: -0.0023, dz: 0.0034 },
            },
            audit_json_url: '/api/admin/gnss/adjustment/reports/2/result.json',
            excel_report_url: '/api/admin/gnss/adjustment/reports/2/result.xlsx',
          },
        }), { status: 200 });
      }
      if (target.includes('/api/admin/db/sensor-data?')) {
        window.sensorListUrl = target;
        return new Response(JSON.stringify([{
          id: 77,
          station_id: 7,
          timestamp: 1787419040,
          sensor_type: 'gnss_adjusted',
          data_preview: '{"type":"gnss_adjusted","project_code":"SQ-2026"}',
        }]), { status: 200, headers: { 'X-Has-More': 'false' } });
      }
      return new Response('[]', { status: 200, headers: { 'X-Total-Count': '0' } });
    };
  });
  await page.addScriptTag({ content: source('frontend/js/db-manager.js') });
  await page.locator('.db-dataset[data-dataset="gnss_adjustments"]').click();

  await expect(page.locator('#db-table-body .db-row')).toHaveCount(1);
  const listUrl = await page.evaluate(() => window.sensorListUrl);
  expect(listUrl).toContain('include_total=false');
  expect(listUrl).toContain('include_data=false');
  expect(listUrl).toContain('include_internal=true');
  await expect(page.locator('#db-current-meta')).toContainText('tải nhanh');

  await page.locator('#db-table-body .db-row').click();
  await expect(page.locator('.adjustment-result-table tbody tr')).toHaveCount(1);
  await expect(page.locator('.adjustment-result-table')).toContainText('ROVER_07');
  await expect(page.locator('#db-inspector-actions')).toContainText('Tải JSON');
  await expect(page.locator('#db-inspector-actions')).toContainText('Tải XLSX');

  await page.getByRole('button', { name: 'Tải JSON' }).click();
  await expect.poll(() => page.evaluate(() => window.downloadedAdjustmentUrl)).toBe('/api/admin/gnss/adjustment/reports/2/result.json');
});

test('dark theme applies one semantic surface across the data workspace', async ({ page }) => {
  await mountManagement(page);
  await page.evaluate(() => {
    document.documentElement.dataset.theme = 'dark';
    document.querySelector('#pi-grid-body').innerHTML = '<article class="pi-device-row"><span class="pi-device-status is-pending">Chờ kích hoạt</span></article>';
  });
  await page.waitForTimeout(350);
  const colors = await page.evaluate(() => {
    const style = getComputedStyle(document.documentElement);
    const surface = style.getPropertyValue('--admin-surface').trim();
    const muted = style.getPropertyValue('--admin-surface-muted').trim();
    const rgb = value => {
      const probe = document.createElement('div');
      probe.style.color = value;
      document.body.appendChild(probe);
      const result = getComputedStyle(probe).color;
      probe.remove();
      return result;
    };
    return {
      surface: rgb(surface),
      muted: rgb(muted),
      kpi: getComputedStyle(document.querySelector('#tab-database .ops-kpi')).backgroundColor,
      explorer: getComputedStyle(document.querySelector('.db-explorer')).backgroundColor,
      rail: getComputedStyle(document.querySelector('.db-dataset-rail')).backgroundColor,
      toolbar: getComputedStyle(document.querySelector('.db-toolbar')).backgroundColor,
      piList: getComputedStyle(document.querySelector('.pi-list-head')).backgroundColor,
      piRow: getComputedStyle(document.querySelector('.pi-device-row')).backgroundColor,
      piStatus: getComputedStyle(document.querySelector('.pi-device-status')).backgroundColor,
    };
  });
  expect(colors.kpi).toBe(colors.surface);
  expect(colors.explorer).toBe(colors.surface);
  expect(colors.toolbar).toBe(colors.surface);
  expect(colors.rail).toBe(colors.muted);
  expect(colors.piList).toBe(colors.muted);
  expect(colors.piRow).toBe(colors.surface);
  expect(colors.piStatus).not.toBe('rgb(255, 245, 215)');
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
