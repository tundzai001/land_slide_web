const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

test('DEM grid renders, zooms and converts a selected UTM 48N cell to WGS84', async ({ page }) => {
  const source = readFileSync(join(__dirname, '../../frontend/js/dem-grid.js'), 'utf8');
  await page.setViewportSize({ width: 900, height: 700 });
  await page.setContent('<main class="dem-grid-viewport" style="width:420px;height:280px"><canvas id="dem" tabindex="0" style="width:100%;height:100%"></canvas></main>');
  await page.addScriptTag({ content: source });
  await page.evaluate(() => {
    const text = 'ncols 2\nnrows 2\nxllcorner 454959.202\nyllcorner 2326094.284\ncellsize 1\nNODATA_value -9999\n100 101\n98 99';
    const grid = window.DemGrid.parse(text);
    window.selectedCells = [];
    window.demViewer = window.DemGrid.mount(document.getElementById('dem'), grid, {
      selectable: true,
      onSelect: (point, interaction) => window.selectedCells.push({ point, interaction }),
    });
  });
  await page.locator('#dem').click({ position: { x: 300, y: 180 } });
  const clicked = await page.evaluate(() => window.selectedCells.at(-1));
  expect(clicked.point.column).toBe(1);
  expect(clicked.point.row).toBe(1);
  expect(clicked.point.easting).toBe(454960.702);
  expect(clicked.point.northing).toBe(2326094.784);
  expect(clicked.point.lat).toBeGreaterThan(20);
  expect(clicked.point.lat).toBeLessThan(25);
  expect(clicked.point.lon).toBeGreaterThan(100);
  expect(clicked.point.lon).toBeLessThan(110);
  expect(clicked.interaction).toEqual({ commit: true, source: 'pointer' });

  await page.locator('#dem').focus();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('Enter');
  const keyboard = await page.evaluate(() => window.selectedCells.at(-1).interaction);
  expect(keyboard).toEqual({ commit: true, source: 'keyboard' });
});
