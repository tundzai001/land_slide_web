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
  'frontend/css/map/premium-light.css',
].map(file => readFileSync(join(__dirname, '..', '..', file), 'utf8')).join('\n');

const autoAdjustmentCss = [
  'frontend/css/theme-variables.css',
  'frontend/css/components.css',
  'frontend/css/admin/base.css',
  'frontend/css/admin/configuration.css',
  'frontend/css/admin/pi-wizard.css',
  'frontend/css/admin-responsive.css',
  'frontend/css/admin/premium-light.css',
].map(file => readFileSync(join(__dirname, '..', '..', file), 'utf8')).join('\n');

const mapControlsCss = [
  'frontend/css/theme-variables.css',
  'frontend/css/map/base.css',
  'frontend/css/map/station-panels.css',
  'frontend/css/map/tools.css',
  'frontend/css/rescue-markers.css',
  'frontend/css/map-responsive.css',
  'frontend/css/map/premium-light.css',
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

async function installLocalMapAssets(page) {
  if (process.env.LOCAL_MAP_BUNDLE !== '1') return;
  await page.route('**/assets/map.min.css*', route => route.fulfill({
    contentType: 'text/css; charset=utf-8',
    body: readFileSync(join(__dirname, '..', '..', 'frontend/dist/map.min.css')),
  }));
  await page.route('**/assets/map-app.min.js*', route => route.fulfill({
    contentType: 'application/javascript; charset=utf-8',
    body: readFileSync(join(__dirname, '..', '..', 'frontend/dist/map-app.min.js')),
  }));
}

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
    await expect(page.locator('h1')).toContainText('Nhìn thấy chuyển động');
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
    await installLocalMapAssets(page);
    await page.goto(mapPath);
    await expect(page.locator('#map')).toBeVisible({ timeout: 30_000 });
    await assertViewportContract(page);
    if (viewport.width <= 900) {
      await expect(page.locator('#map-bottom-nav')).toBeVisible();
    }
  });
}

test('desktop map sidebars open from hamburger and station selection', async ({ page }) => {
  test.setTimeout(150_000);
  await page.setViewportSize({ width: 1366, height: 768 });
  await installLocalMapAssets(page);
  await page.route('**/api/stations', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 1,
      name: 'Desktop test station',
      station_code: 'DESKTOP-1',
      status: 'online',
      risk_level: 'LOW',
      location: { lat: 21.5, lon: 104.5 },
    }]),
  }));
  await page.route('**/api/stations/1/detail**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      id: 1,
      name: 'Desktop test station',
      station_code: 'DESKTOP-1',
      status: 'online',
      risk_level: 'LOW',
      sensors: {},
    }),
  }));
  await page.goto(mapPath);
  await expect(page.locator('#map')).toBeVisible({ timeout: 30_000 });

  const stationSidebar = page.locator('#station-list-sidebar');
  const hamburger = page.locator('#navbar-hamburger-btn');
  await expect(stationSidebar).toHaveAttribute('aria-hidden', 'true');
  await hamburger.click();
  await expect(stationSidebar).toHaveAttribute('aria-hidden', 'false');
  await expect(hamburger).toHaveAttribute('aria-expanded', 'true');
  await expect(stationSidebar).toBeInViewport();

  const firstMarker = page.locator('.leaflet-marker-pane .custom-map-marker').first();
  await expect(firstMarker).toBeVisible();
  await firstMarker.click();
  const detailSidebar = page.locator('#detail-sidebar');
  await expect(detailSidebar).toHaveClass(/active/);
  await expect(detailSidebar).toHaveAttribute('aria-hidden', 'false');
  const detailGeometry = await detailSidebar.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return {
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      inlineStyle: element.getAttribute('style'),
      position: style.position,
      inset: { top: style.top, right: style.right, bottom: style.bottom, left: style.left },
      transform: style.transform,
      translate: style.translate,
      visibility: style.visibility,
      opacity: style.opacity,
      pointerEvents: style.pointerEvents,
      offsetParent: element.offsetParent?.id || element.offsetParent?.className || null,
    };
  });
  expect(detailGeometry.rect.y).toBeGreaterThanOrEqual(0);
  expect(detailGeometry.rect.y).toBeLessThan(100);
  expect(detailGeometry.rect.y + detailGeometry.rect.height).toBeLessThanOrEqual(769);
  await expect(detailSidebar).toBeInViewport();

  await hamburger.click();
  await expect(stationSidebar).toHaveAttribute('aria-hidden', 'true');
  await hamburger.click();
  await expect(stationSidebar).toHaveAttribute('aria-hidden', 'false');
  await expect(stationSidebar).toBeInViewport();

  const gnssCard = page.locator('#sensor-card-gnss');
  const gnssPanel = page.locator('#gnss-advanced-sidepanel');
  await gnssCard.dblclick();
  await expect(gnssPanel).toHaveClass(/active/);
  await expect(gnssPanel).toHaveAttribute('aria-hidden', 'false');
  await expect(gnssCard).toHaveAttribute('aria-expanded', 'true');
  await expect(gnssPanel).toBeInViewport();
  const gnssGeometry = await gnssPanel.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const close = element.querySelector('#gnss-sidepanel-close');
    const closeRect = close.getBoundingClientRect();
    const topElement = document.elementFromPoint(
      closeRect.left + closeRect.width / 2,
      closeRect.top + closeRect.height / 2,
    );
    const style = getComputedStyle(element);
    return {
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      closeRect: { x: closeRect.x, y: closeRect.y, width: closeRect.width, height: closeRect.height },
      display: style.display,
      position: style.position,
      zIndex: style.zIndex,
      visibility: style.visibility,
      opacity: style.opacity,
      pointerEvents: style.pointerEvents,
      topElement: `${topElement?.tagName || ''}#${topElement?.id || ''}.${topElement?.className || ''}`,
      closeButtonOnTop: topElement?.closest('#gnss-sidepanel-close')?.id || '',
    };
  });
  console.log('GNSS geometry:', gnssGeometry);
  expect(gnssGeometry.rect.width).toBeGreaterThan(280);
  expect(gnssGeometry.rect.height).toBeGreaterThan(300);
  expect(gnssGeometry.closeButtonOnTop).toBe('gnss-sidepanel-close');
  await page.locator('#gnss-sidepanel-close').click();
  await expect(gnssPanel).toHaveAttribute('aria-hidden', 'true');

  await page.locator('#btn-show-charts').click();
  const chartsPanel = page.locator('#charts-panel');
  await expect(chartsPanel).toHaveClass(/active/);
  await expect(chartsPanel).toHaveAttribute('aria-hidden', 'false');
  await expect(page.locator('#charts-station-context')).toContainText('Desktop test station');
  const panelGeometry = await page.evaluate(() => {
    const chartRect = document.getElementById('charts-panel').getBoundingClientRect();
    const detailRect = document.getElementById('detail-sidebar').getBoundingClientRect();
    return {
      chart: { left: chartRect.left, top: chartRect.top, right: chartRect.right, bottom: chartRect.bottom },
      detail: { left: detailRect.left, top: detailRect.top, right: detailRect.right, bottom: detailRect.bottom },
      overflow: document.documentElement.scrollWidth - innerWidth,
    };
  });
  expect(panelGeometry.chart.left).toBeGreaterThanOrEqual(8);
  expect(panelGeometry.chart.top).toBeGreaterThanOrEqual(56);
  expect(panelGeometry.chart.right).toBeLessThanOrEqual(panelGeometry.detail.left - 8);
  expect(panelGeometry.chart.bottom).toBeLessThanOrEqual(768);
  expect(panelGeometry.overflow).toBeLessThanOrEqual(1);
  await page.screenshot({ path: 'test-results/map-layout-desktop.png' });
  await page.locator('#close-charts-btn').click();
  await expect(chartsPanel).toHaveAttribute('aria-hidden', 'true');
});

test('mobile chart workspace replaces detail sheet without overflow', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await installLocalMapAssets(page);
  await page.route('**/api/stations', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 1,
      name: 'Mobile test station',
      station_code: 'MOBILE-1',
      status: 'online',
      risk_level: 'LOW',
      location: { lat: 21.5, lon: 104.5 },
    }]),
  }));
  await page.route('**/api/stations/1/detail**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      id: 1,
      name: 'Mobile test station',
      station_code: 'MOBILE-1',
      status: 'online',
      risk_level: 'LOW',
      sensors: {},
    }),
  }));
  await page.goto(mapPath);
  await expect(page.locator('#map')).toBeVisible({ timeout: 30_000 });
  await page.locator('.leaflet-marker-pane .custom-map-marker').first().click();
  await expect(page.locator('#detail-sidebar')).toHaveClass(/active/);
  await page.locator('#btn-show-charts').click();

  const chartsPanel = page.locator('#charts-panel');
  await expect(chartsPanel).toHaveClass(/active/);
  await expect(page.locator('#detail-sidebar')).toHaveAttribute('aria-hidden', 'true');
  const geometry = await chartsPanel.evaluate(element => {
    const rect = element.getBoundingClientRect();
    return {
      left: rect.left,
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
      overflow: document.documentElement.scrollWidth - innerWidth,
    };
  });
  expect(geometry.left).toBeGreaterThanOrEqual(8);
  expect(geometry.top).toBeGreaterThanOrEqual(52);
  expect(geometry.right).toBeLessThanOrEqual(390);
  expect(geometry.bottom).toBeLessThanOrEqual(782);
  expect(geometry.overflow).toBeLessThanOrEqual(1);
  await page.screenshot({ path: 'test-results/map-layout-mobile.png' });
});

test('rescue request surface is light, readable and viewport-bound', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installLocalMapAssets(page);
  await page.goto(mapPath);
  await expect(page.locator('#map')).toBeVisible({ timeout: 30_000 });
  await page.locator('#btn-guest-rescue').click();

  const modal = page.locator('#guestRescueModal .modal-content');
  await expect(modal).toBeVisible();
  const contract = await modal.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    const bodyStyle = getComputedStyle(element.querySelector('.modal-body'));
    return {
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
      pageOverflow: document.documentElement.scrollWidth - innerWidth,
      surface: style.backgroundColor,
      bodySurface: bodyStyle.backgroundColor,
    };
  });
  expect(contract.left).toBeGreaterThanOrEqual(8);
  expect(contract.right).toBeLessThanOrEqual(390);
  expect(contract.top).toBeGreaterThanOrEqual(0);
  expect(contract.bottom).toBeLessThanOrEqual(844);
  expect(contract.pageOverflow).toBeLessThanOrEqual(1);
  expect(contract.surface).toBe('rgb(255, 255, 255)');
  expect(contract.bodySurface).toBe('rgb(247, 249, 252)');
  await page.screenshot({ path: 'test-results/map-rescue-mobile.png' });
});

test('desktop map controls remain stable, separated and readable', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.setContent(`<!doctype html><html data-theme="light" data-app-view="map"><head><style>${mapControlsCss}</style></head><body>
    <nav class="top-navbar"><div></div><div><button id="auth-btn" class="btn btn-primary"><i></i><span>admin</span></button></div></nav>
    <aside class="station-list-sidebar"><button class="sidebar-close-tab" aria-label="Thu gọn"><i></i></button></aside>
    <div class="custom-map-controls">
      <div class="heatmap-toggle-wrap"><button class="heatmap-toggle-btn" id="heatmap-toggle" aria-label="Heatmap"><i></i></button></div>
      <span class="map-control-divider"></span>
      <button class="map-ctrl-btn" id="map-zoom-in" aria-label="Phóng to"></button>
      <button class="map-ctrl-btn" id="map-zoom-out" aria-label="Thu nhỏ"></button>
    </div>
    <button class="rescue-fab" id="btn-guest-rescue"><span class="rescue-fab-icon"></span><span class="rescue-fab-label">Yêu cầu cứu hộ</span></button>
  </body></html>`);

  const closeTab = page.locator('.sidebar-close-tab');
  const beforeHover = await closeTab.boundingBox();
  await closeTab.hover();
  const afterHover = await closeTab.boundingBox();
  expect(Math.abs(afterHover.y - beforeHover.y)).toBeLessThanOrEqual(0.5);
  expect(afterHover.width).toBe(beforeHover.width);

  const geometry = await page.evaluate(() => {
    const rail = document.querySelector('.custom-map-controls').getBoundingClientRect();
    const heat = document.querySelector('#heatmap-toggle').getBoundingClientRect();
    const zoom = document.querySelector('#map-zoom-in').getBoundingClientRect();
    const rescue = document.querySelector('#btn-guest-rescue').getBoundingClientRect();
    const authStyle = getComputedStyle(document.querySelector('#auth-btn'));
    return {
      heatInsideRail: heat.top >= rail.top && heat.bottom <= rail.bottom,
      heatZoomGap: zoom.top - heat.bottom,
      railRescueGap: rail.top >= rescue.bottom ? rail.top - rescue.bottom : rescue.top - rail.bottom,
      authColor: authStyle.color,
      authBackground: authStyle.backgroundColor,
    };
  });
  expect(geometry.heatInsideRail).toBe(true);
  expect(geometry.heatZoomGap).toBeGreaterThanOrEqual(4);
  expect(geometry.railRescueGap).toBeGreaterThanOrEqual(12);
  expect(geometry.authColor).toBe('rgb(255, 255, 255)');
  expect(geometry.authBackground).toBe('rgb(37, 99, 235)');
});

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
