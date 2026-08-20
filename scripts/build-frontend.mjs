import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as esbuild from 'esbuild';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const frontendRoot = path.join(projectRoot, 'frontend');
const outputRoot = path.join(frontendRoot, 'dist');

async function sourceFilesIn(directory = frontendRoot, relativeRoot = '') {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    if (entry.name === 'dist') continue;
    const relativePath = path.join(relativeRoot, entry.name);
    const absolutePath = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await sourceFilesIn(absolutePath, relativePath));
    else files.push(relativePath);
  }
  return files;
}

const sourceFiles = (await sourceFilesIn()).sort();
const versionHash = createHash('sha256');
for (const relativePath of sourceFiles) {
  versionHash.update(relativePath.replaceAll('\\', '/'));
  versionHash.update(await readFile(path.join(frontendRoot, relativePath)));
}
for (const buildInput of [fileURLToPath(import.meta.url), path.join(projectRoot, 'package-lock.json')]) {
  versionHash.update(await readFile(buildInput));
}
const buildVersion = versionHash.digest('hex').slice(0, 12);

const groups = {
  'app-base.min.css': [
    'css/theme-variables.css', 'css/theme-transition.css', 'css/components.css',
    'css/shell.css', 'css/performance.css'
  ],
  'landing.min.css': ['css/landing.css'],
  'login.min.css': ['css/login.css'],
  'map.min.css': [
    'css/map/base.css', 'css/map/station-panels.css', 'css/map/analysis.css',
    'css/map/effects-theme.css', 'css/map/tools.css', 'css/map/gnss.css',
    'css/digital-twin.css', 'css/rescue-markers.css', 'css/map-responsive.css',
    'css/map/premium-light.css', 'css/map/operations-polish.css',
    'css/map/digital-twin-workspace.css'
  ],
  'admin.min.css': [
    'css/admin/base.css', 'css/admin/effects-theme.css', 'css/admin/configuration.css',
    'css/admin/pi-wizard.css', 'css/admin-responsive.css', 'css/admin/premium-light.css',
    'css/admin/pi-devices.css'
  ],
  'shared.min.js': ['js/session-state.js', 'js/theme-manager.js', 'js/api-client.js', 'js/auth.js'],
  'map-app.min.js': [
    'js/templates/map/shell.js', 'js/templates/map/station-panels.js',
    'js/templates/map/analysis.js', 'js/templates/map/rescue.js', 'js/templates/map-template.js',
    'js/map/runtime.js', 'js/map/realtime.js', 'js/map/marker-alerts.js',
    'js/map/guest-rescue.js', 'js/map/map-layers.js', 'js/map/map-interactions.js',
    'js/map/stations.js', 'js/map/station-detail.js', 'js/map/long-term.js',
    'js/map/analysis.js', 'js/map/ui-alerts.js', 'js/map/tools.js'
  ],
  'admin-app.min.js': [
    'js/templates/admin/pi-devices.js', 'js/templates/admin/shell.js',
    'js/templates/admin/gnss-project-modals.js',
    'js/templates/admin/station-wizard-shell.js', 'js/templates/admin/station-basic.js',
    'js/templates/admin/station-connectivity.js', 'js/templates/admin/station-alerts.js',
    'js/templates/admin/station-storage.js', 'js/templates/admin/data-modals-nav.js',
    'js/templates/admin-template.js', 'js/toast-notifications.js',
    'js/admin/core.js', 'js/admin/navigation.js', 'js/admin/projects.js',
    'js/admin/project-config.js', 'js/admin/stations.js', 'js/admin/station-wizard.js',
    'js/admin/station-presets.js', 'js/admin/forwarding-controls.js',
    'js/admin/velocity.js', 'js/admin/origin.js', 'js/admin/provisioning.js',
    'js/admin/users.js', 'js/admin/pi-devices.js', 'js/admin/pi-device-actions.js', 'js/admin/pi-center.js',
    'js/admin/auto-adjustment.js',
    'js/admin/lifecycle.js', 'js/admin/bootstrap.js', 'js/db-manager.js'
  ]
};

async function concatenate(files, separator = '\n;\n') {
  const parts = [];
  for (const relativePath of files) {
    const source = await readFile(path.join(frontendRoot, relativePath), 'utf8');
    parts.push(`/* ${relativePath} */\n${source}`);
  }
  return parts.join(separator);
}

async function minify(outputName, files) {
  const loader = outputName.endsWith('.css') ? 'css' : 'js';
  // A top-level semicolon is a valid JavaScript boundary, but in CSS it is
  // parsed as part of the next selector and invalidates that complete rule.
  // Several route-critical selectors are the first rule in their module.
  const separator = loader === 'css' ? '\n' : '\n;\n';
  let source = (await concatenate(files, separator)).replaceAll('__BUILD_VERSION__', buildVersion);
  if (outputName === 'map-app.min.js') {
    const jsxSource = await readFile(path.join(frontendRoot, 'js/react/station-list.jsx'), 'utf8');
    const jsx = await esbuild.transform(jsxSource, {
      loader: 'jsx', target: 'es2019', minify: true, legalComments: 'none', charset: 'utf8'
    });
    source += `\n;\n${jsx.code}`;
  }
  const transformed = await esbuild.transform(source, {
    loader,
    target: loader === 'css' ? undefined : 'es2019',
    minifyWhitespace: true,
    minifySyntax: true,
    // Top-level names in the legacy classic-script modules are part of their
    // internal shared contract. Keep them stable while still stripping layout.
    minifyIdentifiers: false,
    legalComments: 'none',
    charset: 'utf8'
  });
  await writeFile(path.join(outputRoot, outputName), transformed.code, 'utf8');
}

async function buildLanding() {
  const sessionSource = await readFile(path.join(frontendRoot, 'js/session-state.js'), 'utf8');
  const jsxSource = await readFile(path.join(frontendRoot, 'js/landing.jsx'), 'utf8');
  const transformed = await esbuild.transform(`${sessionSource}\n;\n${jsxSource}`, {
    loader: 'jsx',
    target: 'es2019',
    minify: true,
    minifyIdentifiers: false,
    legalComments: 'none',
    charset: 'utf8',
  });
  await writeFile(path.join(outputRoot, 'landing.min.js'), transformed.code, 'utf8');
}

await rm(outputRoot, { recursive: true, force: true });
await mkdir(outputRoot, { recursive: true });

await Promise.all(Object.entries(groups).map(([name, files]) => minify(name, files)));
await Promise.all([
  buildLanding(),
  minify('app-runtime.min.js', ['js/session-state.js', 'js/app-runtime.js'])
]);

await esbuild.build({
  entryPoints: [path.join(frontendRoot, 'js/engine/simulation-controller.js')],
  outfile: path.join(outputRoot, 'digital-twin.min.js'),
  bundle: true,
  minify: true,
  sourcemap: false,
  legalComments: 'none',
  charset: 'utf8',
  format: 'esm',
  target: 'es2020',
  external: ['three', 'three/*']
});

for (const shellName of ['index.html', 'app.html']) {
  const shell = (await readFile(path.join(frontendRoot, shellName), 'utf8'))
    .replaceAll('__BUILD_VERSION__', buildVersion);
  await writeFile(path.join(outputRoot, shellName), shell, 'utf8');
}

const artifactNames = [
  ...Object.keys(groups), 'landing.min.js', 'app-runtime.min.js',
  'digital-twin.min.js', 'index.html', 'app.html'
].sort();
const manifest = { version: 1, build: buildVersion, generated_at: new Date().toISOString(), assets: {} };
for (const name of artifactNames) {
  const filePath = path.join(outputRoot, name);
  const bytes = await readFile(filePath);
  const metadata = await stat(filePath);
  manifest.assets[name] = {
    bytes: metadata.size,
    sha256: createHash('sha256').update(bytes).digest('hex')
  };
}
await writeFile(path.join(outputRoot, 'build-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');

// Absolute source URLs are forbidden. CDN URLs may legitimately contain
// segments such as `/dist/js/`, so anchor this check to a string delimiter.
const forbidden = /(?:["'`]\/(?:js|css)\/|sourceMappingURL|text\/babel|babel-runtime)/i;
for (const name of artifactNames.filter(name => name.endsWith('.js'))) {
  const output = await readFile(path.join(outputRoot, name), 'utf8');
  if (forbidden.test(output)) throw new Error(`${name} still references a source-only path or runtime compiler`);
}

for (const shellName of ['index.html', 'app.html']) {
  const shell = await readFile(path.join(outputRoot, shellName), 'utf8');
  if (shell.includes('__BUILD_VERSION__') || /["']\/(?:js|css)\//i.test(shell)) {
    throw new Error(`${shellName} still references a source-only path or unresolved build version`);
  }
}

const totalBytes = Object.values(manifest.assets).reduce((sum, asset) => sum + asset.bytes, 0);
process.stdout.write(`Built ${artifactNames.length} production assets (${totalBytes.toLocaleString('en-US')} bytes) in frontend/dist\n`);
