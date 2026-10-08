const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const source = file => readFileSync(join(__dirname, '../..', file), 'utf8');

async function mount(page, width) {
  await page.setViewportSize({ width, height: 900 });
  await page.setContent('<html data-theme="light"><body><div id="projects-content-area"></div><div id="action-buttons-container"></div></body></html>');
  await page.addStyleTag(process.env.BOOTSTRAP_TEST_CSS ? { path: process.env.BOOTSTRAP_TEST_CSS } : { url: 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' });
  await page.addStyleTag({ content: ['theme-variables', 'admin/configuration', 'admin/premium-light'].map(name => source(`frontend/css/${name}.css`)).join('\n') });
  for (const file of ['templates/admin/gnss-project-modals', 'admin/core', 'admin/auto-adjustment', 'admin/projects', 'admin/project-config']) {
    await page.addScriptTag({ content: source(`frontend/js/${file}.js`) });
  }
  await page.evaluate(() => {
    document.body.insertAdjacentHTML('beforeend', window.LegacyTemplateParts['gnss-project-modals']);
    window.bootstrap = { Modal: class {
      constructor(element) { this.element = element; window.activeModal = this; }
      show() { this.element.style.display = 'block'; this.element.classList.add('show'); }
      hide() { this.element.style.display = 'none'; }
      static getInstance() { return window.activeModal; }
    } };
    window.savedRequests = [];
    window.toast = { warning() {}, success() {}, error(message) { window.lastError = message; } };
    window.fetch = async (url, options = {}) => {
      if (options.body) {
        window.savedRequests.push(JSON.parse(options.body));
        return new Response('{}', { status: 200 });
      }
      return new Response(JSON.stringify([
        { id: 1, location: { lat: 22, lon: 103 } },
        { id: 2, location: { lat: 24, lon: 105 } },
      ]), { status: 200 });
    };
    window.adminManager = Object.create(window.AdminManager.prototype);
    Object.assign(window.adminManager, {
      currentUserRole: 'admin', token: 'test-token',
      projectsData: [{ id: 7, name: 'Sín Quyền', project_code: 'SQ', location: { address: 'Lào Cai', map_mode: 'manual', lat: 21.5, lon: 104.5 } }],
      fetchCorsStations: async () => {}, addClusterRow() {}, loadAutoAdjustmentConfig() {}, loadProjects: async () => {},
    });
  });
}

for (const width of [1280, 390]) {
  test(`admin saves manual/auto map positions and validates inline at ${width}px`, async ({ page }) => {
    await mount(page, width);
    await page.evaluate(() => window.adminManager.openProjectConfigModal(7));
    await expect(page.locator('#project-config-map-mode')).toHaveValue('manual');
    await expect(page.locator('#project-config-map-lat')).toHaveValue('21.5');
    await expect(page.locator('#project-config-location')).toHaveValue('Lào Cai');
    await page.locator('#project-config-map-lat').fill('91');
    await page.locator('#project-config-save-btn').click();
    await expect(page.locator('#project-config-map-error')).toBeVisible();
    await expect(page.locator('#project-config-map-lat')).toBeFocused();
    expect(await page.evaluate(() => window.savedRequests)).toEqual([]);
    await page.locator('#project-config-map-lat').fill('22.123456');
    await page.locator('#project-config-map-lon').fill('103.987654');
    await page.locator('.project-map-position').first().screenshot({ path: `test-results/project-map-settings-${width}.png` });
    await page.evaluate(() => { document.documentElement.dataset.theme = 'dark'; });
    await page.locator('.project-map-position').first().screenshot({ path: `test-results/project-map-settings-dark-${width}.png` });
    await page.locator('#project-config-save-btn').click();
    expect((await page.evaluate(() => window.savedRequests))[0].map_position).toEqual({ mode: 'manual', lat: 22.123456, lon: 103.987654 });
    await page.evaluate(() => window.adminManager.openProjectConfigModal(7));
    await page.locator('#project-config-map-mode').selectOption('auto');
    await expect(page.locator('#project-config-map-lat')).toHaveValue('23.00000000');
    await expect(page.locator('#project-config-map-lat')).toHaveAttribute('readonly', '');
    await page.locator('#project-config-save-btn').click();
    expect((await page.evaluate(() => window.savedRequests))[1].map_position).toEqual({ mode: 'auto' });
    await page.evaluate(() => window.adminManager.openCreateProjectModal());
    await page.locator('#project-code').fill('NEW');
    await page.locator('#project-name').fill('Dự án mới');
    await page.locator('#project-map-mode').selectOption('manual');
    await page.locator('#project-map-lat').fill('20');
    await page.locator('#project-map-lon').fill('106');
    await page.locator('#project-save-btn').click();
    expect((await page.evaluate(() => window.savedRequests))[2].map_position).toEqual({ mode: 'manual', lat: 20, lon: 106 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test('project cards escape stored HTML and hide write controls from operators', async ({ page }) => {
  await mount(page, 1280);
  await page.evaluate(() => {
    const payload = '<img src=x onerror="window.injected=true">';
    window.adminManager.projectsData = [{ id: 7, name: payload, project_code: payload, description: payload, location: { address: payload }, station_count: 2 }];
    window.adminManager.renderProjects();
  });
  await expect(page.locator('#projects-content-area img')).toHaveCount(0);
  await expect(page.locator('.project-edit-btn')).toBeVisible();
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
  await page.evaluate(() => { window.adminManager.currentUserRole = 'operator'; window.adminManager.renderProjects(); });
  await expect(page.locator('.project-edit-btn')).toHaveCount(0);
  await expect(page.locator('#action-buttons-container button')).toHaveCount(0);
});
