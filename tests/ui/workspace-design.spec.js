const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const root = join(__dirname, '../..');
const source = name => readFileSync(join(root, name), 'utf8');

async function css(page, env, url) {
  await page.addStyleTag(process.env[env] ? { path: process.env[env] } : { url });
}
async function mount(page, view, width) {
  await page.setViewportSize({ width, height: 900 });
  await page.route('http://workspace.test/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.startsWith('/assets/aitogy')) return route.fulfill({ contentType: 'image/png', body: readFileSync(join(root, 'frontend/assets/aitogy.png')) });
    return route.fulfill({ contentType: 'text/html', body: `<html lang="vi" data-theme="light" data-app-view="${view}"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="app-root"></div></body></html>` });
  });
  await page.goto('http://workspace.test/');
  await css(page, 'WORKSPACE_BOOTSTRAP_CSS', 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css');
  await page.addStyleTag({ url: 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css' });
  await page.addStyleTag({ content: source('frontend/dist/app-base.min.css') });
  await page.addStyleTag({ content: source(`frontend/dist/${view === 'admin' ? 'admin' : 'map'}.min.css`) });
}
async function assertLayout(page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
}

for (const width of [1440, 1024, 768, 390, 320]) {
  test(`management workspace navigation and data fit at ${width}px`, async ({ page }) => {
    await mount(page, 'admin', width);
    for (const file of ['pi-devices','operations','shell','data-modals-nav']) {
      await page.addScriptTag({ content: source(`frontend/js/templates/admin/${file}.js`) });
    }
    await page.evaluate(() => { document.getElementById('app-root').innerHTML = window.LegacyTemplateParts.shell + window.LegacyTemplateParts['data-modals-nav']; });
    for (const file of ['core','users','projects','navigation','auto-adjustment']) {
      await page.addScriptTag({ content: source(`frontend/js/admin/${file}.js`) });
    }
    await page.evaluate(() => {
      window.adminManager = Object.create(window.AdminManager.prototype);
      Object.assign(window.adminManager, {
        currentUserRole:'admin', canAccessTab:()=>true, currentTabId:'tab-users',
        projectsData: [
          {id:1, name:'Hồ chứa Bắc Sơn', project_code:'BS-01', station_count:12, description:'Quan trắc chuyển vị, mực nước và áp lực thấm.', location:'Lạng Sơn'},
          {id:2, name:'Công trình Sín Quyền', project_code:'SQ-02', station_count:8, description:'Giám sát biến dạng và điều kiện môi trường.', location:'Lào Cai'},
          {id:3, name:'Đập thủy điện', project_code:'TD-03', station_count:6, description:'Thu thập dữ liệu GNSS và cảm biến hiện trường.', location:'Hòa Bình'},
        ],
        loadUsers(){}, loadProjects(){}, loadStations(id){ window.selectedProject=id; },
      });
      window.adminManager.renderUsers([
        {id:1,username:'admin',full_name:'Quản trị hệ thống',role:'admin',is_active:true},
        {id:2,username:'vanhanh',full_name:'Nguyễn Minh Anh',role:'operator',is_active:true,assigned_projects:[1]},
        {id:3,username:'quantrac',full_name:'Trần Hải Nam',role:'viewer',is_active:true},
        {id:4,username:'kythuat',full_name:'Lê Thu Hà',role:'operator',is_active:false},
      ]);
      window.adminManager.renderProjects();
    });
    const runtime = source('frontend/js/app-runtime.js');
    const helpers = runtime.slice(runtime.indexOf('    function setupAdminMobileNavigation()'), runtime.indexOf('    function setupAdminDrawerAccessibility()'));
    await page.addScriptTag({ content: helpers + '\nsetupAdminMobileNavigation(); setupAdminResponsiveTables();' });
    await expect(page.locator('#user-table-body tr')).toHaveCount(4);
    await assertLayout(page);
    await page.screenshot({ path:`test-results/workspace-users-${width}.png`, fullPage:true, animations:'disabled' });
    await page.locator(width < 768 ? '#mobile-bottom-nav [data-tab="tab-projects"]' : '.admin-sidebar [data-tab="tab-projects"]').click();
    await expect(page.locator('#tab-projects')).toHaveClass(/active/);
    await expect(page.locator('.management-project-card')).toHaveCount(3);
    const projectPositions = await page.locator('.management-project-card').evaluateAll(cards => cards.map(card => ({
      top: card.getBoundingClientRect().top,
      width: card.getBoundingClientRect().width,
    })));
    if (width >= 768) expect(projectPositions[0].top).toBe(projectPositions[1].top);
    else expect(projectPositions[0].top).toBeLessThan(projectPositions[1].top);
    await expect(page.locator('.project-directory-summary')).toContainText('3 dự án');
    await expect(page.locator('.project-directory-summary')).toContainText('26 trạm quan trắc');
    await page.locator('.management-project-card').first().focus();
    await page.keyboard.press('Enter');
    await expect.poll(() => page.evaluate(() => window.selectedProject)).toBe(1);
    await expect(page.locator('.workspace-map-link')).toHaveAttribute('href','/map');
    await assertLayout(page);
    await page.screenshot({ path:`test-results/workspace-projects-${width}.png`, fullPage:true, animations:'disabled' });
    const lightChrome = await page.evaluate(() => [getComputedStyle(document.querySelector('.admin-sidebar')).backgroundColor, getComputedStyle(document.querySelector('.admin-navbar')).backgroundColor]);
    expect(lightChrome[0]).toBe(lightChrome[1]);
    await page.evaluate(() => document.documentElement.dataset.theme='dark');
    await page.waitForTimeout(200);
    const darkChrome = await page.evaluate(() => [getComputedStyle(document.querySelector('.admin-sidebar')).backgroundColor, getComputedStyle(document.querySelector('.admin-navbar')).backgroundColor]);
    expect(darkChrome[0]).toBe(darkChrome[1]);
    expect(darkChrome[0]).not.toBe(lightChrome[0]);
    await page.screenshot({ path:`test-results/workspace-projects-dark-${width}.png`, fullPage:true, animations:'disabled' });
    if (width < 768) await page.locator('#mobile-bottom-nav [data-more]').click();
    await page.locator(width < 768 ? '#mobile-bottom-nav [data-tab="tab-users"]' : '.admin-sidebar [data-tab="tab-users"]').focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('#tab-users')).toHaveClass(/active/);
  });

  test(`map workspace panels and keyboard selection fit at ${width}px`, async ({ page }) => {
    await mount(page, 'map', width);
    await css(page, 'LEAFLET_TEST_CSS', 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css');
    await page.addScriptTag(process.env.LEAFLET_TEST_JS ? { path:process.env.LEAFLET_TEST_JS } : { url:'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js' });
    for (const file of ['shell','station-panels']) await page.addScriptTag({ content:source(`frontend/js/templates/map/${file}.js`) });
    await page.evaluate(() => {
      document.getElementById('app-root').innerHTML = window.LegacyTemplateParts.shell + window.LegacyTemplateParts['station-panels'];
      window.__MAP_BUNDLE_LOADING__ = true;
    });
    await page.addScriptTag({ content:source('frontend/js/map/runtime.js') });
    await page.addScriptTag({ content:source('frontend/js/map/map-layers.js') });
    await page.addScriptTag({ content:source('frontend/js/map/stations.js') });
    await page.addScriptTag({ content:source('frontend/js/map/ui-alerts.js') });
    await page.evaluate(() => {
      map = L.map('map',{zoomControl:false}).setView([21.035,105.815],13);
      L.tileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',{attribution:'Google Maps'}).addTo(map);
      allStations = [
        {id:1,name:'Điểm quan trắc GNSS 01',station_code:'GNSS-01',risk_level:'LOW',status:'online'},
        {id:2,name:'Cảm biến áp lực thấm',station_code:'PIEZO-02',risk_level:'MEDIUM',status:'online'},
        {id:3,name:'Trạm môi trường 03',station_code:'ENV-03',risk_level:'LOW',status:'offline'},
      ];
      renderStationList(allStations);
      document.getElementById('station-filter-result').textContent='3 trạm';
      selectStation = id => { window.selectedStation=id; };
      allStations.forEach((s,index) => L.circleMarker([21.025+index*.009,105.812+index*.012],{radius:7,color:'#fff',weight:2,fillColor:index===1?'#b45309':'#0f766e',fillOpacity:1}).addTo(map).bindTooltip(s.name));
      setStationListSidebarOpen(document.getElementById('station-list-sidebar'),true);
      document.getElementById('sidebar-close-tab').addEventListener('click',()=>setStationListSidebarOpen(document.getElementById('station-list-sidebar'),false));
      document.getElementById('navbar-hamburger-btn').addEventListener('click',()=>setStationListSidebarOpen(document.getElementById('station-list-sidebar'),true));
    });
    await expect(page.locator('.station-item')).toHaveCount(3);
    await page.locator('.station-item').first().focus();
    await page.keyboard.press('Enter');
    expect(await page.evaluate(() => window.selectedStation)).toBe(1);
    // Reopen after selection on mobile, as in the station list workflow.
    await page.locator('#navbar-hamburger-btn').click();
    await assertLayout(page);
    await page.waitForTimeout(1000);
    await page.screenshot({ path:`test-results/workspace-map-${width}.png`, fullPage:true, animations:'disabled' });
    const lightNav = await page.locator('.top-navbar').evaluate(el => getComputedStyle(el).backgroundColor);
    await page.evaluate(() => document.documentElement.dataset.theme='dark');
    await page.waitForTimeout(200);
    const darkNav = await page.locator('.top-navbar').evaluate(el => getComputedStyle(el).backgroundColor);
    expect(darkNav).not.toBe(lightNav);
    await page.screenshot({ path:`test-results/workspace-map-dark-${width}.png`, fullPage:true, animations:'disabled' });
    await page.locator('#sidebar-close-tab').click();
    await expect(page.locator('#station-list-sidebar')).toHaveAttribute('aria-hidden','true');
    await page.evaluate(() => {
      document.getElementById('st-name').textContent='Điểm quan trắc GNSS 01';
      document.getElementById('st-code').textContent='GNSS-01';
      document.getElementById('st-risk').textContent='An toàn';
      document.documentElement.dataset.theme='light';
      setDetailSidebarOpen(document.getElementById('detail-sidebar'),true);
    });
    await expect(page.locator('#detail-sidebar')).toHaveAttribute('aria-hidden','false');
    await assertLayout(page);
    await expect(page.locator('.detail-sidebar-header')).toBeInViewport();
    expect(await page.locator('#st-name').evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    await page.screenshot({ path:`test-results/workspace-map-detail-${width}.png`, fullPage:true, animations:'disabled' });
  });
}
