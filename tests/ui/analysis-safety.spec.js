const { test, expect } = require('./coverage-fixture');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

test('long-term text removes only the intended emoji', async ({ page }) => {
  await page.setContent('<!doctype html><html><body></body></html>');
  await page.addScriptTag({ content: readFileSync(join(__dirname, '../../frontend/js/map/analysis.js'), 'utf8') });
  const result = await page.evaluate(() => sanitizeLongTermText('📈 Tăng 🚨 và 🛰️'));
  expect(result).toBe('Tăng và 🛰️');
});

test('sensor consensus renders untrusted labels and notes as text', async ({ page }) => {
  await page.setContent('<section id="cross-consensus-section"><div id="consensus-banner"><span id="consensus-badge"></span></div><p id="consensus-summary"></p><div id="consensus-sensors-with-data"></div><p id="consensus-trend-agreement"></p><div id="consensus-notes"></div></section>');
  await page.addScriptTag({ content: readFileSync(join(__dirname, '../../frontend/js/map/analysis.js'), 'utf8') });
  await page.evaluate(() => renderCrossConsensusSection({ cross_sensor_consensus: {
    available: true, sensors_with_data: ['<img src=x onerror=alert(1)>'], notes: ['<img src=x onerror=alert(1)>'],
  } }));
  await expect(page.locator('#cross-consensus-section img')).toHaveCount(0);
  await expect(page.locator('#consensus-sensors-with-data')).toContainText('<img src=x onerror=alert(1)>');
  await expect(page.locator('#consensus-notes')).toContainText('<img src=x onerror=alert(1)>');
});
