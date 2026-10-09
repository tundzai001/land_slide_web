const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const source = file => readFileSync(join(__dirname, '../..', file), 'utf8');
const catalog = JSON.parse(source('backend/app/shared/sensor_catalog.json'));

async function mount(page) {
  await page.setContent(`<html><head><style>${['theme-variables', 'admin/configuration'].map(name => source(`frontend/css/${name}.css`)).join('\n')}
  body {font-family:system-ui;margin:20px;background:var(--bg-primary);color:var(--text-primary)} .form-control {box-sizing:border-box;max-width:100%;padding:10px} .wizard-content:not([data-step="2"]) {display:none} .row {display:flex;flex-wrap:wrap;gap:10px} .sensor-config-section {padding:16px} .sensor-config-body input {display:block} </style></head><body></body></html>`);
  await page.evaluate(value => { window.SensorCatalog = value; }, catalog);
  await page.addScriptTag({ content: source('frontend/js/sensor-catalog.js') });
  for (const name of ['station-basic', 'station-connectivity', 'station-alerts', 'station-storage']) {
    await page.addScriptTag({ content: source(`frontend/js/templates/admin/${name}.js`) });
  }
  await page.evaluate(() => {
    document.body.innerHTML = '<input id="edit-project-id" value="1">' + Object.values(window.LegacyTemplateParts).join('');
  });
  for (const name of ['core', 'station-wizard', 'station-presets']) await page.addScriptTag({ content: source(`frontend/js/admin/${name}.js`) });
  await page.evaluate(() => {
    window.adminManager = Object.create(window.AdminManager.prototype);
    window.adminManager.currentStep = 2;
    document.querySelectorAll('[data-sensor-choice] input').forEach(input => input.addEventListener('change', () => window.adminManager.syncMqttSectionsForStep()));
  });
}

test('catalog supports multiple types, filtering and the existing save flow', async ({ page }) => {
  await mount(page);
  await expect(page.locator('[data-sensor-choice]')).toHaveCount(15);
  await page.locator('#edit-piezometer').check();
  await page.locator('#edit-temperature').check();
  await page.locator('#edit-flow_velocity').check();
  await expect(page.locator('#mqtt-piezometer-section')).toBeVisible();
  await expect(page.locator('#mqtt-temperature-section')).toBeVisible();
  await expect(page.locator('#mqtt-flow_velocity-section')).toBeVisible();
  await page.locator('#sensor-catalog-search').fill('thấm');
  await expect(page.locator('[data-sensor-choice]:visible')).toHaveCount(2);
  await expect(page.locator('#edit-temperature')).toBeChecked();
  await page.locator('#sensor-catalog-search').fill('');
  await page.locator('#topic-piezometer').fill('dam/T1/pressure');
  await page.locator('#topic-temperature').fill('dam/T1/temperature');
  await page.locator('#topic-flow_velocity').fill('dam/T1/flow_velocity');
  await page.locator('#origin-piezometer-lat').fill('15.1');
  await page.locator('#origin-piezometer-lon').fill('107.2');
  const payload = await page.evaluate(async () => {
    document.getElementById('edit-code').value = 'T1';
    document.getElementById('edit-name').value = 'Thân đập';
    Object.assign(window.adminManager, {
      validateAllMqttTopics: async () => true, confirmConfirmStepWarnings: () => true, defaultOfflineThresholds: {gnss:30,rain:60,water:60,imu:2400}, isEditMode: true, currentStationId: 1,
      stationModal: {hide() {}}, loadStations() {}, currentStationConfig: {}
    });
    window.toast = { success() {}, warning(message) {throw Error(message)}, error(message) {throw Error(message)} };
    window.fetch = async (url, options) => { window.saved = JSON.parse(options.body); return {ok:true}; };
    await window.adminManager.saveStation();
    return window.saved;
  });
  expect(Object.keys(payload.sensors).sort()).toEqual(['flow_velocity', 'piezometer', 'temperature']);
  expect(payload.sensors.piezometer.lat).toBe(15.1);
  expect(payload.config.piezometer_origin.lon).toBe(107.2);
});

test('catalog fits mobile and supports keyboard selection', async ({ page }) => {
  await page.setViewportSize({ width:390, height:844 });
  await mount(page);
  await page.locator('#edit-piezometer').focus();
  await page.keyboard.press('Space');
  await expect(page.locator('#edit-piezometer')).toBeChecked();
  await page.locator('#edit-piezometer').uncheck();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'tmp/monitoring/catalog-mobile.png', fullPage: true });
  await page.setViewportSize({width:1280,height:900});
  await page.screenshot({ path: 'tmp/monitoring/catalog-desktop.png', fullPage: true });
});

test('new sensor cards show zero, all axes, stale state and clear when changing stations', async ({ page }) => {
  await page.setContent('<div id="monitoring-sensor-values"></div>');
  await page.evaluate(value => { window.SensorCatalog = value; }, catalog);
  await page.addScriptTag({content:source('frontend/js/map/station-detail.js')});
  await page.evaluate(() => renderMonitoringSensors({sensors:{temperature:{latest:{temperature:0},is_online:true},accelerometer:{latest:{x:1,y:-2,z:3},is_online:false}}}));
  await expect(page.locator('#monitoring-sensor-values')).toContainText('0 °C');
  await expect(page.locator('#monitoring-sensor-values')).toContainText('Y: -2 m/s²');
  await expect(page.locator('#monitoring-sensor-values')).toContainText('Dữ liệu cuối');
  await page.evaluate(() => renderMonitoringSensors({sensors:{}}));
  await expect(page.locator('#monitoring-sensor-values')).toBeEmpty();
});

test('history charts retain every tilt axis and extensometer point, then release charts', async ({ page }) => {
  await page.setContent('<div id="charts-panel"></div>');
  await page.evaluate(value => { window.SensorCatalog = value; }, catalog);
  await page.addScriptTag({content:source('frontend/js/sensor-catalog.js')});
  await page.addScriptTag({content:source('frontend/js/templates/map/station-panels.js')});
  await page.evaluate(() => {
    document.body.innerHTML = window.LegacyTemplateParts['station-panels'];
    window.charts = {};
    window.normalizeEpochMs = value => value * 1000;
    window.Chart = class {
      constructor(canvas, config) { this.data = config.data; this.destroyed = false; }
      destroy() { this.destroyed = true; }
    };
  });
  await page.addScriptTag({content:source('frontend/js/map/station-detail.js')});
  const result = await page.evaluate(() => {
    renderCharts({sensors:{
      tiltmeter: {history:[{timestamp:1700000000,data:{x:1,y:2,z:3}}]},
      extensometer: {history:[{timestamp:1700000000,data:{points:{A1:0,A2:-2}}}]}
    }});
    const values = Object.fromEntries(Object.entries(charts).map(([key, chart]) => [key,chart.data.datasets[0].data]));
    const instances = Object.values(charts);
    destroyStationCharts();
    return {values, released:instances.every(chart => chart.destroyed), remaining:Object.keys(charts)};
  });
  expect(result.values['chart-tiltmeter-z']).toEqual([3]);
  expect(result.values['chart-extensometer-0']).toEqual([0]);
  expect(result.values['chart-extensometer-1']).toEqual([-2]);
  expect(result.released).toBe(true);
  expect(result.remaining).toEqual([]);
});

test('quality, measurement time and waveform are distinct from connection and snapshots', async ({page}) => {
  await page.setContent('<div id="monitoring-sensor-values"></div><div id="accelerometer-waveform-charts"></div>');
  await page.addStyleTag({content:source('frontend/css/theme-variables.css') + source('frontend/css/map/station-panels.css')});
  await page.evaluate(value => {window.SensorCatalog = value; window.charts = {}; window.Chart = class {
    constructor(canvas, config) {this.data = config.data;} destroy() {}
  };}, catalog);
  await page.addScriptTag({content:source('frontend/js/map/station-detail.js')});
  await page.evaluate(() => {
    const sensor = {is_online:true,latest_timestamp:1700000010,latest:{x:0,y:-2,z:3,quality:'suspect',
      measured_at:1700000000,reference_id:'ZERO-1',event_id:'EVENT-1',
      waveform:{start_at:1700000000,sample_rate_hz:250,x:[0,-2,1],y:[1,0,2],z:[3,2,1]}}};
    renderMonitoringSensors({sensors:{accelerometer:sensor}});
    renderAccelerometerWaveform(sensor);
  });
  await expect(page.locator('#monitoring-sensor-values')).toContainText('Đang nhận dữ liệu');
  await expect(page.locator('#monitoring-sensor-values')).toContainText('Chất lượng: cần kiểm tra');
  await expect(page.locator('#monitoring-sensor-values')).toContainText('Mốc: ZERO-1');
  await expect(page.locator('#monitoring-sensor-values')).toContainText('Đo:');
  await expect(page.locator('#monitoring-sensor-values')).toContainText('Nhận:');
  expect(await page.evaluate(() => charts['chart-waveform-x'].data.datasets[0].data)).toEqual([{x:0,y:0},{x:4,y:-2},{x:8,y:1}]);
  await expect(page.locator('#accelerometer-waveform-charts canvas')).toHaveCount(3);
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'tmp/monitoring/measurement-quality.png',fullPage:true});
  await page.evaluate(() => {
    renderMonitoringSensors({sensors:{piezometer:{is_online:true,latest:{pressure:999,quality:'invalid'}}}});
    renderAccelerometerWaveform(null);
  });
  await expect(page.locator('#monitoring-sensor-values')).toContainText('Áp lực thấm: — kPa');
  await expect(page.locator('#monitoring-sensor-values')).not.toContainText('999');
  await expect(page.locator('#accelerometer-waveform-charts')).toBeEmpty();
});
