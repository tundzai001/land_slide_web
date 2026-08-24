const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const indexSource = readFileSync(join(__dirname, '..', '..', 'frontend/index.html'), 'utf8');
const landingCss = readFileSync(join(__dirname, '..', '..', 'frontend/dist/landing.min.css'));
const landingJs = readFileSync(join(__dirname, '..', '..', 'frontend/dist/landing.min.js'));

test('index is semantic and progressively enhanced without React', async () => {
  expect(indexSource).toContain('<main id="main">');
  expect(indexSource).toContain('<section class="hero"');
  expect(indexSource).toContain('Nhìn thấy chuyển động');
  expect(indexSource).toContain('rel="canonical"');
  expect(indexSource).not.toContain('react.production.min.js');
  expect(indexSource).not.toContain('ReactDOM');
  expect(landingCss.toString()).toContain('.story-enhanced .story-stage');
  expect(landingJs.toString()).toContain('story-enhanced');
  expect(landingJs.toString()).toContain('--stage-scale');
});

const sizes = [
  { name: 'mobile-small', width: 375, height: 667 },
  { name: 'mobile', width: 390, height: 844 },
  { name: 'landscape', width: 844, height: 390 },
  { name: 'desktop', width: 1440, height: 1000 },
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
        updated_at: '2026-08-14T12:00:00+07:00',
      }),
    }));
    await page.goto('/');
    await expect(page.locator('#main')).not.toBeEmpty();
    await expect(page.locator('h1')).toContainText('Nhìn thấy chuyển động');
    await expect(page.locator('#stations-total')).toHaveText('59');

    const contract = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth - innerWidth,
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

    const themeButton = page.locator('.icon-button');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await themeButton.click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await themeButton.click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    if (size.width < 768) {
      await page.locator('.menu-button').click();
      await expect(page.locator('#mobile-menu')).toBeVisible();
      await page.locator('.menu-button').click();
      await expect(page.locator('#mobile-menu')).toBeHidden();
    }

    const pageHeight = await page.evaluate(() => document.documentElement.scrollHeight);
    for (let top = 0; top < pageHeight; top += Math.max(300, Math.floor(size.height * .7))) {
      await page.evaluate(value => scrollTo(0, value), top);
      await page.waitForTimeout(30);
    }
    await expect(page.locator('.final-cta')).toHaveClass(/is-visible/);
    await page.evaluate(() => scrollTo(0, 0));

    await page.screenshot({
      path: `test-results/landing-premium-${size.name}.png`,
      fullPage: true,
    });
  });
}

test('desktop story advances without shifting the fixed navigation', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route('http://127.0.0.1:8000/', route => route.fulfill({
    contentType: 'text/html; charset=utf-8',
    body: indexSource.replaceAll('__BUILD_VERSION__', 'test'),
  }));
  await page.route('**/assets/landing.min.css*', route => route.fulfill({ contentType: 'text/css', body: landingCss }));
  await page.route('**/assets/landing.min.js*', route => route.fulfill({ contentType: 'application/javascript', body: landingJs }));
  await page.route('**/api/public/dashboard-summary', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ stations: { total: 59, online: 52, stale: 4, offline: 3 }, updated_at: '2026-08-14T12:00:00+07:00' }),
  }));
  await page.goto('/');

  const before = await page.locator('.header-inner').boundingBox();
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
