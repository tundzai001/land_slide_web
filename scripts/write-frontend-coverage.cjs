const { createCoverageMap } = require('istanbul-lib-coverage');
const { mkdirSync, readFileSync, readdirSync, writeFileSync } = require('node:fs');
const { join } = require('node:path');
const v8toIstanbul = require('v8-to-istanbul');

async function main() {
  const directory = process.env.FRONTEND_COVERAGE_DIR;
  if (!directory) throw new Error('FRONTEND_COVERAGE_DIR is required');
  const coverage = createCoverageMap({});
  for (const name of readdirSync(directory).filter(name => name.endsWith('.json'))) {
    const entries = JSON.parse(readFileSync(join(directory, name), 'utf8'));
    await Promise.all(entries.map(async entry => {
      const converter = v8toIstanbul(entry.path);
      await converter.load();
      converter.applyCoverage(entry.functions);
      coverage.merge(converter.toIstanbul());
    }));
  }
  if (!coverage.files().length) throw new Error('No frontend source coverage was collected');
  let lcov = '';
  for (const path of coverage.files()) {
    lcov += `SF:${path}\n`;
    const file = coverage.fileCoverageFor(path);
    const lines = file.getLineCoverage();
    for (const [line, hits] of Object.entries(lines)) lcov += `DA:${line},${hits}\n`;
    const data = file.toJSON();
    for (const [id, branch] of Object.entries(data.branchMap)) {
      data.b[id].forEach((hits, index) => {
        const line = branch.locations[index]?.start.line || branch.line;
        lcov += `BRDA:${line},${id},${index},${hits}\n`;
      });
    }
    lcov += 'end_of_record\n';
  }
  mkdirSync('coverage-js', { recursive: true });
  writeFileSync('coverage-js/lcov.info', lcov);
  console.log(`Frontend coverage written for ${coverage.files().length} source files`);
}
main().catch(error => { console.error(error); process.exitCode = 1; });
