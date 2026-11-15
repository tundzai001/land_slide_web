const { test, expect } = require('./coverage-fixture');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const source = file => readFileSync(join(__dirname, '../..', file), 'utf8');

for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test(`project centroid, tooltip and sensor fit at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: viewport.width < 900 ? 'reduce' : 'no-preference' });
    await page.setContent(`<html data-theme="light"><body>
      <div id="map" style="position:fixed;inset:0"></div>
      <nav class="top-navbar" style="position:fixed;height:60px;z-index:1000">Quan trắc</nav>
      <div style="position:fixed;top:100px;left:12px;z-index:2000">
        <input type="checkbox" id="layer-station" checked>
        <input type="checkbox" id="layer-cors"><input type="checkbox" id="layer-rescue" checked>
      </div>
      <nav id="map-bottom-nav" style="display:${viewport.width < 900 ? 'block' : 'none'};position:fixed;bottom:0;height:64px;z-index:1000">Trạm · Lớp bản đồ</nav>
    </body></html>`);
    await page.addStyleTag(process.env.LEAFLET_TEST_CSS
      ? { path: process.env.LEAFLET_TEST_CSS }
      : { url: 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css' });
    await page.addStyleTag({ content: source('frontend/css/theme-variables.css') + source('frontend/css/map/map-interface.css') });
    await page.addScriptTag(process.env.LEAFLET_TEST_JS
      ? { path: process.env.LEAFLET_TEST_JS }
      : { url: 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js' });
    await page.evaluate(() => {
      Object.assign(window, {
        markers: {}, allStations: [], clusterPolylines: [], clusterRenderSignature: '',
        showStationMarkers: true, showRescueMarkers: true, showCorsBaseMarkers: true, projectDetailsVisible: false,
        corsBaseMarkers: {}, rescueMarkers: {}, stationClusterGroup: null, currentTileLayer: null,
        mapInteractionActive: false, mapInteractionDepth: 0, projectsFetchInFlight: false,
        pendingProjectsReload: false, pendingStationsReload: false, pendingRescueMarkersReload: false, pendingCorsBaseReload: false,
        beginMapInteraction() {}, endMapInteraction() {}, setMapState() {},
        setStationListSidebarOpen() {}, setDetailSidebarOpen() {}, setGnssAdvancedPanelOpen() {}, setChartsPanelOpen() {},
        toggleRescueMarkersDisplay() {}, normalizeRiskLevel: () => 'LOW',
        TILE_URLS: { light: '' }, TILE_OPTIONS: { light: {} },
        MAP_BASEMAPS: {hybrid:{url:'',label:'Vệ tinh có nhãn'}}, activeBasemap:'hybrid',
        getLeafletMap: () => window.map,
      });
      window.projects = [{ id: 7, name: 'Mỏ <Sin Quyền>', location: { map_mode: 'manual', lat: 22.45, lon: 103.9 }, gnss_clusters: [{ stations: [1, 2, 3] }] }, { id: 8, name: 'Dự án một trạm' }];
      window.fetch = async () => ({ ok: true, json: async () => window.projects });
    });
    await page.addScriptTag({ content: source('frontend/js/map/map-layers.js') });
    await page.addScriptTag({ content: source('frontend/js/map/stations.js') });
    await page.evaluate(async () => {
      initMap();
      // Keep the check offline; no imagery is needed to exercise Leaflet geometry.
      map.removeLayer(currentTileLayer);
      const base = L.marker([22.55, 103.9]);
      corsBaseMarkers.base = base;
      setupMarkerLayerControls();
      allStations = [
        { id: 1, project_id: 7, name: 'Cảm biến 1', location: { lat: 22.5, lon: 103.8 } },
        { id: 2, project_id: 7, name: 'Cảm biến 2', location: { lat: 22.6, lon: 104 } },
        { id: 3, project_id: 7, name: 'Cảm biến 3', location: { lat: 22.52, lon: 103.85 } },
        { id: 4, project_id: 7, name: 'Chưa có tọa độ', location: { lat: null, lon: null } },
        { id: 5, project_id: 7, name: 'Tọa độ lỗi', location: { lat: 999, lon: 104 } },
        { id: 6, project_id: 8, name: 'Cảm biến 6', location: { lat: 20.8, lon: 106.7 } },
      ];
      allStations.forEach(updateMarker);
      await loadProjectsAndClusters();
    });
    await expect(page.locator('.project-map-marker')).toHaveCount(2);
    await expect(page.locator('.custom-map-marker')).toHaveCount(0);
    expect(await page.evaluate(() => ({ base: map.hasLayer(corsBaseMarkers.base), lines: clusterPolylines.some(line => map.hasLayer(line)) })))
      .toEqual({ base: false, lines: false });
    const center = await page.evaluate(() => projectMapGroups[0].marker.getLatLng());
    expect(center.lat).toBeCloseTo(22.45, 8);
    expect(center.lng).toBeCloseTo(103.9, 8);
    const project = page.getByRole('button', { name: 'Mỏ <Sin Quyền>: xem toàn bộ 3 trạm cảm biến' });
    await project.hover();
    await expect(page.locator('.project-map-tooltip strong')).toHaveText('Mỏ <Sin Quyền>');
    const tooltipBox = await page.locator('.project-map-tooltip').boundingBox();
    expect(tooltipBox.width).toBeGreaterThan(180);
    expect(tooltipBox.x).toBeGreaterThanOrEqual(0);
    expect(tooltipBox.x + tooltipBox.width).toBeLessThanOrEqual(viewport.width);
    await page.screenshot({ path: `test-results/project-map-pin-${viewport.width}.png` });
    await project.focus();
    await page.keyboard.press('Enter');
    if (viewport.width >= 900) {
      expect(await page.evaluate(() => map.getZoom())).toBeLessThan(10);
      await expect(page.locator('.custom-map-marker')).toHaveCount(0);
    }
    await expect(page.locator('.custom-map-marker')).toHaveCount(3);
    expect(await page.evaluate(() => map.hasLayer(corsBaseMarkers.base))).toBe(true);
    const fit = await page.evaluate(() => {
      const padding = getProjectMapPadding();
      const size = map.getSize();
      return [1, 2, 3].map(id => {
        const point = map.latLngToContainerPoint(markers[id].getLatLng());
        return point.x >= padding.paddingTopLeft[0] && point.y >= padding.paddingTopLeft[1]
          && point.x <= size.x - padding.paddingBottomRight[0] && point.y <= size.y - padding.paddingBottomRight[1];
      });
    });
    expect(fit).toEqual([true, true, true]);
    expect(await page.evaluate(() => clusterPolylines.every(line => map.hasLayer(line)))).toBe(true);
    await page.screenshot({ path: `test-results/project-map-fit-${viewport.width}.png` });
    await page.evaluate(() => map.setView([21.5, 105], 6, { animate: false }));
    await expect(page.locator('.custom-map-marker')).toHaveCount(0);
    await expect(page.locator('.project-map-marker')).toHaveCount(2);
    await page.screenshot({ path: `test-results/project-map-overview-${viewport.width}.png` });
    await page.getByRole('button', { name: 'Dự án một trạm: xem toàn bộ 1 trạm cảm biến' }).click();
    await expect.poll(() => page.evaluate(() => map.getZoom())).toBe(16);
    await expect(page.locator('.custom-map-marker')).toHaveCount(4);
    await page.locator('#layer-cors').uncheck();
    expect(await page.evaluate(() => map.hasLayer(corsBaseMarkers.base))).toBe(false);
    await page.locator('#layer-cors').check();
    expect(await page.evaluate(() => map.hasLayer(corsBaseMarkers.base))).toBe(true);
    await page.locator('#layer-station').uncheck();
    await expect(page.locator('.custom-map-marker')).toHaveCount(0);
    await expect(page.locator('.project-map-marker')).toHaveCount(0);
    expect(await page.evaluate(() => clusterPolylines.some(line => map.hasLayer(line)))).toBe(false);
    await page.locator('#layer-station').check();
    await page.evaluate(async () => {
      map.setView([21.5, 105], 6, { animate: false });
      allStations[0].location.lat = 22.4;
      window.projects[0].location = { map_mode: 'auto', lat: 22.50666667, lon: 103.88333333 };
      window.projects = [window.projects[0]];
      await loadProjectsAndClusters();
    });
    await expect(page.locator('.project-map-marker')).toHaveCount(1);
    expect((await page.evaluate(() => projectMapGroups[0].marker.getLatLng())).lat)
      .toBeCloseTo((22.4 + 22.6 + 22.52) / 3, 8);
    await page.evaluate(async () => {
      allStations = [];
      window.projects = [{ id: 9, name: 'Dự án mới', location: { map_mode: 'manual', lat: 21.5, lon: 105 } }];
      await loadProjectsAndClusters();
    });
    await expect(page.getByRole('button', { name: 'Dự án mới: xem toàn bộ 0 trạm cảm biến' })).toBeVisible();
  });
}
