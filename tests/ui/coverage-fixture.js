const base = require('@playwright/test');
const { createHash } = require('node:crypto');
const { mkdirSync, readFileSync, readdirSync, writeFileSync } = require('node:fs');
const { join, resolve } = require('node:path');

const sourceByHash = new Map();
function indexSources(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) indexSources(path);
    else if (entry.name.endsWith('.js')) {
      const hash = createHash('sha256').update(readFileSync(path)).digest('hex');
      sourceByHash.set(hash, path);
    }
  }
}

const test = base.test.extend({
  page: async ({ page }, use, testInfo) => {
    const directory = process.env.FRONTEND_COVERAGE_DIR;
    if (!directory || testInfo.project.name !== 'chromium') return use(page);
    if (!sourceByHash.size) indexSources(resolve(__dirname, '../../frontend/js'));
    await page.coverage.startJSCoverage({ resetOnNavigation: false, reportAnonymousScripts: true });
    await use(page);
    if (page.isClosed()) return;
    const entries = [];
    for (const entry of await page.coverage.stopJSCoverage()) {
      if (typeof entry.source !== 'string') continue;
      const hash = createHash('sha256').update(entry.source).digest('hex');
      const path = sourceByHash.get(hash);
      if (path) entries.push({ path, functions: entry.functions });
    }
    mkdirSync(directory, { recursive: true });
    writeFileSync(join(directory, `${testInfo.testId}-${testInfo.retry}.json`), JSON.stringify(entries));
  },
});

module.exports = { ...base, test };
