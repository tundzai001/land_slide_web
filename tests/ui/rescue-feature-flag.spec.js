const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const source = file => readFileSync(join(__dirname, '../..', file), 'utf8');

for (const mode of ['disabled', 'enabled', 'unavailable']) {
  test(`rescue form is ${mode}`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.setContent('<body style="background:#edf4f4"><main>Bản đồ quan trắc</main></body>');
    await page.addStyleTag({ content: source('frontend/dist/app-base.min.css') + source('frontend/dist/map.min.css') + source('frontend/css/map/map-interface.css') });
    for (const file of ['templates/map/rescue', 'templates/map/shell', 'map/guest-rescue']) {
      await page.addScriptTag({ content: source(`frontend/js/${file}.js`) });
    }
    await page.evaluate(() => {
      const rescue = document.createElement('div');
      rescue.innerHTML = window.LegacyTemplateParts.rescue;
      document.body.append(rescue.querySelector('#btn-guest-rescue'), rescue.querySelector('#guestRescueModal'));
      const shell = document.createElement('div');
      shell.innerHTML = window.LegacyTemplateParts.shell;
      document.body.append(shell.querySelector('#map-bottom-nav'));
      window.bootstrap = { Modal: class { show() { const modal = document.getElementById('guestRescueModal'); modal.style.display = 'block'; modal.classList.add('show'); } } };
      window.fetch = () => new Promise((resolve, reject) => { window.resolveConfig = resolve; window.rejectConfig = reject; });
      window.setupPromise = setupGuestRescueUI();
    });
    const button = page.locator('#btn-guest-rescue');
    const shortcut = page.locator('[data-map-action="rescue"]');
    await expect(button).toBeHidden();
    await expect(shortcut).toBeHidden();
    await page.evaluate(async mode => {
      if (mode === 'unavailable') window.rejectConfig(new Error('offline'));
      else window.resolveConfig({ ok: true, json: async () => ({ enabled: mode === 'enabled' }) });
      await window.setupPromise;
    }, mode);
    if (mode === 'enabled') {
      await expect(button).toBeVisible();
      await expect(shortcut).toBeVisible();
      await button.focus();
      await expect(button).toBeFocused();
      await button.press('Enter');
      await expect(page.locator('#guestRescueModal')).toBeVisible();
    } else {
      await expect(button).toBeHidden();
      await expect(shortcut).toBeHidden();
      await expect(page.locator('#guestRescueModal')).toBeHidden();
      expect(await page.evaluate(() => window.rescueFormModal)).toBeUndefined();
      await page.screenshot({ path: `test-results/rescue-${mode}.png` });
    }
  });
}
