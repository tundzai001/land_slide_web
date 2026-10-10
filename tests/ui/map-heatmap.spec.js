const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const toolsSource = readFileSync(join(__dirname, '../../frontend/js/map/tools.js'), 'utf8');
const heatmapSource = toolsSource.slice(
  toolsSource.indexOf('// --- FEATURE 5:'),
  toolsSource.indexOf('// --- FEATURE 6:')
);

test('station heatmap works independently of rescue and refreshes with station data', async ({ page }) => {
  await page.setContent('<button id="heatmap-toggle" aria-pressed="false">Heatmap</button><input id="layer-heatmap" type="checkbox">');
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
  expect(await page.evaluate(() => window.layerEvents[0])).toEqual(['add', [[21.2, 107.3, 1], [22, 103, 0.2]]]);

  await page.evaluate(() => {
    allStations = [{ location: { lat: 21.3, lon: 107.4 }, risk_level: 'MEDIUM', status: 'online' }];
    refreshHeatmapData();
  });
  expect(await page.evaluate(() => window.layerEvents[1])).toEqual(['update', [[21.3, 107.4, 0.65]]]);

  await page.locator('#heatmap-toggle').click();
  await expect(page.locator('#heatmap-toggle')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('#layer-heatmap')).not.toBeChecked();
  expect(await page.evaluate(() => window.layerEvents[2][0])).toBe('remove');
});

test('Leaflet renders the station heatmap on the map', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 600 });
  await page.setContent('<div id="map" style="position:fixed;inset:0;background:#dce8e4"></div><button id="heatmap-toggle" aria-pressed="false" style="position:fixed;top:20px;left:20px;z-index:1000">Heatmap</button><input id="layer-heatmap" type="checkbox" style="position:fixed;top:50px;left:20px;z-index:1000">');
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
  await page.locator('#heatmap-toggle').click();
  await expect(page.locator('.leaflet-heatmap-layer')).toHaveCount(1);
  await expect(page.locator('#heatmap-toggle')).toHaveAttribute('aria-pressed', 'true');
  await page.screenshot({ path: 'test-results/station-heatmap.png' });
});
