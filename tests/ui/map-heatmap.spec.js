const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const toolsSource = readFileSync(join(__dirname, '../../frontend/js/map/tools.js'), 'utf8');
const heatmapSource = toolsSource.slice(
  toolsSource.indexOf('// --- FEATURE 5:'),
  toolsSource.indexOf('// --- FEATURE 6:')
);

test('station heatmap works independently of rescue and refreshes with station data', async ({ page }) => {
  await page.setContent('<button id="heatmap-toggle" aria-pressed="false">Heatmap</button><input id="layer-heatmap" type="checkbox"><aside id="heatmap-legend" hidden><span id="heatmap-count"></span></aside>');
  await page.evaluate(() => {
    window.rescueFeatureEnabled = false;
    window.layerEvents = [];
    window.map = {
      removeLayer(layer) { window.layerEvents.push(['remove', layer.points]); },
    };
    window.L = {};
    window.loadFeatureLibrary = async () => {
      window.L.heatLayer = (points) => ({
        points,
        addTo() { window.layerEvents.push(['add', this.points]); return this; },
        setLatLngs(next) { this.points = next; window.layerEvents.push(['update', next]); },
      });
    };
  });
  await page.addScriptTag({ content: `
    var map = window.map;
    var allStations = [
      { location: {lat: 21.2, lon: 107.3}, risk_level: 'CRITICAL', status: 'online' },
      { location: {lat: 22, lon: 103}, risk_level: 'LOW', status: 'online' },
      { location: {lat: 0, lon: 0}, risk_level: 'CRITICAL', status: 'online' },
      { location: {lat: 20, lon: 105}, risk_level: 'CRITICAL', status: 'offline' },
    ];
    function hasValidLatLon(location) { return location && Number(location.lat) !== 0 && Number.isFinite(Number(location.lat)) && Number.isFinite(Number(location.lon)); }
    function normalizeRiskLevel(risk, status) { return status === 'offline' ? 'OFFLINE' : risk; }
    function setMapState(patch) { window.lastMapState = patch; }
    function runWhenDomReady(callback) { callback(); }
    ${heatmapSource}
  ` });
  await page.locator('#heatmap-toggle').click();
  await expect(page.locator('#heatmap-toggle')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#layer-heatmap')).toBeChecked();
  expect(await page.evaluate(() => window.layerEvents[0])).toEqual(['add', [[21.2, 107.3, 1]]]);
  await expect(page.locator('#heatmap-legend')).toBeVisible();
  await expect(page.locator('#heatmap-count')).toHaveText('1 trạm cảnh báo · 1 nguy cấp');

  await page.evaluate(() => {
    allStations = [{ location: { lat: 21.3, lon: 107.4 }, risk_level: 'MEDIUM', status: 'online' }];
    refreshHeatmapData();
  });
  expect(await page.evaluate(() => window.layerEvents[1])).toEqual(['update', [[21.3, 107.4, 0.65]]]);
  await expect(page.locator('#heatmap-count')).toHaveText('1 trạm cảnh báo · 0 nguy cấp');

  await page.locator('#heatmap-toggle').click();
  await expect(page.locator('#heatmap-toggle')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('#layer-heatmap')).not.toBeChecked();
  await expect(page.locator('#heatmap-legend')).toBeHidden();
  expect(await page.evaluate(() => window.layerEvents[2][0])).toBe('remove');
});

test('safe stations never create misleading heat spots', async ({ page }) => {
  await page.setContent('<button id="heatmap-toggle">Heatmap</button><input id="layer-heatmap" type="checkbox">');
  await page.addScriptTag({ content: `
    var map = {};
    var allStations = [{ location: {lat: 21, lon: 105}, risk_level: 'LOW', status: 'online' }];
    var L = {};
    function hasValidLatLon() { return true; }
    function normalizeRiskLevel(risk) { return risk; }
    function setMapState() {}
    function runWhenDomReady(callback) { callback(); }
    ${heatmapSource}
  ` });
  await page.locator('#heatmap-toggle').click();
  await expect(page.locator('#layer-heatmap')).not.toBeChecked();
  expect(await page.evaluate(() => heatmapVisible)).toBe(false);
});

for (const viewport of [{ width: 1280, height: 720 }, { width: 390, height: 844 }]) {
test(`Leaflet renders the station heatmap at ${viewport.width}px`, async ({ page }) => {
  await page.setViewportSize(viewport);
  await page.setContent(`<!doctype html><html data-theme="light" data-app-view="map"><body>
    <div id="map" style="background:#dce8e4"></div>
    <aside class="map-status-legend"><span>An toàn</span><span>Cảnh báo</span><span>Nguy cấp</span></aside>
    <aside class="map-heatmap-legend" id="heatmap-legend" hidden><strong>Mật độ cảnh báo</strong><span id="heatmap-count"></span><span class="heatmap-gradient"></span><span class="heatmap-scale"><span>Ít / cảnh báo</span><span>Nhiều / nguy cấp</span></span></aside>
    <div class="custom-map-controls"><div class="heatmap-toggle-wrap"><button class="heatmap-toggle-btn" id="heatmap-toggle" aria-pressed="false">●</button></div></div>
    <input id="layer-heatmap" type="checkbox" hidden>
  </body></html>`);
  await page.addStyleTag({ content: readFileSync(join(__dirname, '../../frontend/dist/app-base.min.css'), 'utf8') + readFileSync(join(__dirname, '../../frontend/dist/map.min.css'), 'utf8') });
  await page.addStyleTag({ url: 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css' });
  await page.addScriptTag({ url: 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js' });
  await page.addScriptTag({ url: 'https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js' });
  await page.addScriptTag({ content: `
    var map = L.map('map', { zoomControl: false }).setView([21.2, 107.3], 8);
    var allStations = [
      { location: {lat: 21.2, lon: 107.3}, risk_level: 'CRITICAL', status: 'online' },
      { location: {lat: 21.3, lon: 107.4}, risk_level: 'MEDIUM', status: 'online' },
      { location: {lat: 21.35, lon: 107.25}, risk_level: 'LOW', status: 'online' },
    ];
    function hasValidLatLon(location) { return location && Number.isFinite(Number(location.lat)) && Number.isFinite(Number(location.lon)); }
    function normalizeRiskLevel(risk) { return risk; }
    function setMapState() {}
    function runWhenDomReady(callback) { callback(); }
    ${heatmapSource}
  ` });
  if (viewport.width > 900) await page.locator('#heatmap-toggle').click();
  else await page.evaluate(() => toggleHeatmap());
  await expect(page.locator('.leaflet-heatmap-layer')).toHaveCount(1);
  await expect(page.locator('#heatmap-toggle')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#heatmap-legend')).toBeVisible();
  const legendBox = await page.locator('#heatmap-legend').boundingBox();
  expect(legendBox.x).toBeGreaterThanOrEqual(0);
  expect(legendBox.x + legendBox.width).toBeLessThanOrEqual(viewport.width);
  await page.screenshot({ path: `test-results/station-heatmap-${viewport.width}.png` });
});
}
