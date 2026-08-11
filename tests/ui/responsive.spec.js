const { test, expect } = require('@playwright/test');

const viewports = [
  { name: '320x568', width: 320, height: 568 },
  { name: '390x844', width: 390, height: 844 },
  { name: '844x390', width: 844, height: 390 },
  { name: '768x1024', width: 768, height: 1024 },
  { name: '1024x768', width: 1024, height: 768 },
  { name: '1366x768', width: 1366, height: 768 },
  { name: '1920x1080', width: 1920, height: 1080 },
  { name: '2560x1440', width: 2560, height: 1440 },
  { name: '3840x2160', width: 3840, height: 2160 }
];

async function assertViewportContract(page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  const undersizedPrimaryActions = await page.locator('a.button, button:visible').evaluateAll(elements => elements
    .filter(element => {
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && getComputedStyle(element).pointerEvents !== 'none';
    })
    .filter(element => {
      const rect = element.getBoundingClientRect();
      return rect.width < 44 || rect.height < 44;
    })
    .map(element => ({ text: element.textContent.trim(), id: element.id })));
  expect(undersizedPrimaryActions).toEqual([]);
}

for (const viewport of viewports) {
  test(`landing responsive ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await page.goto('/');
    await expect(page.locator('h1')).toContainText('Cảnh báo sạt lở');
    await assertViewportContract(page);
    await expect(page).toHaveScreenshot(`landing-${viewport.name}-${testInfo.project.name}.png`, { fullPage: true });
  });

  test(`login responsive ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await page.goto('/login?return_to=/management');
    await expect(page.locator('#login-form')).toBeVisible();
    await assertViewportContract(page);
    await expect(page).toHaveScreenshot(`login-${viewport.name}-${testInfo.project.name}.png`, { fullPage: true });
  });
}

for (const viewport of viewports.slice(0, 5)) {
  test(`map shell responsive ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto('/map');
    await expect(page.locator('#map')).toBeVisible({ timeout: 30_000 });
    await assertViewportContract(page);
    if (viewport.width <= 900) {
      await expect(page.locator('#map-bottom-nav')).toBeVisible();
    }
  });
}

test('login reports required fields next to the form', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto('/login?return_to=/management');
  await page.locator('#login-submit').click();
  await expect(page.locator('#login-error')).toContainText('Vui lòng nhập');
  await expect(page.locator('#login-username')).toHaveAttribute('aria-invalid', 'true');
});
