const { test, expect } = require('./coverage-fixture');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const projectRoot = join(__dirname, '..', '..');
const sessionSource = readFileSync(join(projectRoot, 'frontend/js/session-state.js'), 'utf8');
const landingSource = readFileSync(join(projectRoot, 'frontend/js/templates/landing-template.js'), 'utf8');
const runtimeSource = readFileSync(join(projectRoot, 'frontend/js/app-runtime.js'), 'utf8');
const authSource = readFileSync(join(projectRoot, 'frontend/js/auth.js'), 'utf8');
const themeCss = readFileSync(join(projectRoot, 'frontend/css/theme-variables.css'), 'utf8');
const componentCss = readFileSync(join(projectRoot, 'frontend/css/components.css'), 'utf8');

async function installAppRoutes(page, authStatus = 200) {
  await page.route('https://app.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/auth/me') {
      const status = typeof authStatus === 'function' ? authStatus() : authStatus;
      if (status === 200) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ username: 'admin', full_name: 'Administrator', role: 'admin' }),
        });
      } else {
        await route.fulfill({ status, contentType: 'application/json', body: '{}' });
      }
      return;
    }
    await route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><div id="app-root"></div>' });
  });
}

test('landing login returns to map', async () => {
  expect(landingSource).toContain('id="auth-link" href="/login?return_to=%2Fmap"');
});

for (const [path, destination] of [['/login', '/map'], ['/login?return_to=/map', '/map'], ['/login?return_to=/management', '/management'], ['/login////?return_to=/map', '/map']]) {
  test(`browser session opens ${destination} from ${path}`, async ({ page }) => {
    await installAppRoutes(page, 200);
    await page.addInitScript(() => { document.cookie = 'monitoring_csrf=test-csrf; Path=/; SameSite=Lax'; localStorage.setItem('token', 'obsolete-token'); });
    await page.goto(`https://app.test${path}`);
    await page.addScriptTag({ content: sessionSource });
    await page.addScriptTag({ content: runtimeSource });
    await expect(page).toHaveURL(`https://app.test${destination}`);
  });
}

test('login route forwards a valid browser session without showing the form', async ({ page }) => {
  await installAppRoutes(page, 200);
  await page.addInitScript(() => { document.cookie = 'monitoring_csrf=test-csrf; Path=/; SameSite=Lax'; localStorage.setItem('token', 'obsolete-token'); });
  await page.goto('https://app.test/login?return_to=/management');
  await page.addScriptTag({ content: sessionSource });
  await page.addScriptTag({ content: runtimeSource });

  await expect(page).toHaveURL('https://app.test/management');
  await expect(page.locator('#login-form')).toHaveCount(0);
});

test('login route clears an invalid remembered token and shows the form', async ({ page }) => {
  await installAppRoutes(page, 401);
  await page.addInitScript(() => {
    document.cookie = 'monitoring_csrf=expired-csrf; Path=/; SameSite=Lax';
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

test('successful login opens map by default', async ({ page }) => {
  let loggedIn = false;
  await installAppRoutes(page, () => loggedIn ? 200 : 401);
  await page.route('https://app.test/api/auth/login', route => {
    loggedIn = true;
    return route.fulfill({ json: { token_type: 'cookie' }, headers: { 'set-cookie': 'monitoring_csrf=test-csrf; Path=/; SameSite=Lax' } });
  });
  await page.goto('https://app.test/login');
  await page.addScriptTag({ content: sessionSource });
  await page.addScriptTag({ content: runtimeSource });
  await page.locator('#login-username').fill('operator');
  await page.locator('#login-password').fill('test-password');
  await page.locator('#login-submit').click();
  await expect(page).toHaveURL('https://app.test/map');
});

test('session dialog lists devices and revokes other sessions with CSRF', async ({ page }) => {
  await installAppRoutes(page, 200);
  let csrfHeader = null;
  let revoked = false;
  await page.route('https://app.test/api/auth/sessions', route => route.fulfill({ json: [
    { id: 'current-session-1234', client: 'Brave', current: true, created_at: 1760000000, last_seen: 1760000000, expires_at: 1860000000 },
    ...(!revoked ? [{ id: 'other-session-12345', client: 'Firefox', current: false, created_at: 1760000000, last_seen: 1760000000, expires_at: 1860000000 }] : []),
  ] }));
  await page.route('https://app.test/api/auth/sessions/revoke-others', route => {
    csrfHeader = route.request().headers()['x-csrf-token'];
    revoked = true;
    return route.fulfill({ json: { revoked: 1 } });
  });
  await page.addInitScript(() => { document.cookie = 'monitoring_csrf=test-csrf; Path=/; SameSite=Lax'; });
  await page.goto('https://app.test/map');
  await page.addStyleTag({ content: themeCss });
  await page.addStyleTag({ content: componentCss });
  await page.addScriptTag({ content: sessionSource });
  await page.addScriptTag({ content: authSource });
  await page.evaluate(() => window.authManager.openSessions());
  await expect(page.getByRole('dialog', { name: 'Phiên đăng nhập' })).toBeVisible();
  await expect(page.getByText('Firefox')).toBeVisible();
  await page.getByRole('button', { name: 'Đăng xuất thiết bị khác' }).click();
  await expect(page.getByText('Firefox')).toHaveCount(0);
  expect(csrfHeader).toBe('test-csrf');
});
