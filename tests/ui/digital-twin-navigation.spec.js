import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const root = join(__dirname, '..', '..');
const read = file => readFileSync(join(root, file), 'utf8');
const workspaceCss = [
  'frontend/css/theme-variables.css',
  'frontend/css/map/base.css',
  'frontend/css/digital-twin.css',
  'frontend/css/map/operations-polish.css',
  'frontend/css/map/digital-twin-workspace.css',
].map(read).join('\n');

test('3D simulation is a top-level map action, not a station detail action', () => {
  const shell = read('frontend/js/templates/map/shell.js');
  const details = read('frontend/js/templates/map/station-panels.js');

  expect(shell.match(/id="btn-digital-twin"/g)).toHaveLength(1);
  expect(shell.indexOf('id="btn-digital-twin"')).toBeLessThan(shell.indexOf('id="admin-nav-btn"'));
  expect(details).not.toContain('id="btn-digital-twin"');
});

test('simulation runner exposes ready, running, stopped and completed feedback', () => {
  const template = read('frontend/js/templates/map/rescue.js');
  const controller = read('frontend/js/engine/simulation-controller.js');

  expect(template).toContain('id="dt-run-status-text"');
  expect(template).toContain('aria-live="polite"');
  for (const state of ['ready', 'running', 'stopped', 'complete']) {
    expect(controller).toContain(`_setRunUi('${state}'`);
  }
});

test('simulation entry and runner remain usable on a small phone', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.setContent(`
    <nav class="top-navbar">
      <div class="d-flex">
        <button class="navbar-hamburger" aria-label="Menu"><i></i></button>
        <a class="brand-text"><i></i><span>Landslide Monitor</span></a>
        <button id="btn-digital-twin" class="btn map-simulation-nav"><i></i> Mô phỏng 3D</button>
        <a id="admin-nav-btn" class="btn" style="display:inline-flex"><i></i> Quản trị</a>
      </div>
      <div class="d-flex"><button id="auth-btn" class="btn"><i></i> admin</button></div>
    </nav>
    <div class="dt-overlay-container dt-active">
      <div id="dt-main">
        <aside id="dt-panel" class="dt-panel-open">
          <div class="dt-run-card" data-state="ready">
            <div class="dt-run-status-line"><i></i><span>Sẵn sàng chạy mô phỏng</span></div>
            <div class="dt-panel-actions">
              <button class="dt-btn-primary">Chạy mô phỏng</button>
              <button class="dt-btn-secondary">Đặt lại tham số</button>
            </div>
          </div>
        </aside>
      </div>
    </div>`);
  await page.addStyleTag({ content: workspaceCss });

  const metrics = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - innerWidth,
    navTarget: document.getElementById('btn-digital-twin').getBoundingClientRect(),
    panel: document.getElementById('dt-panel').getBoundingClientRect(),
    buttons: [...document.querySelectorAll('.dt-panel-actions button')].map(el => el.getBoundingClientRect().height),
  }));

  expect(metrics.overflow).toBeLessThanOrEqual(1);
  expect(metrics.navTarget.width).toBeGreaterThanOrEqual(44);
  expect(metrics.navTarget.height).toBeGreaterThanOrEqual(40);
  expect(metrics.panel.width).toBeLessThanOrEqual(320);
  expect(metrics.buttons.every(height => height >= 44)).toBe(true);
});
