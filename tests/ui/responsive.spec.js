const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const mapPath = process.env.MAP_PATH || '/map';

const gnssPanelCss = [
  'frontend/css/theme-variables.css',
  'frontend/css/shell.css',
  'frontend/css/map/base.css',
  'frontend/css/map/gnss.css',
  'frontend/css/map-responsive.css',
].map(file => readFileSync(join(__dirname, '..', '..', file), 'utf8')).join('\n');

const autoAdjustmentCss = [
  'frontend/css/theme-variables.css',
  'frontend/css/components.css',
  'frontend/css/admin/base.css',
  'frontend/css/admin/system-settings.css',
  'frontend/css/admin/pi-wizard.css',
  'frontend/css/admin-responsive.css',
].map(file => readFileSync(join(__dirname, '..', '..', file), 'utf8')).join('\n');

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

for (const viewport of viewports.filter(({ width }) => [390, 768, 1366].includes(width))) {
  test(`automatic adjustment controls stay aligned ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const options = ['Đập 1', 'Đập 4', 'Cả 2 đập'].map((name, index) => `
      <div class="form-check auto-adjustment-cluster-option">
        <input class="form-check-input auto-adj-cluster-cb" type="checkbox" id="cluster-${index}" ${index === 0 ? 'checked' : ''}>
        <label class="form-check-label" for="cluster-${index}"><span class="auto-adjustment-cluster-icon">◎</span><span>${name}</span></label>
      </div>`).join('');
    await page.setContent(`<!doctype html><html data-theme="light" data-app-view="admin"><head><style>${autoAdjustmentCss}</style></head><body>
      <main style="width:min(720px,100%);padding:16px;margin:auto"><section class="config-section auto-adjustment-card">
        <header class="section-header auto-adjustment-header"><span class="auto-adjustment-icon">◷</span><div class="auto-adjustment-heading"><h5>Bình sai tự động</h5><p>Thiết lập cụm GNSS và lịch xử lý định kỳ</p></div><div class="form-check form-switch auto-adjustment-switch"><input class="form-check-input" type="checkbox" checked><label class="form-check-label">Kích hoạt</label></div></header>
        <div class="sensor-config-body auto-adjustment-body"><div class="row auto-adjustment-grid"><div class="col-md-6"><label class="form-label auto-adjustment-field-label">Chọn cụm chạy tự động</label><div class="auto-adjustment-cluster-list">${options}</div></div><div class="col-md-6"><div class="auto-adjustment-control-stack"><label class="form-label auto-adjustment-field-label">Tần suất</label><div class="auto-adjustment-input-wrap"><select class="form-select"><option>Mỗi 4 giờ</option></select></div><label class="form-label auto-adjustment-field-label">Giờ bắt đầu</label><div class="auto-adjustment-input-wrap auto-adjustment-hour-wrap"><input class="form-control" value="1"><span>giờ</span></div></div></div></div><div class="auto-adjustment-schedule-block"><label class="form-label auto-adjustment-field-label">Lịch chạy trong ngày</label><div class="auto-adjustment-schedule"><span class="auto-adjustment-time-chip">◷ 01:00</span><span class="auto-adjustment-time-chip">◷ 05:00</span><span class="auto-adjustment-time-chip">◷ 09:00</span></div></div></div>
      </section></main></body></html>`);

    const contract = await page.locator('.auto-adjustment-card').evaluate(card => {
      const toggle = card.querySelector('.auto-adjustment-switch .form-check-input').getBoundingClientRect();
      const checkboxes = Array.from(card.querySelectorAll('.auto-adj-cluster-cb')).map(input => input.getBoundingClientRect());
      const options = Array.from(card.querySelectorAll('.auto-adjustment-cluster-option')).map(option => option.getBoundingClientRect());
      return {
        pageOverflow: document.documentElement.scrollWidth - innerWidth,
        cardOverflow: card.scrollWidth - card.clientWidth,
        toggle: { width: toggle.width, height: toggle.height },
        checkboxSizes: checkboxes.map(rect => ({ width: rect.width, height: rect.height })),
        optionsDoNotOverlap: options.every((rect, index) => index === 0 || rect.top >= options[index - 1].bottom),
      };
    });
    expect(contract.pageOverflow).toBeLessThanOrEqual(1);
    expect(contract.cardOverflow).toBeLessThanOrEqual(1);
    expect(contract.toggle).toEqual({ width: 38, height: 22 });
    expect(contract.checkboxSizes).toEqual(Array(3).fill({ width: 18, height: 18 }));
    expect(contract.optionsDoNotOverlap).toBe(true);
  });
}

for (const viewport of viewports.slice(0, 5)) {
  test(`map shell responsive ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto(mapPath);
    await expect(page.locator('#map')).toBeVisible({ timeout: 30_000 });
    await assertViewportContract(page);
    if (viewport.width <= 900) {
      await expect(page.locator('#map-bottom-nav')).toBeVisible();
    }
  });
}

for (const viewport of viewports) {
  test(`GNSS panel remains viewport-bound ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const items = Array.from({ length: 24 }, (_, index) =>
      `<div class="adv-item"><span class="adv-label">Value ${index + 1}</span><span class="adv-value">--</span></div>`
    ).join('');
    await page.setContent(`<!doctype html><html data-app-view="map"><head><style>${gnssPanelCss}</style></head><body>
      <div id="app-root"><aside id="gnss-advanced-sidepanel" class="gnss-advanced-sidepanel active">
        <header class="sidepanel-header"><h6>Advanced GNSS</h6><button class="sidepanel-close">x</button></header>
        <div class="sidepanel-body"><div class="adv-column-left">${items}</div></div>
      </aside></div></body></html>`);

    const geometry = await page.locator('#gnss-advanced-sidepanel').evaluate(element => {
      const rect = element.getBoundingClientRect();
      const body = element.querySelector('.sidepanel-body');
      return {
        position: getComputedStyle(element).position,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        documentOverflow: document.documentElement.scrollHeight - innerHeight,
        bodyOverflow: getComputedStyle(body).overflowY,
        bodyCanScroll: body.scrollHeight > body.clientHeight,
      };
    });
    expect(geometry.position).toBe('fixed');
    expect(geometry.top).toBeGreaterThanOrEqual(0);
    expect(geometry.right).toBeLessThanOrEqual(viewport.width + 1);
    expect(geometry.bottom).toBeLessThanOrEqual(viewport.height + 1);
    expect(geometry.documentOverflow).toBeLessThanOrEqual(1);
    expect(geometry.bodyOverflow).toBe('auto');
    if (viewport.height <= 1440) expect(geometry.bodyCanScroll).toBe(true);
  });
}

test('login reports required fields next to the form', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto('/login?return_to=/management');
  await page.locator('#login-submit').click();
  await expect(page.locator('#login-error')).toContainText('Vui lòng nhập');
  await expect(page.locator('#login-username')).toHaveAttribute('aria-invalid', 'true');
});
