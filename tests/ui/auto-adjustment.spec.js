const { test, expect } = require('./coverage-fixture');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const featureSource = readFileSync(
  join(__dirname, '..', '..', 'frontend/js/admin/auto-adjustment.js'),
  'utf8',
);

test('daily schedule is anchored at midnight and previews the next day', async ({ page }) => {
  await page.setContent(`<!doctype html><html><body>
    <select id="auto-adj-interval"><option value="4" selected>4</option></select>
    <select id="auto-adj-start-hour"><option value="0" selected>00:00</option></select>
    <div id="auto-adj-schedule-preview"></div>
    <input id="auto-adj-enabled" type="checkbox" checked>
    <input class="auto-adj-cluster-cb" type="checkbox" value="0" checked>
  </body></html>`);
  await page.evaluate(() => {
    window.AdminManager = class AdminManager {};
    window.applyAdminFeature = FeatureClass => {
      for (const name of Object.getOwnPropertyNames(FeatureClass.prototype)) {
        if (name === 'constructor') continue;
        Object.defineProperty(
          window.AdminManager.prototype,
          name,
          Object.getOwnPropertyDescriptor(FeatureClass.prototype, name),
        );
      }
    };
  });
  await page.addScriptTag({ content: featureSource });

  const result = await page.evaluate(() => {
    const manager = new window.AdminManager();
    manager.generateSchedulePreview();
    return {
      config: manager.collectAutoAdjustmentConfig(),
      preview: document.getElementById('auto-adj-schedule-preview').textContent.replace(/\s+/g, ' ').trim(),
    };
  });

  expect(result.config).toEqual({
    enabled: true,
    interval_hours: 4,
    start_hour: 0,
    scheduled_hours: ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00'],
    selected_clusters: [0],
  });
  expect(result.preview).toContain('00:00');
  expect(result.preview).toContain('20:00');
  expect(result.preview).toContain('Ngày kế tiếp 00:00');
});
