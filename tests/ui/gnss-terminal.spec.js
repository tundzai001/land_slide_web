const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const gnssCss = readFileSync(
  join(__dirname, '..', '..', 'frontend/css/map/gnss.css'),
  'utf8',
);
const mapInteractionsSource = readFileSync(
  join(__dirname, '..', '..', 'frontend/js/map/map-interactions.js'),
  'utf8',
);

test('GNSS startup errors stay in the terminal instead of stacking a blocking alert', () => {
  expect(mapInteractionsSource).toContain("terminalModal?.classList.contains('show')");
  const startupCatch = mapInteractionsSource.match(
    /catch \(error\) \{\s*console\.error\('Adjustment trigger error:'[\s\S]*?\n\s*\}/,
  )?.[0] || '';
  expect(startupCatch).toContain('showAdjustmentError');
  expect(startupCatch).not.toContain('Swal.fire');
});

for (const viewport of [
  { name: 'desktop-1366x768', width: 1366, height: 768 },
  { name: 'mobile-390x844', width: 390, height: 844 },
]) {
  test(`GNSS terminal keeps retry action visible ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.setContent(`<!doctype html><html><head><style>
      * { box-sizing: border-box; } html, body { margin: 0; width: 100%; height: 100%; }
      .modal { position: fixed; inset: 0; display: grid; place-items: center; }
      .modal-dialog { width: 100%; margin: 0; }
      .modal-content { display: flex; flex-direction: column; width: 100%; }
      .modal-header { flex: 0 0 52px; display: flex; align-items: center; }
      .d-flex { display: flex; } .flex-column { flex-direction: column; }
      .flex-grow-1 { flex-grow: 1; } .p-3 { padding: 1rem; }
      .gap-2 { gap: .5rem; } .mb-2 { margin-bottom: .5rem; }
      button { min-height: 40px; }
      ${gnssCss}
    </style></head><body>
      <div class="modal gnss-result-visible" id="gnssTerminalModal">
        <div class="modal-dialog gnss-terminal-dialog"><div class="modal-content gnss-terminal-content">
          <div class="modal-header">GNSS Adjustment</div>
          <div class="modal-body d-flex gnss-terminal-body">
            <div id="gnss-board-container"></div><div id="gnss-column-resizer"></div>
            <div id="gnss-data-column" class="d-flex flex-column gnss-debug-collapsed">
              <section class="gnss-workflow-panel flex-grow-1"><div class="gnss-workflow-scroll">Workflow</div></section>
              <div id="gnss-debug-section"></div>
              <div id="adj-results-section" class="p-3 gnss-result-panel" style="display:block">
                <h6>Bình sai lỗi – đã lưu hồ sơ JSON</h6>
                <div class="mb-2">Time: 8/11/2026, 12:39:22 PM</div>
                <div class="d-flex gap-2 mb-2 gnss-result-actions">
                  <button id="gnss-retry-adjustment-btn">Bình sai lại</button>
                  <button id="gnss-download-results-btn">Tải kết quả</button>
                </div>
                <div style="height:180px">Temporary-BASE coverage is insufficient</div>
              </div>
            </div>
          </div>
        </div></div>
      </div>
    </body></html>`);

    const retry = page.locator('#gnss-retry-adjustment-btn');
    await expect(retry).toBeVisible();
    const geometry = await retry.evaluate(element => {
      const rect = element.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return {
        top: rect.top,
        bottom: rect.bottom,
        viewportHeight: innerHeight,
        hit: hit === element || element.contains(hit),
      };
    });
    expect(geometry.top).toBeGreaterThanOrEqual(0);
    expect(geometry.bottom).toBeLessThanOrEqual(geometry.viewportHeight);
    expect(geometry.hit).toBe(true);
  });
}
