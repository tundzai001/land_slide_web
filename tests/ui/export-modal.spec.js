const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const templateSource = readFileSync(
  join(__dirname, '..', '..', 'frontend/js/templates/admin/data-modals-nav.js'),
  'utf8',
);

test('export choices override the global 44px native checkbox rule cleanly', async ({ page }) => {
  await page.setContent(`<!doctype html><html><head><style>
    input[type="checkbox"] { min-width:44px; min-height:44px; }
    label { display:flex; align-items:center; gap:8px; }
  </style></head><body></body></html>`);
  await page.addScriptTag({ content: templateSource });
  await page.evaluate(() => {
    document.body.innerHTML = window.LegacyTemplateParts['data-modals-nav'];
  });

  const geometry = await page.locator('#export-projects').evaluate(input => {
    const inputRect = input.getBoundingClientRect();
    const label = input.closest('label');
    const iconRect = label.querySelector('.export-dataset-icon').getBoundingClientRect();
    const copyRect = label.querySelector('.export-dataset-copy').getBoundingClientRect();
    const checkRect = label.querySelector('.export-check').getBoundingClientRect();
    return {
      inputWidth: inputRect.width,
      inputHeight: inputRect.height,
      iconRight: iconRect.right,
      copyLeft: copyRect.left,
      checkWidth: checkRect.width,
    };
  });

  expect(geometry.inputWidth).toBeLessThanOrEqual(1);
  expect(geometry.inputHeight).toBeLessThanOrEqual(1);
  expect(geometry.copyLeft).toBeGreaterThan(geometry.iconRight);
  expect(geometry.checkWidth).toBe(22);
  await expect(page.locator('.export-sensor-check')).toHaveCount(4);
  await expect(page.locator('.export-sensor-types label').first()).toHaveCSS('min-height', '48px');
});

test('export modal synchronizes colors cleanly between light and dark themes', async ({ page }) => {
  const themeVars = readFileSync(
    join(__dirname, '..', '..', 'frontend/css/theme-variables.css'),
    'utf8',
  );

  await page.setContent(`<!doctype html><html lang="vi" data-theme="light"><head><style>${themeVars}</style></head><body></body></html>`);
  await page.addScriptTag({ content: templateSource });
  await page.evaluate(() => {
    document.body.innerHTML = window.LegacyTemplateParts['data-modals-nav'];
  });

  const getShellBg = () => page.locator('#exportExcelModal .export-shell').evaluate(el => getComputedStyle(el).backgroundColor);
  const getPanelBg = () => page.locator('#exportExcelModal .export-panel').first().evaluate(el => getComputedStyle(el).backgroundColor);
  const getSelectBg = () => page.locator('#export-project-select').evaluate(el => getComputedStyle(el).backgroundColor);

  // In light theme
  const lightShell = await getShellBg();
  const lightSelect = await getSelectBg();
  expect(lightShell).toBe('rgb(255, 255, 255)');
  expect(lightSelect).toBe('rgb(255, 255, 255)');
  await expect(page.locator('#btn-export-retry')).toBeAttached();

  // Switch to dark theme
  await page.evaluate(() => {
    document.documentElement.setAttribute('data-theme', 'dark');
  });

  const darkShell = await getShellBg();
  const darkSelect = await getSelectBg();
  expect(darkShell).toBe('rgb(11, 36, 39)'); // --surface-default
  expect(darkSelect).toBe('rgb(12, 43, 46)'); // --export-field-bg #0c2b2e
  expect(darkShell).not.toBe(lightShell);
});
