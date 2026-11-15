const { test, expect } = require('./coverage-fixture');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const source = file => readFileSync(join(__dirname, '../..', file), 'utf8');

for (const [view, template] of [
  ['map', 'frontend/js/templates/map/shell.js'],
  ['admin', 'frontend/js/templates/admin/shell.js'],
]) {
  test(`${view} theme control animates and updates accessibility state`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('theme', 'light'));
    await page.route('https://theme.test/', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><html data-theme="light"><body><div id="app"></div></body></html>' }));
    await page.goto('https://theme.test/');
    await page.addStyleTag({ content: source('frontend/dist/app-base.min.css') + source(`frontend/dist/${view}.min.css`) });
    await page.addScriptTag({ content: source(template) });
    await page.evaluate(() => { document.getElementById('app').innerHTML = window.LegacyTemplateParts.shell; });
    await page.addScriptTag({ content: source('frontend/js/theme-manager.js') });
    const button = page.locator('#theme-toggle-btn');
    await expect(button.locator('svg')).toHaveCount(2);
    await button.click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(button).toHaveAttribute('aria-label', 'Chuyển giao diện sáng');
    await expect(button).toHaveAttribute('aria-pressed', 'true');
    await expect.poll(() => button.locator('.theme-sun').evaluate(el => getComputedStyle(el).opacity)).toBe('1');
    await page.screenshot({ path: `test-results/${view}-theme-control.png` });
    await button.click();
    await expect(button).toHaveAttribute('aria-pressed', 'false');
  });
}
