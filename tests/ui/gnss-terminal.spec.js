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

test('GNSS terminal header and debug controls stay clear of map navbar and floating controls at 100% laptop zoom', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 740 });
  await page.setContent(`<!doctype html><html data-app-view="map"><head><style>
    :root { --z-popover: 1100; --z-modal: 2200; --z-critical: 3200; }
    * { box-sizing: border-box; }
    html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; }
    .top-navbar { position: fixed; top: 0; left: 0; right: 0; height: 72px; z-index: var(--z-critical); background: #fff; }
    .custom-map-controls { position: fixed; right: 22px; bottom: 96px; width: 56px; height: 150px; z-index: var(--z-popover); background: #111; }
    .modal { position: fixed; inset: 0; display: block; }
    .modal-dialog { width: 100%; margin: 1.75rem auto; }
    .modal-content { display: flex; flex-direction: column; width: 100%; }
    .modal-header { display: flex; align-items: center; }
    .d-flex { display: flex; } .flex-row { flex-direction: row; } .flex-column { flex-direction: column; }
    .flex-grow-1 { flex-grow: 1; }
    ${gnssCss}
  </style></head><body>
    <nav class="top-navbar">Navbar</nav>
    <div class="custom-map-controls">Controls</div>
    <div class="modal show" id="gnssTerminalModal">
      <div class="modal-dialog gnss-terminal-dialog">
        <div class="modal-content gnss-terminal-content">
          <div class="modal-header gnss-terminal-header">
            <div class="gnss-terminal-heading">
              <span class="gnss-terminal-eyebrow">NETWORK ADJUSTMENT</span>
              <h5 class="modal-title">Bình sai mạng GNSS</h5>
            </div>
            <div id="gnss-phase-indicator">Phase: COLLECTING_BASELINE</div>
            <div class="gnss-run-controls">
              <button id="gnss-pause-adjustment-btn" class="btn">Tạm dừng</button>
              <button id="gnss-stop-adjustment-btn" class="btn">Dừng hẳn</button>
            </div>
            <button type="button" id="gnss-close-btn" class="btn-close">X</button>
          </div>
          <div class="modal-body d-flex flex-row gnss-terminal-body">
            <div id="gnss-board-container">
              <div id="gnss-roster-summary" class="gnss-roster-summary"><span>6 trạm đã chọn</span></div>
            </div>
            <div id="gnss-column-resizer"></div>
            <div id="gnss-data-column" class="d-flex flex-column">
              <section class="gnss-workflow-panel flex-grow-1">
                <header class="gnss-workflow-header">
                  <div>
                    <span class="gnss-workflow-kicker">LIVE WORKFLOW</span>
                    <h6>Sơ đồ quy trình bình sai</h6>
                    <p id="gnss-workflow-current">Thu baseline từ Base cố định</p>
                  </div>
                </header>
                <div class="gnss-workflow-scroll">
                  <div class="gnss-workflow-map">
                    <article class="gnss-flow-node status-success"><div class="gnss-flow-rail"><span class="gnss-flow-marker">1</span></div><div class="gnss-flow-card"><h6>Khởi tạo phiên bình sai</h6><p>Sẵn sàng</p></div></article>
                    <article class="gnss-flow-node status-running"><div class="gnss-flow-rail"><span class="gnss-flow-marker">2</span></div><div class="gnss-flow-card"><h6>Thu baseline từ Base cố định</h6><p>Đang chờ</p></div></article>
                    <article class="gnss-flow-node status-warning"><div class="gnss-flow-rail"><span class="gnss-flow-marker">3</span></div><div class="gnss-flow-card"><h6>Lọc cụm GNSS đang hoạt động</h6><p>Còn 5 rover</p></div></article>
                  </div>
                </div>
              </section>
              <div id="gnss-debug-section" class="d-flex flex-column">
                <div class="gnss-debug-header d-flex"><button id="gnss-debug-clear">Xóa log</button></div>
                <div id="gnss-debug-log" class="flex-grow-1">[09:48:51] PHASE: CP03</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </body></html>`);

  for (const selector of ['#gnss-pause-adjustment-btn', '#gnss-stop-adjustment-btn', '#gnss-close-btn', '#gnss-debug-clear']) {
    const info = await page.locator(selector).evaluate(el => {
      const rect = el.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return {
        top: rect.top,
        bottom: rect.bottom,
        viewportHeight: window.innerHeight,
        hit: hit === el || el.contains(hit),
      };
    });
    expect(info.top).toBeGreaterThanOrEqual(72);
    expect(info.bottom).toBeLessThanOrEqual(info.viewportHeight);
    expect(info.hit).toBe(true);
  }
});

