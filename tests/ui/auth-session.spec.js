const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const projectRoot = join(__dirname, '..', '..');
const sessionSource = readFileSync(join(projectRoot, 'frontend/js/session-state.js'), 'utf8');
const landingSource = readFileSync(join(projectRoot, 'frontend/js/landing.js'), 'utf8');
const runtimeSource = readFileSync(join(projectRoot, 'frontend/js/app-runtime.js'), 'utf8');

const landingDocument = `<!doctype html><html data-theme="light"><body>
  <header id="site-header"><button id="theme-button"></button><a data-auth-link href="/login?return_to=/management">Đăng nhập</a></header>
  <button id="menu-button" aria-expanded="false"></button>
  <div id="mobile-menu" hidden><a data-auth-link href="/login?return_to=/management">Đăng nhập quản trị</a></div>
  <span id="stations-total"></span><span id="stations-online"></span><span id="stations-offline"></span><span id="stations-stale"></span><span id="summary-updated"></span>
</body></html>`;

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
    if (url.pathname === '/api/public/dashboard-summary') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ stations: { total: 1, online: 1, offline: 0, stale: 0 }, updated_at: new Date().toISOString() }),
      });
      return;
    }
    if (url.pathname.startsWith('/assets/')) {
      await route.fulfill({ status: 200, contentType: 'text/css', body: '' });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><div id="app-root"></div>' });
  });
}

test('remembered admin session updates every landing login link', async ({ page }) => {
  await installAppRoutes(page, 200);
  await page.addInitScript(() => {
    localStorage.setItem('token', 'remembered-token');
    localStorage.setItem('rememberMe', 'true');
  });
  await page.goto('https://app.test/');
  await page.setContent(landingDocument);
  await page.addScriptTag({ content: sessionSource });
  await page.addScriptTag({ content: landingSource });

  const links = page.locator('[data-auth-link]');
  await expect(links).toHaveCount(2);
  await expect(links.first()).toHaveText('Quản trị hệ thống');
  await expect(links.first()).toHaveAttribute('href', '/management');
  await expect(links.nth(1)).toHaveText('Quản trị hệ thống');
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
