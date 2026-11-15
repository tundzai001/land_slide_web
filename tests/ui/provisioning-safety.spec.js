const { test, expect } = require('./coverage-fixture');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

test('pending Pi data remains text and device actions stay usable', async ({ page }) => {
  await page.setContent('<div id="pending-devices-list"></div>');
  await page.addScriptTag({ content: `
    window.AdminManager = class {};
    window.applyAdminFeature = Feature => { window.adminManager = new Feature(); };
    window.toast = { success() {}, error() {} };
  ` });
  await page.addScriptTag({ content: readFileSync(join(__dirname, '../../frontend/js/admin/provisioning.js'), 'utf8') });
  const code = "Pi' onclick='window.injected=1";
  await page.evaluate(deviceCode => {
    window.adminManager.renderPendingDevices([{
      device_code: deviceCode,
      name: '<img src=x onerror="window.injected=1">',
      device_type: '<script>window.injected=1</script>',
      config: { license: '<svg onload="window.injected=1">' },
    }]);
  }, code);
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
  await expect(page.locator('#pending-devices-list img, #pending-devices-list script, #pending-devices-list svg')).toHaveCount(0);
  await expect(page.getByText('<img src=x onerror=', { exact: false })).toBeVisible();
  const details = page.getByRole('button', { name: 'Chi tiết' });
  await details.click();
  await expect(details).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('#pending-detail-0')).toBeVisible();

  await page.evaluate(() => {
    window.adminManager.generateLicense = code => new Promise(resolve => {
      window.chosenDevice = code;
      window.finishLicense = resolve;
    });
  });
  await page.getByRole('button', { name: 'Chỉ tạo Key' }).click();
  expect(await page.evaluate(() => window.chosenDevice)).toBe(code);
  await expect(page.locator('[data-device-index]')).toHaveAttribute('aria-busy', 'true');
  await expect(page.getByRole('button', { name: 'Tạo Key & Gán vào trạm' })).toBeDisabled();
  await page.evaluate(() => window.finishLicense());
  await expect(page.locator('[data-device-index]')).not.toHaveAttribute('aria-busy', 'true');
  await expect(page.getByRole('button', { name: 'Chỉ tạo Key' })).toBeEnabled();
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
});

test('Pi assignment picker escapes device names and keeps selection working', async ({ page }) => {
  await page.setContent('<div id="pending-devices-list"></div><div id="pi-assign-btn-row"></div><div id="current-pi-info"></div>');
  await page.addScriptTag({ content: `
    window.AdminManager = class {};
    window.applyAdminFeature = Feature => { window.adminManager = new Feature(); };
    window.fetch = async () => ({ json: async () => [{
      id: 7, name: '<img src=x onerror="window.injected=1">', serial: '<svg onload="window.injected=1">',
      device_type: 'pi_center', status: 'activated', station_id: null
    }] });
  ` });
  await page.addScriptTag({ content: readFileSync(join(__dirname, '../../frontend/js/admin/pi-center.js'), 'utf8') });
  await page.evaluate(() => {
    window.adminManager.currentStationId = 10;
    return window.adminManager.loadWizardPendingDevices();
  });
  await expect(page.locator('#pending-devices-list img, #pending-devices-list svg')).toHaveCount(0);
  await expect(page.getByText('<img src=x onerror=', { exact: false })).toBeVisible();
  await page.locator('.wizard-pi-option').click();
  expect(await page.evaluate(() => window.adminManager._selectedWizardPiId)).toBe(7);
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
});
