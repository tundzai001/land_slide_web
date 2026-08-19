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
