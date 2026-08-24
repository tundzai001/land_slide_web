const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const projectRoot = join(__dirname, '..', '..');
const sessionSource = readFileSync(join(projectRoot, 'frontend/js/session-state.js'), 'utf8');
const landingSource = readFileSync(join(projectRoot, 'frontend/js/landing.js'), 'utf8');
const runtimeSource = readFileSync(join(projectRoot, 'frontend/js/app-runtime.js'), 'utf8');

async function installAppRoutes(page, authStatus = 200) {
  await page.route('https://app.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/auth/me') {
      if (authStatus === 200) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ username: 'admin', full_name: 'Administrator', role: 'admin' }),
        });
      } else {
        await route.fulfill({ status: authStatus, contentType: 'application/json', body: '{}' });
      }
      return;
    }
    await route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><div id="app-root"></div>' });
  });
}

test('landing progressive enhancement routes remembered operators to management', async () => {
  expect(landingSource).toContain("window.authSession?.inspect?.()");
  expect(landingSource).toContain("['admin', 'operator'].includes(session.user?.role)");
  expect(landingSource).toContain("const href = canManage ? '/management' : '/map'");
  expect(landingSource).toContain("const label = canManage ? 'Quản trị hệ thống' : 'Mở bản đồ'");
});

test('login route forwards a valid remembered session without showing the form', async ({ page }) => {
  await installAppRoutes(page, 200);
  await page.addInitScript(() => localStorage.setItem('token', 'remembered-token'));
  await page.goto('https://app.test/login?return_to=/management');
  await page.addScriptTag({ content: sessionSource });
  await page.addScriptTag({ content: runtimeSource });

  await expect(page).toHaveURL('https://app.test/management');
  await expect(page.locator('#login-form')).toHaveCount(0);
});

test('login route clears an invalid remembered token and shows the form', async ({ page }) => {
  await installAppRoutes(page, 401);
  await page.addInitScript(() => {
    localStorage.setItem('token', 'expired-token');
    localStorage.setItem('rememberMe', 'true');
  });
  await page.goto('https://app.test/login?return_to=/management');
  await page.addScriptTag({ content: sessionSource });
  await page.addScriptTag({ content: runtimeSource });

  await expect(page.locator('#login-form')).toBeVisible();
  const stored = await page.evaluate(() => ({
    local: localStorage.getItem('token'),
    session: sessionStorage.getItem('token'),
    remember: localStorage.getItem('rememberMe'),
  }));
  expect(stored).toEqual({ local: null, session: null, remember: null });
});
