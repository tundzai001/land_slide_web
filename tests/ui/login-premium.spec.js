const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const root = join(__dirname, '..', '..');
const sessionSource = readFileSync(join(root, 'frontend/js/session-state.js'), 'utf8');
const runtimeSource = readFileSync(join(root, 'frontend/js/app-runtime.js'), 'utf8');
const baseCss = readFileSync(join(root, 'frontend/dist/app-base.min.css'), 'utf8');
const loginCss = readFileSync(join(root, 'frontend/css/login.css'), 'utf8');

async function openLogin(page) {
  await page.route('https://app.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/assets/aitogy.png') {
      await route.fulfill({status:200, contentType:'image/png', body:readFileSync(join(root, 'frontend/assets/aitogy.png'))});
      return;
    }
    if (url.pathname === '/assets/login.min.css') {
      await route.fulfill({ status: 200, contentType: 'text/css', body: loginCss });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'text/html',
      body: '<!doctype html><html lang="vi" data-theme="light"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="app-root"></div></body></html>',
    });
  });
  await page.route('https://cdn.jsdelivr.net/**', route => route.fulfill({ status: 200, contentType: 'text/css', body: '' }));
  await page.goto('https://app.test/login?return_to=/map');
  await page.addStyleTag({ content: baseCss });
  await page.addScriptTag({ content: sessionSource });
  await page.addScriptTag({ content: runtimeSource });
  await expect(page.locator('.login-card')).toBeVisible();
  await expect(page.locator('.login-brand .app-brand-product strong')).toHaveText('Monitoring');
}

test('production login keeps controls proportioned and responsive', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openLogin(page);

  const geometry = await page.evaluate(() => {
    const rect = selector => document.querySelector(selector).getBoundingClientRect();
    const username = rect('#login-username');
    const checkbox = rect('#login-remember');
    const card = rect('.login-card');
    return {
      usernameWidth: username.width,
      checkboxWidth: checkbox.width,
      checkboxHeight: checkbox.height,
      cardWidth: card.width,
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      errorDisplay: getComputedStyle(document.querySelector('#login-error')).display,
    };
  });

  expect(geometry.usernameWidth).toBeGreaterThan(300);
  expect(geometry.cardWidth).toBeGreaterThan(390);
  expect(geometry.checkboxWidth).toBeLessThanOrEqual(20);
  expect(geometry.checkboxHeight).toBeLessThanOrEqual(20);
  expect(geometry.overflow).toBe(0);
  expect(geometry.errorDisplay).toBe('none');

  await page.locator('#login-submit').click();
  await expect(page.locator('#login-error')).toContainText('Vui lòng nhập');
  await page.screenshot({ path: 'test-results/login-premium-desktop.png', fullPage: true });

  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 375, height: 844 });
  await page.evaluate(() => { document.documentElement.style.fontSize = '20px'; });
  await expect(page.locator('.login-card')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBe(0);
  await page.screenshot({ path: 'test-results/login-premium-mobile.png', fullPage: true });

  await page.setViewportSize({ width: 844, height: 390 });
  await page.evaluate(() => { document.documentElement.style.fontSize = ''; });
  await page.locator('#login-theme').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.locator('.login-card')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBe(0);
});
