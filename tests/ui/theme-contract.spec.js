const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const root = join(__dirname, '..', '..');
const source = file => readFileSync(join(root, file), 'utf8');
const cssBundle = files => files.map(source).join('\n');

const adminCss = cssBundle([
  'frontend/css/theme-variables.css', 'frontend/css/theme-transition.css',
  'frontend/css/components.css', 'frontend/css/shell.css', 'frontend/css/performance.css',
  'frontend/css/admin/base.css', 'frontend/css/admin/effects-theme.css',
  'frontend/css/admin/configuration.css', 'frontend/css/admin/pi-wizard.css',
  'frontend/css/admin-responsive.css', 'frontend/css/admin/pi-devices.css',
  'frontend/css/admin/incidents.css', 'frontend/css/admin/simulations.css',
  'frontend/css/admin/premium-light.css',
]);

const mapCss = cssBundle([
  'frontend/css/theme-variables.css', 'frontend/css/theme-transition.css',
  'frontend/css/components.css', 'frontend/css/shell.css', 'frontend/css/performance.css',
  'frontend/css/map/base.css', 'frontend/css/map/station-panels.css',
  'frontend/css/map/analysis.css', 'frontend/css/map/effects-theme.css',
  'frontend/css/map/tools.css', 'frontend/css/map/gnss.css',
  'frontend/css/digital-twin.css', 'frontend/css/rescue-markers.css',
  'frontend/css/map-responsive.css', 'frontend/css/map/premium-light.css',
  'frontend/css/map/digital-twin-workspace.css', 'frontend/css/map/digital-twin-results.css',
  'frontend/css/map/incidents.css', 'frontend/css/map/operations-polish.css',
]);

async function computedTheme(page, selectors, tokens) {
  return page.evaluate(({ selectors, tokens }) => {
    const resolveToken = token => {
      const probe = document.createElement('i');
      probe.style.backgroundColor = `var(${token})`;
      document.body.appendChild(probe);
      const value = getComputedStyle(probe).backgroundColor;
      probe.remove();
      return value;
    };
    return {
      boxes: Object.fromEntries(Object.entries(selectors).map(([name, selector]) => [name, getComputedStyle(document.querySelector(selector)).backgroundColor])),
      tokens: Object.fromEntries(tokens.map(token => [token, resolveToken(token)])),
    };
  }, { selectors, tokens });
}

test('dark admin boxes resolve through the shared semantic contract', async ({ page }) => {
  await page.setContent(`<!doctype html><html data-theme="dark" data-app-view="admin"><head><style>${adminCss}</style></head><body class="admin-page">
    <div class="card" id="card"></div><div class="modal-content" id="modal"></div>
    <div class="user-profile"></div><div class="breadcrumb"></div><div class="project-config-skeleton"></div>
    <div class="pi-list-head"></div><div class="pi-device-row"><span class="pi-device-status is-pending"></span></div>
    <div class="modal-footer"></div><div class="clear-db-body"></div><div class="clear-db-option"></div>
    <div class="bg-light" id="bootstrap-light"></div><table><thead class="table-light"><tr><th>x</th></tr></thead></table>
    <div id="stationConfigModal"><div class="sensor-config-card"></div></div>
    <div class="gnss-offset-result"><div class="gnss-offset-grid"><div></div></div></div>
  </body></html>`);

  const result = await computedTheme(page, {
    card: '#card', modal: '#modal', profile: '.user-profile', breadcrumb: '.breadcrumb',
    skeleton: '.project-config-skeleton', piRow: '.pi-device-row', clearBody: '.clear-db-body',
    stationCard: '#stationConfigModal .sensor-config-card', offsetCell: '.gnss-offset-grid > div',
    piHead: '.pi-list-head', modalFooter: '.modal-footer', clearOption: '.clear-db-option',
    bootstrapLight: '#bootstrap-light', tableLight: '.table-light', pending: '.pi-device-status',
  }, ['--surface-default', '--surface-subtle', '--state-warning-bg']);

  for (const key of ['card', 'modal', 'profile', 'breadcrumb', 'skeleton', 'piRow', 'clearBody', 'stationCard', 'offsetCell']) {
    expect(result.boxes[key], key).toBe(result.tokens['--surface-default']);
  }
  for (const key of ['piHead', 'modalFooter', 'clearOption', 'bootstrapLight', 'tableLight']) {
    expect(result.boxes[key], key).toBe(result.tokens['--surface-subtle']);
  }
  expect(result.boxes.pending).toBe(result.tokens['--state-warning-bg']);
});

test('dark map status boxes use semantic state surfaces', async ({ page }) => {
  await page.setContent(`<!doctype html><html data-theme="dark" data-app-view="map"><head><style>${mapCss}</style></head><body>
    <span class="gnss-fix-badge GNSS_RTK_FIXED"></span>
    <span class="gnss-fix-badge GNSS_RTK_FLOAT"></span>
    <span class="gnss-fix-badge GNSS_INVALID"></span>
    <span class="sensor-offline-badge"></span>
    <div class="reliability-note reliability-note-warning"></div>
    <div class="analysis-source-note"></div>
    <span class="consensus-badge consensus-strong"></span>
    <span class="consensus-badge consensus-partial"></span>
    <span class="consensus-badge consensus-conflict"></span>
  </body></html>`);

  const result = await computedTheme(page, {
    fixed: '.GNSS_RTK_FIXED', float: '.GNSS_RTK_FLOAT', invalid: '.GNSS_INVALID',
    offline: '.sensor-offline-badge', warning: '.reliability-note-warning', info: '.analysis-source-note',
    strong: '.consensus-strong', partial: '.consensus-partial', conflict: '.consensus-conflict',
  }, ['--state-success-bg', '--state-warning-bg', '--state-danger-bg', '--state-info-bg', '--state-neutral-bg']);

  expect(result.boxes.fixed).toBe(result.tokens['--state-success-bg']);
  expect(result.boxes.strong).toBe(result.tokens['--state-success-bg']);
  for (const key of ['float', 'warning', 'partial']) expect(result.boxes[key], key).toBe(result.tokens['--state-warning-bg']);
  for (const key of ['invalid', 'conflict']) expect(result.boxes[key], key).toBe(result.tokens['--state-danger-bg']);
  expect(result.boxes.info).toBe(result.tokens['--state-info-bg']);
  expect(result.boxes.offline).toBe(result.tokens['--state-neutral-bg']);
});

test('semantic state pairs keep readable contrast in both themes', async ({ page }) => {
  await page.setContent(`<!doctype html><html data-theme="light"><head><style>${source('frontend/css/theme-variables.css')}</style></head><body></body></html>`);
  const ratios = await page.evaluate(() => {
    const parse = value => value.match(/[\d.]+/g).slice(0, 3).map(Number);
    const luminance = value => {
      const channels = parse(value).map(channel => {
        const normalized = channel / 255;
        return normalized <= .04045 ? normalized / 12.92 : ((normalized + .055) / 1.055) ** 2.4;
      });
      return .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2];
    };
    const resolve = token => {
      const probe = document.createElement('i');
      probe.style.color = `var(${token})`;
      document.body.appendChild(probe);
      const value = getComputedStyle(probe).color;
      probe.remove();
      return value;
    };
    const pairs = ['success', 'warning', 'info', 'danger', 'neutral'];
    return ['light', 'dark'].flatMap(theme => {
      document.documentElement.dataset.theme = theme;
      return pairs.map(name => {
        const foreground = luminance(resolve(`--state-${name}-text`));
        const background = luminance(resolve(`--state-${name}-bg`));
        return { theme, name, ratio: (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05) };
      });
    });
  });
  for (const pair of ratios) expect(pair.ratio, `${pair.theme} ${pair.name}`).toBeGreaterThanOrEqual(4.5);
});

test('light is the default and complex map boxes follow the same theme switch', async ({ page }) => {
  await page.setContent(`<!doctype html><html data-theme="light" data-app-view="map"><head><style>${mapCss}</style></head><body>
    <section class="dt-overlay-container" style="display:block"><header id="dt-header"></header><main id="dt-main"><aside id="dt-panel"><div class="dt-panel-section"></div></aside></main></section>
    <aside class="dt-results" style="visibility:visible;transform:none"></aside>
    <section class="incident-inbox"><article class="incident-item"></article></section>
  </body></html>`);

  const snapshot = () => page.evaluate(() => ({
    theme: document.documentElement.dataset.theme,
    canvas: getComputedStyle(document.querySelector('.dt-overlay-container')).backgroundColor,
    panelBox: getComputedStyle(document.querySelector('.dt-panel-section')).backgroundColor,
    results: getComputedStyle(document.querySelector('.dt-results')).backgroundColor,
    incidents: getComputedStyle(document.querySelector('.incident-inbox')).backgroundColor,
    incidentItem: getComputedStyle(document.querySelector('.incident-item')).backgroundColor,
  }));
  const tokens = async () => computedTheme(page, {}, ['--surface-canvas', '--surface-default', '--surface-subtle']);

  const light = await snapshot();
  const lightTokens = (await tokens()).tokens;
  expect(light.theme).toBe('light');
  expect(light.canvas).toBe(lightTokens['--surface-canvas']);
  expect(light.results).toBe(lightTokens['--surface-default']);
  expect(light.incidents).toBe(lightTokens['--surface-default']);
  expect(light.panelBox).toBe(lightTokens['--surface-subtle']);
  expect(light.incidentItem).toBe(lightTokens['--surface-subtle']);

  await page.evaluate(() => { document.documentElement.dataset.theme = 'dark'; });
  const dark = await snapshot();
  const darkTokens = (await tokens()).tokens;
  expect(dark.canvas).toBe(darkTokens['--surface-canvas']);
  expect(dark.results).toBe(darkTokens['--surface-default']);
  expect(dark.incidents).toBe(darkTokens['--surface-default']);
  expect(dark.panelBox).toBe(darkTokens['--surface-subtle']);
  expect(dark.incidentItem).toBe(darkTokens['--surface-subtle']);
  expect(dark.results).not.toBe(light.results);
});
