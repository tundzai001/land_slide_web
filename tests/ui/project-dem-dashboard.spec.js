const { test, expect } = require('./coverage-fixture');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

test('project dashboard zooms to the project and switches between terrain models', async ({ page }) => {
  const source = file => readFileSync(join(__dirname, '../..', file), 'utf8');
  await page.setViewportSize({ width: 1100, height: 800 });
  await page.setContent('<main id="map" style="width:100%;height:100%"></main>');
  await page.addStyleTag({ content: '.project-dashboard-panel{position:fixed;inset:20px 20px 20px auto;width:520px;background:#fff}.project-dashboard-content{height:calc(100% - 80px);overflow:auto}.dem-grid-viewport{width:100%;height:240px;background:#0f252c}.dem-grid-viewport canvas{width:100%;height:100%;display:block}' });
  await page.addScriptTag({ content: source('frontend/js/dem-grid.js') });
  await page.addScriptTag({ content: source('frontend/js/map/stations.js') });
  await page.evaluate(() => {
    window.DemGrid.mount = async () => ({ destroy() {}, fit() {} });
    const center = { lat: 22.6, lng: 103.8 };
    const map = {
      getCenter: () => center,
      getZoom: () => 14,
      panBy() {},
      once() {},
      flyTo() {},
      setView() {},
    };
    window.getLeafletMap = () => map;
    window.allStations = [{ id: 1, project_id: 4 }, { id: 2, project_id: 4 }];
    window.setStationListSidebarOpen = () => {};
    window.setDetailSidebarOpen = () => {};
    window.setGnssAdvancedPanelOpen = () => {};
    window.setChartsPanelOpen = () => {};
    window.matchMedia = () => ({ matches: true });
    window.demRequests = [];
    window.fetch = async url => {
      window.demRequests.push(url);
      return new Response('ncols 2\nnrows 2\nxllcorner 454959.202\nyllcorner 2326094.284\ncellsize 1\nNODATA_value -9999\n100 101\n98 99', { status: 200 });
    };
  });

  await page.evaluate(async () => {
    await window.openProjectDashboard({
      id: 4,
      name: 'Dự án Sín Quyền',
      location: { lat: 22.6, lon: 103.8 },
      dems: [{ id: 'dam-grid', name: 'Thân đập' }, { id: 'mine-grid', name: 'Bờ mỏ' }],
    }, [22.6, 103.8], document.createElement('button'));
  });

  await expect(page.locator('#project-dashboard')).toHaveClass(/is-open/);
  await expect(page.locator('#project-dashboard-name')).toHaveText('Dự án Sín Quyền');
  await expect(page.locator('#project-dashboard-dem-select')).toBeVisible();
  await expect(page.locator('#project-dashboard-status')).toContainText('2 × 2 ô');
  await page.locator('#project-dashboard-dem-select').selectOption('mine-grid');
  await expect(page.locator('#project-dashboard-terrain-description')).toContainText('Bờ mỏ');
  await expect.poll(() => page.evaluate(() => window.demRequests.length)).toBe(2);
  await page.keyboard.press('Escape');
  await expect(page.locator('#project-dashboard')).toHaveAttribute('aria-hidden', 'true');
});

test('project without DEM keeps the old map zoom behavior and opens no empty panel', async ({ page }) => {
  const source = file => readFileSync(join(__dirname, '../..', file), 'utf8');
  await page.setContent('<main id="map"></main>');
  await page.addScriptTag({ content: source('frontend/js/map/stations.js') });
  await page.evaluate(() => {
    const handlers = {};
    const marker = {
      bindTooltip() { return this; },
      on(name, callback) { handlers[name] = callback; return this; },
      getElement() { return document.createElement('button'); },
    };
    const map = {
      getSize: () => ({ x: 1000, y: 700 }),
      getContainer: () => ({ getBoundingClientRect: () => ({ top: 0, bottom: 700 }) }),
      flyToBounds(bounds, options) { window.zoomCall = { bounds, options }; },
    };
    window.L = {
      marker: () => marker,
      divIcon: () => ({}),
      latLngBounds: points => ({ points }),
    };
    window.getLeafletMap = () => map;
    window.allStations = [
      { id: 1, project_id: 12, name: 'CP02', location: { lat: 21.1, lon: 107.2 } },
      { id: 2, project_id: 12, name: 'CP06', location: { lat: 21.2, lon: 107.3 } },
    ];
    window.matchMedia = () => ({ matches: true });
    window.projectMarkerHandlers = handlers;
  });
  await page.evaluate(() => {
    window.createProjectMapGroup({ id: 12, name: 'Mông Dương', location: { lat: 21.15, lon: 107.25 } });
    window.projectMarkerHandlers.click();
  });
  await expect.poll(() => page.evaluate(() => window.zoomCall?.bounds.points.length)).toBe(2);
  await expect(page.locator('#project-dashboard')).toHaveCount(0);
});

test('DEM upload explains an upstream 413 with the file details', async ({ page }) => {
  const source = file => readFileSync(join(__dirname, '../..', file), 'utf8');
  await page.setContent('<input id="project-dem-name" value="Thân đập"><p id="management-dem-selection" role="status"></p><div id="action-buttons-container"><button onclick=""></button></div>');
  await page.evaluate(() => {
    window.AdminManager = class {};
    window.applyAdminFeature = Feature => { window.AdminStationsFeature = Feature; };
    window.toast = { error: message => { window.lastToast = message; } };
    window.fetch = async () => new Response('<html>Content Too Large</html>', {
      status: 413,
      headers: { 'Content-Type': 'text/html' },
    });
  });
  await page.addScriptTag({ content: source('frontend/js/admin/stations.js') });
  await page.evaluate(async () => {
    const manager = Object.assign(Object.create(window.AdminStationsFeature.prototype), {
      currentProjectId: 6,
      token: 'test-token',
      projectsData: [],
      renderStations() {},
    });
    await manager.uploadProjectDem(new File(['dem'], 'site.asc', { type: 'text/plain' }));
  });
  await expect(page.locator('#management-dem-selection')).toContainText('site.asc (0.0 MiB)');
  await expect(page.locator('#management-dem-selection')).toContainText('IIS hoặc proxy');
  await expect.poll(() => page.evaluate(() => window.lastToast)).toContain('HTTP 413');
});

test('project overview hides empty DEM block, formats non-redundant stations, and clears fresh disconnect banner', async ({ page }) => {
  const source = file => readFileSync(join(__dirname, '../..', file), 'utf8');
  await page.setContent(`
    <main id="map" style="width:100%;height:100%"></main>
    <div id="st-stale-info" class="stale-info" style="display:none"></div>
  `);
  await page.addScriptTag({ content: source('frontend/js/dem-grid.js') });
  await page.addScriptTag({ content: source('frontend/js/map/analysis.js') });
  await page.addScriptTag({ content: source('frontend/js/map/stations.js') });
  await page.evaluate(() => {
    window.DemGrid.mount = async () => ({ destroy() {}, fit() {} });
    const center = { lat: 21.05, lng: 107.32 };
    window.getLeafletMap = () => ({
      getCenter: () => center,
      getZoom: () => 14,
      panBy() {},
      once() {},
      flyTo() {},
      setView() {},
    });
    window.allStations = [
      { id: 101, project_id: 20, station_code: 'CP03', name: 'CP03', status: 'online', sensor_types: ['gnss'] },
      { id: 102, project_id: 20, station_code: 'Dap1_1', name: 'Đập 1 số 1', status: 'offline', sensor_types: ['gnss', 'imu'] }
    ];
    window.matchMedia = () => ({ matches: true });
  });

  await page.evaluate(async () => {
    await window.openProjectDashboard({
      id: 20,
      name: 'Mông Dương',
      location: { lat: 21.05, lon: 107.32 },
      dems: [] // No DEM
    }, [21.05, 107.32], document.createElement('button'));
  });

  // 1. Empty DEM block must be hidden
  await expect(page.locator('#project-dashboard-terrain')).toBeHidden();

  // 2. Station list must not duplicate name when station_code === name
  const cp03Item = page.locator('.project-station-item[data-station-id="101"]');
  await expect(cp03Item).toContainText('CP03');
  await expect(cp03Item.locator('.station-name-sub')).toHaveCount(0);

  // But station with different name must display the distinct name
  const dapItem = page.locator('.project-station-item[data-station-id="102"]');
  await expect(dapItem.locator('.station-name-sub')).toHaveText('Đập 1 số 1');

  // 3. Stale banner logic: fresh data clears/hides stale banner
  const now = Math.floor(Date.now() / 1000);
  await page.evaluate(({ nowTs }) => {
    // If data timestamp is 2s ago (< 60s) and station is online, banner must be hidden
    window.renderStaleInfo({ status: 'online' }, false, nowTs - 2);
  }, { nowTs: now });
  await expect(page.locator('#st-stale-info')).toBeHidden();

  // If data timestamp is old (300s ago), banner must be shown
  await page.evaluate(({ nowTs }) => {
    window.renderStaleInfo({ status: 'online' }, false, nowTs - 300);
  }, { nowTs: now });
  await expect(page.locator('#st-stale-info')).toBeVisible();
  await expect(page.locator('#st-stale-info')).toContainText('MẤT KẾT NỐI');
});
