const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const source = file => readFileSync(join(__dirname, '../..', file), 'utf8');
const catalog = JSON.parse(source('backend/app/shared/sensor_catalog.json'));

for (const { width, height } of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
  test(`station setup sensor picker at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.setContent('<!doctype html><html data-theme="light"><body></body></html>');
    await page.addStyleTag({ content: [
      'frontend/css/theme-variables.css', 'frontend/css/components.css', 'frontend/css/admin/base.css',
      'frontend/css/admin/configuration.css', 'frontend/css/admin/pi-wizard.css',
      'frontend/css/admin-responsive.css', 'frontend/css/admin/premium-light.css',
    ].map(source).join('\n') + '\n.modal { position:fixed; inset:0; display:block; opacity:1!important; background:rgba(15,23,42,.48) } .modal-dialog { margin:auto } .modal-content { display:flex } .row { display:flex;flex-wrap:wrap } .col-md-4 {flex:0 0 33.333%} .col-md-6 {flex:0 0 50%} .col-md-8 {flex:0 0 66.666%} .form-control {display:block;width:100%;box-sizing:border-box} .btn {cursor:pointer} .btn-close {cursor:pointer} ' });
    await page.addScriptTag({ content: `window.SensorCatalog = ${JSON.stringify(catalog)};` });
    for (const name of ['station-wizard-shell', 'station-basic', 'station-connectivity', 'station-alerts', 'station-storage']) {
      await page.addScriptTag({ content: source(`frontend/js/templates/admin/${name}.js`) });
    }
    await page.addScriptTag({ content: source('frontend/js/sensor-catalog.js') });
    await page.evaluate(() => {
      document.body.innerHTML = ['station-wizard-shell', 'station-basic', 'station-connectivity', 'station-alerts', 'station-storage']
        .map(name => window.LegacyTemplateParts[name]).join('');
      document.querySelector('#stationConfigModal').classList.add('show');
      document.querySelector('#stationConfigModal').setAttribute('aria-hidden', 'false');
      document.querySelector('.wizard-content[data-step="1"]').classList.remove('active');
      document.querySelector('.wizard-content[data-step="2"]').classList.add('active');
      document.querySelector('.wizard-step[data-step="1"]').classList.remove('active');
      document.querySelector('.wizard-step[data-step="2"]').classList.add('active');
      document.querySelector('#btn-wizard-back').style.display = 'inline-flex';
    });
    await expect(page.locator('[data-sensor-choice]')).toHaveCount(catalog.length);
    await expect(page.locator('#edit-flow_velocity')).toBeAttached();
    await expect(page.locator('#station-connectivity-heading')).toBeVisible();
    await expect(page.locator('.station-connection-heading')).toBeVisible();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `test-results/station-wizard-${width}.png` });
    await page.locator('[data-sensor-choice]').filter({ hasText: 'Biến dạng' }).first().click();
    await expect(page.locator('#edit-strain')).toBeChecked();
    await page.locator('#sensor-catalog-search').fill('giãn kế');
    await expect(page.locator('[data-sensor-choice]:visible')).toHaveCount(1);
    await page.locator('#sensor-catalog-search').fill('');
    await page.getByRole('button', { name: 'Thân đập', exact: true }).click();
    await expect(page.locator('#edit-strain')).toBeChecked();
    const horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    expect(horizontalOverflow).toBeLessThanOrEqual(1);
  });
}
