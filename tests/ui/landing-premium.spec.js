const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const indexSource = readFileSync(join(__dirname, '..', '..', 'frontend/index.html'), 'utf8');
const landingTemplateSource = readFileSync(join(__dirname, '..', '..', 'frontend/js/templates/landing-template.js'), 'utf8');
const landingCss = readFileSync(join(__dirname, '..', '..', 'frontend/dist/landing.min.css'));
const landingJs = readFileSync(join(__dirname, '..', '..', 'frontend/dist/landing.min.js'));

test.beforeEach(async ({page}) => {
  await page.route('**/assets/aitogy.png*', route => route.fulfill({contentType:'image/png',body:readFileSync(join(__dirname, '../..', 'frontend/assets/aitogy.png'))}));
});

test('index is semantic and progressively enhanced without React', async () => {
  expect(indexSource).toContain('<div id="landing-root"></div>');
  expect(indexSource).toContain('rel="canonical"');
  expect(indexSource).toContain('Quan trắc công trình, đập và môi trường');
  expect(indexSource).toContain('"@type":"WebPage"');
  expect(indexSource).toContain('og:image:alt');
  expect(indexSource).toContain('rel="icon"');
  expect(indexSource).not.toContain('react.production.min.js');
  expect(indexSource).not.toContain('ReactDOM');
  expect(landingTemplateSource).toContain('<main id="main">');
  expect(landingTemplateSource).toContain('<section class="hero"');
  expect(landingTemplateSource).toContain('Hệ thống quan trắc');
  expect(landingTemplateSource).toContain('<address class="footer-contact"');
  expect(landingTemplateSource).toContain('aitogyaitogy@gmail.com');
  expect(landingJs.toString()).not.toContain('WebGLRenderer');
  expect(landingTemplateSource).toContain('href="/about"');
});

const aboutSource = readFileSync(join(__dirname, '../..', 'frontend/about.html'), 'utf8');
const aboutCss = readFileSync(join(__dirname, '../..', 'frontend/dist/about.min.css'));
const aboutJs = readFileSync(join(__dirname, '../..', 'frontend/dist/about.min.js'));

const sizes = [
  { name: 'mobile-small', width: 375, height: 667 },
  { name: 'mobile', width: 390, height: 844 },
  { name: 'landscape', width: 844, height: 390 },
  { name: 'desktop', width: 1440, height: 1000 },
  { name: 'desktop-wide', width: 1920, height: 1080 },
];

for (const size of sizes) {
test(`semantic landing is usable on ${size.name}`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.route('http://127.0.0.1:8000/', route => route.fulfill({
      contentType: 'text/html; charset=utf-8',
      body: indexSource.replaceAll('__BUILD_VERSION__', 'test'),
    }));
    await page.route('**/assets/landing.min.css*', route => route.fulfill({
      contentType: 'text/css; charset=utf-8',
      body: landingCss,
    }));
    await page.route('**/assets/landing.min.js*', route => route.fulfill({
      contentType: 'application/javascript; charset=utf-8',
      body: landingJs,
    }));
    await page.route('**/api/public/dashboard-summary', route => route.fulfill({
      contentType: 'application/json; charset=utf-8',
      body: JSON.stringify({
        stations: { total: 59, online: 52, stale: 4, offline: 3 },
        updated_at: new Date().toISOString(),
      }),
    }));
    await page.goto('/');
    await expect(page.locator('#main')).not.toBeEmpty();
    await expect(page.locator('h1')).toContainText('Hệ thống quan trắc');
    await expect(page.locator('#stations-total')).toHaveText('59');

    const contract = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth - innerWidth,
      mainWidth: document.querySelector('main').getBoundingClientRect().width,
      h1: document.querySelectorAll('h1').length,
      emptyLinks: [...document.querySelectorAll('a')].filter(link => !link.textContent.trim() && !link.getAttribute('aria-label')).length,
      undersizedTargets: [...document.querySelectorAll('a,button')].filter(element => {
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && (rect.width < 44 || rect.height < 44);
      }).map(element => element.textContent.trim() || element.getAttribute('aria-label')),
      offenders: [...document.querySelectorAll('body *')].map(element => {
        const rect = element.getBoundingClientRect();
        return { tag: element.tagName, cls: element.className?.baseVal || element.className || '', left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width) };
      }).filter(rect => rect.left < -1 || rect.right > innerWidth + 1).slice(0, 12),
    }));
    expect(contract.overflow, JSON.stringify(contract.offenders)).toBeLessThanOrEqual(1);
    expect(contract.h1).toBe(1);
    expect(contract.emptyLinks).toBe(0);
    expect(contract.undersizedTargets).toEqual([]);
    await expect(page.locator('.access-card').first()).toHaveAttribute('href', '/map');
    await expect(page.locator('.access-card').last()).toHaveAttribute('href', '/management');
    await expect(page.locator('#auth-link')).toHaveAttribute('href', '/login?return_to=%2Fmap');
    await expect(page.locator('canvas')).toHaveCount(0);

    const themeButton = page.locator('.icon-button');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await themeButton.click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.locator('.access-management h3')).toHaveCSS('color', 'rgb(240, 253, 250)');
    if (size.name === 'desktop') {
      await page.waitForTimeout(250);
      await page.screenshot({ path: 'test-results/landing-portal-dark.png', fullPage: true });
    }
    await themeButton.click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(246, 247, 248)');
    if (size.width < 768) {
      await page.locator('.menu-button').click();
      await expect(page.locator('#mobile-menu')).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(page.locator('#mobile-menu')).toBeHidden();
      await expect(page.locator('.menu-button')).toBeFocused();
    }

    const pageHeight = await page.evaluate(() => document.documentElement.scrollHeight);
    for (let top = 0; top < pageHeight; top += Math.max(300, Math.floor(size.height * .7))) {
      await page.evaluate(value => scrollTo(0, value), top);
      await page.waitForTimeout(30);
    }
    await expect(page.locator('.about-link')).toBeVisible();
    await page.evaluate(() => scrollTo(0, 0));

    await page.screenshot({
      path: `test-results/landing-premium-${size.name}.png`,
      fullPage: true,
    });
  });
}

test('public navigation reflects the session and keeps theme controls consistent', async ({ page }) => {
  let authenticated = true;
  await page.route('http://127.0.0.1:8000/', route => route.fulfill({ contentType:'text/html', body:indexSource.replaceAll('__BUILD_VERSION__', 'test') }));
  await page.route('http://127.0.0.1:8000/about', route => route.fulfill({ contentType:'text/html', body:aboutSource.replaceAll('__BUILD_VERSION__', 'test') }));
  await page.route('**/assets/landing.min.css*', route => route.fulfill({ contentType:'text/css', body:landingCss }));
  await page.route('**/assets/landing.min.js*', route => route.fulfill({ contentType:'application/javascript', body:landingJs }));
  await page.route('**/assets/about.min.css*', route => route.fulfill({ contentType:'text/css', body:aboutCss }));
  await page.route('**/assets/about.min.js*', route => route.fulfill({ contentType:'application/javascript', body:aboutJs }));
  await page.route('**/api/auth/me', route => route.fulfill(authenticated ? { json:{ username:'admin', full_name:'Administrator' } } : { status:401, json:{} }));
  await page.route('**/api/public/dashboard-summary', route => route.fulfill({ json:{ stations:{ total:0, online:0, stale:0, offline:0 } } }));

  let landingHeader;
  for (const path of ['/', '/about']) {
    await page.goto(path);
    await expect(page.locator('#auth-link')).toHaveText('Administrator');
    await expect(page.locator('#auth-link')).toHaveAttribute('href', '/management');
    await expect(page.locator('#mobile-auth-link')).toHaveText('Administrator');
    await expect(page.locator('.desktop-nav a')).toHaveText(['Trang chủ', 'Giới thiệu', 'Dashboard', 'Bản đồ']);
    const header = await page.locator('.site-header').evaluate(element => ({ background:getComputedStyle(element).backgroundColor, height:element.getBoundingClientRect().height }));
    if (landingHeader) expect(header).toEqual(landingHeader);
    else landingHeader = header;
    await expect(page.locator('#theme-toggle')).toHaveAttribute('aria-pressed', 'false');
    await page.locator('#theme-toggle').click();
    await expect(page.locator('#theme-toggle')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.theme-sun')).toHaveCSS('opacity', '1');
    await page.locator('#theme-toggle').click();
  }

  await page.goto('/');
  await expect(page.locator('.access-map')).toHaveCSS('background-color', 'rgb(229, 241, 239)');
  await page.locator('#theme-toggle').click();
  await expect(page.locator('.access-map')).toHaveCSS('background-color', 'rgb(34, 62, 71)');
  authenticated = false;
  await page.reload();
  await expect(page.locator('#auth-link')).toHaveText('Đăng nhập');
  await expect(page.locator('#auth-link')).toHaveAttribute('href', '/login?return_to=%2Fmap');
  await expect(page.locator('#mobile-auth-link')).toHaveText('Đăng nhập');
});

test('desktop story advances without shifting the fixed navigation', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route('http://127.0.0.1:8000/about', route => route.fulfill({
    contentType: 'text/html; charset=utf-8',
    body: aboutSource.replaceAll('__BUILD_VERSION__', 'test'),
  }));
  await page.route('**/assets/about.min.css*', route => route.fulfill({ contentType: 'text/css', body: aboutCss }));
  await page.route('**/assets/about.min.js*', route => route.fulfill({ contentType: 'application/javascript', body: aboutJs }));
  await page.route('**/api/public/dashboard-summary', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ stations: { total: 59, online: 52, stale: 4, offline: 3 }, updated_at: new Date().toISOString() }),
  }));
  await page.goto('/about');

  const before = await page.locator('.header-inner').boundingBox();
  const storyVisibility = async progress => {
    await page.evaluate(value => {
      const story = document.querySelector('.story');
      scrollTo(0, story.offsetTop + (story.offsetHeight - innerHeight) * value);
    }, progress);
    await page.waitForTimeout(350);
    return page.locator(`[data-story-step="${Math.min(3, Math.floor(progress * 4))}"]`).evaluate(element => Number(getComputedStyle(element).opacity));
  };
  for (const progress of [0, .125, .375, .625, .875]) {
    expect(await storyVisibility(progress), `chapter at story progress ${progress}`).toBeGreaterThan(.8);
  }
  await page.evaluate(() => {
    const story = document.querySelector('.story');
    scrollTo(0, story.offsetTop + (story.offsetHeight - innerHeight) * .72);
  });
  await page.waitForTimeout(150);

  await expect(page.locator('.story')).toHaveAttribute('data-step', '2');
  const after = await page.locator('.header-inner').boundingBox();
  expect(Math.abs(after.x - before.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(after.width - before.width)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: 'test-results/landing-story-desktop.png' });
});

test('story fallback stays compact when progressive enhancement is unavailable', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route('http://127.0.0.1:8000/about', route => route.fulfill({
    contentType: 'text/html; charset=utf-8',
    body: aboutSource.replaceAll('__BUILD_VERSION__', 'test'),
  }));
  await page.route('**/assets/about.min.css*', route => route.fulfill({ contentType: 'text/css', body: aboutCss }));
  await page.route('**/assets/about.min.js*', route => route.fulfill({ contentType: 'application/javascript', body: aboutJs }));
  await page.goto('/about');

  const geometry = await page.locator('.story').evaluate(element => ({
    height: element.getBoundingClientRect().height,
    enhanced: element.classList.contains('story-enhanced'),
  }));
  expect(geometry.enhanced).toBe(false);
  expect(geometry.height).toBeLessThan(2250);
});

 test('network error can be retried and empty data stays explicit', async ({ page }) => {
  await page.route('http://127.0.0.1:8000/', route => route.fulfill({ contentType: 'text/html', body: indexSource }));
  await page.route('**/assets/landing.min.css*', route => route.fulfill({ contentType: 'text/css', body: landingCss }));
  await page.route('**/assets/landing.min.js*', route => route.fulfill({ contentType: 'application/javascript', body: landingJs }));
  let requests = 0;
  await page.route('**/api/public/dashboard-summary', route => {
    requests++;
    return requests === 1 ? route.fulfill({ status: 503 }) : route.fulfill({ json: { stations: { total: 0, online: 0, stale: 0, offline: 0 } } });
  });
  await page.goto('/');
  await expect(page.locator('#metrics-status')).toHaveAttribute('data-state', 'error');
  await page.locator('#metrics-retry').click();
  await expect(page.locator('#metrics-status')).toHaveAttribute('data-state', 'empty');
  await expect(page.locator('#stations-total')).toHaveText('0');
  await expect(page.locator('#metric-grid')).toHaveAttribute('aria-busy', 'false');
 });
