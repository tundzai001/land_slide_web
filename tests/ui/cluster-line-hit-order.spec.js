const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const stationsSource = readFileSync(
  join(__dirname, '..', '..', 'frontend/js/map/stations.js'),
  'utf8',
);

test('ordinary cluster paths stay above total-cluster hitboxes', async ({ page }) => {
  await page.setContent('<div id="map"></div>');
  await page.evaluate(() => {
    window.createdPolylines = [];
    window.createdPanes = {};
    window.mapInteractionActive = false;
    window.pendingProjectsReload = false;
    window.projectsFetchInFlight = false;
    window.clusterRenderSignature = '';
    window.clusterPolylines = [];
    window.adjustmentRequests = [];
    window.requestGnssAdjustment = (projectId, stationIds) => {
      window.adjustmentRequests.push({ projectId, stationIds });
    };
    window.stationClusterGroup = null;
    window.currentTileLayer = null;
    window.tileUrls = [];
    window.TILE_URLS = { light: 'light', dark: 'dark' };
    window.TILE_OPTIONS = { light: {}, dark: {} };
    window.beginMapInteraction = () => {};
    window.endMapInteraction = () => {};
    window.getLeafletMap = () => window.map;
    window.allStations = [
      { id: 1, name: 'Dap1_1', location: { lat: 1, lon: 1 } },
      { id: 2, name: 'Dap1_2', location: { lat: 2, lon: 2 } },
      { id: 3, name: 'Dap4_1', location: { lat: 3, lon: 3 } },
    ];

    const fakeMap = {
      on() {},
      setView() { return this; },
      addLayer() {},
      removeLayer() {},
      closePopup() {},
      createPane(name) {
        const pane = { style: {} };
        window.createdPanes[name] = pane;
        return pane;
      },
    };
    window.L = {
      map() { return fakeMap; },
      layerGroup() { return {}; },
      tileLayer(url) { window.tileUrls.push(url); return { addTo() { return this; } }; },
      polyline(_points, options) {
        const line = {
          options,
          handlers: {},
          on(event, handler) { this.handlers[event] = handler; return this; },
          addTo() { return this; },
        };
        window.createdPolylines.push(line);
        return line;
      },
      popup() {
        return {
          setLatLng() { return this; },
          setContent(content) { window.popupContent = content; return this; },
          openOn() { return this; },
        };
      },
    };
    window.fetch = async () => ({
      ok: true,
      json: async () => [{
        id: 7,
        name: 'Sin Quyen',
        // Deliberately put the normal cluster first: rendering must still put
        // the aggregate below it.
        gnss_clusters: [
          { name: 'Dap 1', cluster_type: 'normal', stations: [1, 2] },
          { name: 'Ca 2 dap', cluster_type: 'total', stations: [1, 2, 3] },
        ],
      }],
    });
  });

  await page.addScriptTag({ content: stationsSource });
  const result = await page.evaluate(async () => {
    initMap();
    await loadProjectsAndClusters();
    return {
      panes: Object.fromEntries(
        Object.entries(window.createdPanes).map(([name, pane]) => [name, pane.style.zIndex]),
      ),
      pathPanes: window.createdPolylines.map(line => line.options.pane),
      tileUrls: window.tileUrls,
    };
  });

  expect(result.panes).toEqual({
    gnssTotalClusterPane: '390',
    gnssNormalClusterPane: '410',
  });
  expect(result.pathPanes).toEqual([
    'gnssTotalClusterPane',
    'gnssTotalClusterPane',
    'gnssNormalClusterPane',
    'gnssNormalClusterPane',
  ]);
  expect(result.tileUrls).toEqual(['light']);

  const overlap = await page.evaluate(() => {
    window.createdPolylines[2].handlers.click({ latlng: { lat: 1.5, lng: 1.5 } });
    const buttons = [...window.popupContent.querySelectorAll('button')];
    const labels = buttons.map(button => button.textContent);
    buttons.at(-1).click();
    return { labels, requests: window.adjustmentRequests };
  });
  expect(overlap.labels).toEqual(['Cụm · Dap 1', 'Cụm tổng · Ca 2 dap']);
  expect(overlap.requests).toEqual([{ projectId: 7, stationIds: [1, 2, 3] }]);
});

test('station list updates existing rows with localized connection state', async ({ page }) => {
  await page.setContent('<div id="station-list-container"></div>');
  await page.evaluate(() => {
    window.escapeHtml = value => String(value);
    window.selectStation = () => {};
    window.setStationListSidebarOpen = () => {};
    window.getRiskPresentation = (_risk, status) => status === 'stale'
      ? { normalized: 'STALE', className: 'STALE' }
      : { normalized: 'LOW', className: 'LOW' };
  });
  await page.addScriptTag({ content: stationsSource });

  const result = await page.evaluate(() => {
    renderStationList([{ id: 1, name: 'Đập 1 số 1', station_code: 'Dap1_1', status: 'online' }]);
    renderStationList([{ id: 1, name: 'Đập 1 số 1', station_code: 'Dap1_1', status: 'stale' }]);
    const row = document.querySelector('.station-item');
    return {
      count: document.querySelectorAll('.station-item').length,
      state: row.dataset.state,
      label: row.querySelector('.station-status').textContent,
    };
  });

  expect(result).toEqual({ count: 1, state: 'stale', label: 'Mất tín hiệu' });
});
