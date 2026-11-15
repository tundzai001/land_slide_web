const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const source = file => readFileSync(join(__dirname, '../..', file), 'utf8');

for (const theme of ['light', 'dark']) {
  test(`GNSS evaluation text stays readable in ${theme} mode`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.setContent(`<html lang="vi" data-theme="${theme}" data-app-view="map"><body></body></html>`);
    await page.addStyleTag({ content: source('frontend/dist/app-base.min.css') });
    await page.addStyleTag({ content: source('frontend/dist/map.min.css') });
    // Match production: Bootstrap is inserted after both application stylesheets.
    await page.addStyleTag(process.env.WORKSPACE_BOOTSTRAP_CSS
      ? { path: process.env.WORKSPACE_BOOTSTRAP_CSS }
      : { url: 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' });
    await page.addScriptTag({ content: source('frontend/js/templates/map/station-panels.js') });
    await page.evaluate(() => {
      document.body.innerHTML = window.LegacyTemplateParts['station-panels'];
      document.getElementById('detail-sidebar').classList.add('active');
      document.getElementById('st-name').textContent = 'CP03';
      window.currentStationData = { id: 1 };
      window.mapUiState = { selectedStation: 1 };
      window.latestRealtimeSensorTs = {};
      window.stationSensorCatalog = () => [];
      window.updateGnssFixBadge = () => {};
      window.updateGnssIntegrityStatus = () => {};
      window.getGnssVelocity = data => data.speed_3d_mm_s;
      window.setHTML = (id, html) => { document.getElementById(id).innerHTML = html; };
      window.safeNumber = (value, digits) => Number(value).toFixed(digits);
      window.clearGnssEvaluationSummary = () => {};
    });
    await page.addScriptTag({ content: source('frontend/js/map/realtime.js') });
    for (const state of [{}, { velocity_reliable: false }, { velocity_confirmed: true },
      { velocity_confirmed: false, velocity_statistically_significant: true },
      { integrity: { integrity_state: 'REFERENCE_TRANSITION' } }]) {
      await page.evaluate(state => updateRealtimeSensorValues({
        station_id: 1, sensor_type: 'gnss', timestamp: Date.now() / 1000,
        data: { speed_3d_mm_s: 0.7129, velocity_method: 'theil_sen_enu',
          velocity_sample_count: 16, velocity_window_duration_s: 15,
          velocity_confidence_95_mm_s: 0.45, velocity_z_score: 2.36, ...state },
      }), state);
      const ratios = await page.locator('#gnss-eval-summary').evaluate(summary => {
        const context = document.createElement('canvas').getContext('2d');
        const rgb = color => {
          context.fillStyle = color;
          context.fillRect(0, 0, 1, 1);
          return [...context.getImageData(0, 0, 1, 1).data].slice(0, 3);
        };
        const luminance = color => rgb(color).map(value => {
          value /= 255;
          return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
        }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
        const background = luminance(getComputedStyle(summary.closest('.sensor-item')).backgroundColor);
        return [...summary.querySelectorAll('span, strong, .gnss-eval-muted')].map(element => {
          const foreground = luminance(getComputedStyle(element).color);
          return { text: element.textContent, color: getComputedStyle(element).color,
            ratio: (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05) };
        });
      });
      expect(ratios.length).toBeGreaterThan(0);
      for (const item of ratios) expect(item.ratio, JSON.stringify(item)).toBeGreaterThanOrEqual(4.5);
    }
    await page.evaluate(() => updateRealtimeSensorValues({
      station_id: 1, sensor_type: 'gnss', data: { speed_3d_mm_s: 0.7129,
        velocity_method: 'theil_sen_enu', velocity_sample_count: 16,
        velocity_window_duration_s: 15, velocity_confidence_95_mm_s: 0.45, velocity_z_score: 2.36 },
    }));
    await expect(page.locator('#gnss-eval-summary')).toContainText('Cửa sổ vận tốc: 16 mẫu (15.0s)');
    await expect(page.locator('#gnss-eval-summary .opacity-75')).toHaveCount(0);
    await page.locator('#detail-sidebar').screenshot({ path: `tmp/gnss-summary-${theme}.png` });
  });
}
