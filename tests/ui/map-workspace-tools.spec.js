const {test,expect} = require('@playwright/test');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const root=join(__dirname,'../..');
const source=file=>readFileSync(join(root,file),'utf8');
async function mount(page,width=1440) {
  await page.setViewportSize({width,height:900});
  await page.route('http://tools.test/**',route=>route.fulfill({contentType:'text/html',body:'<html lang="vi" data-theme="light" data-app-view="map"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="app-root"></div></body></html>'}));
  await page.route('**/assets/aitogy.png*',route=>route.fulfill({contentType:'image/png',body:readFileSync(join(root,'frontend/assets/aitogy.png'))}));
  await page.goto('http://tools.test/');
  await page.addStyleTag(process.env.WORKSPACE_BOOTSTRAP_CSS ? {path:process.env.WORKSPACE_BOOTSTRAP_CSS} : {url:'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css'});
  await page.addStyleTag({url:'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css'});
  for(const file of ['app-base','map']) await page.addStyleTag({content:source(`frontend/dist/${file}.min.css`)});
  await page.addStyleTag(process.env.LEAFLET_TEST_CSS ? {path:process.env.LEAFLET_TEST_CSS} : {url:'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'});
  await page.addScriptTag(process.env.LEAFLET_TEST_JS ? {path:process.env.LEAFLET_TEST_JS} : {url:'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'});
  await page.addScriptTag(process.env.CHART_TEST_JS ? {path:process.env.CHART_TEST_JS} : {url:'https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js'});
  await page.addScriptTag({content:source('frontend/js/sensor-catalog.js')});
  for(const file of ['shell','station-panels']) await page.addScriptTag({content:source(`frontend/js/templates/map/${file}.js`)});
  await page.evaluate(()=>{
    document.getElementById('app-root').innerHTML=window.LegacyTemplateParts.shell+window.LegacyTemplateParts['station-panels'];
    window.__MAP_BUNDLE_LOADING__=true;
  });
  for(const file of ['runtime','map-layers','stations','station-detail','chart-workspace']) await page.addScriptTag({content:source(`frontend/js/map/${file}.js`)});
  await page.evaluate(()=>{
    map=L.map('map',{zoomControl:false}).setView([21.035,105.815],13);
    switchMapTiles(); setupBasemapControls(); setupChartWorkspaceControls();
    currentStationData={id:1,name:'Hồ chứa Bắc Sơn',station_code:'BS-01',sensors:{water:{},rain:{},imu:{}}};
  });
}

test('basemaps switch without moving the map or removing overlays and persist',async({page})=>{
  await mount(page);
  await page.evaluate(()=>{window.overlay=L.marker([21.035,105.815]).addTo(map);});
  await page.locator('#basemap-toggle').click();
  for(const [type,code] of [['roadmap','m'],['satellite','s'],['terrain','p'],['hybrid','y']]) {
    await page.locator(`input[name=basemap][value=${type}]`).check();
    const result=await page.evaluate(()=>({url:currentTileLayer._url,zoom:map.getZoom(),center:map.getCenter(),overlay:map.hasLayer(window.overlay),saved:localStorage.getItem('monitoring-basemap')}));
    expect(result.url).toContain(`lyrs=${code}`); expect(result.zoom).toBe(13); expect(result.center.lat).toBeCloseTo(21.035); expect(result.overlay).toBe(true); expect(result.saved).toBe(type);
  }
  await page.keyboard.press('Escape');
  await expect(page.locator('#basemap-popover')).toBeHidden(); await expect(page.locator('#basemap-toggle')).toBeFocused();
  await page.locator('#basemap-toggle').click(); await page.locator('input[value=terrain]').check();
  await mount(page);
  await expect(page.locator('input[value=terrain]')).toBeChecked();
  expect(await page.evaluate(()=>currentTileLayer._url)).toContain('lyrs=p');
  await page.locator('#basemap-toggle').click();
  await page.waitForTimeout(1000);
  await page.screenshot({path:'test-results/map-basemap-picker.png',animations:'disabled'});
});

for(const width of [1440,390,320]) test(`chart inspection, filtering, export and refresh at ${width}px`,async({page})=>{
  await mount(page,width);
  await page.route('**/api/stations/1/history?**',route=>route.fulfill({json:{sensors:{
    water:{history:[{timestamp:1700000000,data:{water_level:12.3456}},{timestamp:1700000060,data:{water_level:null}},{timestamp:1700000120,data:{water_level:12.7}}]},
    rain:{history:[{timestamp:1700000000,data:{intensity_mm_h:0}},{timestamp:1700000060,data:{intensity_mm_h:8}}]},
    imu:{history:[{timestamp:1700000000,data:{roll:null,pitch:0,yaw:-1}},{timestamp:1700000060,data:{roll:1,pitch:2,yaw:3}}]}
  }}}));
  await page.evaluate(async()=>{setChartsPanelOpen(document.getElementById('charts-panel'),true);await loadStationHistoryAndRenderCharts();});
  await expect(page.locator('#chart-workspace-status')).toContainText('Đã tải dữ liệu');
  expect(await page.evaluate(()=>charts['chart-imu'].data.datasets[0].data)).toEqual([null,1]);
  await page.locator('#chart-sensor-filter').selectOption('chart-water');
  await expect(page.locator('#chart-box-water')).toBeVisible(); await expect(page.locator('#chart-box-rain')).toBeHidden();
  await expect(page.locator('#chart-box-water .chart-series-summary')).toContainText('2 điểm');
  await page.locator('#charts-expand').click(); await expect(page.locator('#charts-expand')).toHaveAttribute('aria-pressed','true');
  await page.keyboard.press('Escape'); await expect(page.locator('#charts-expand')).toHaveAttribute('aria-pressed','false');
  await page.locator('#charts-expand').click();
  const csv=page.waitForEvent('download'); await page.locator('#chart-box-water').getByRole('button',{name:/Xuất CSV/}).click();
  const file=await csv; const content=readFileSync(await file.path(),'utf8');
  expect(content).toContain('2023-11-14T22:13:20.000Z'); expect(content).toContain('12.3456'); expect(content).toContain('2023-11-14T22:14:20.000Z",');
  const png=page.waitForEvent('download'); await page.locator('#chart-box-water').getByRole('button',{name:/Xuất PNG/}).click();
  const bytes=readFileSync(await (await png).path()); expect(bytes.subarray(1,4).toString()).toBe('PNG');
  await page.route('**/api/stations/1/history?**',route=>route.fulfill({status:503,json:{}}));
  await page.locator('#charts-refresh').click(); await expect(page.locator('#chart-workspace-status')).toContainText('Không tải được');
  await expect(page.locator('#charts-refresh')).toBeEnabled();
  await page.route('**/api/stations/1/history?**',route=>route.fulfill({json:{sensors:{water:{history:[]},rain:{history:[]},imu:{history:[]}}}}));
  await page.locator('#charts-refresh').click(); await expect(page.locator('#chart-workspace-status')).toContainText('Chưa có dữ liệu');
  await page.unroute('**/api/stations/1/history?**');
  await page.evaluate(()=>{currentStationData.sensors.water.history=Array.from({length:100},(_,i)=>({timestamp:1700000000+i*60,data:{water_level:12+Math.sin(i/8)*.4}}));renderCharts(currentStationData);});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1);
  await page.evaluate(()=>document.querySelector('.charts-panel-content').scrollTop=0);
  await page.screenshot({path:`test-results/chart-workspace-${width}.png`,animations:'disabled'});
  await page.evaluate(()=>{document.documentElement.dataset.theme='dark';window.dispatchEvent(new CustomEvent('themeChanged',{detail:{theme:'dark'}}));});
  expect(await page.evaluate(()=>charts['chart-water'].options.scales.y.ticks.color)).toBe(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim()));
  await page.screenshot({path:`test-results/chart-workspace-dark-${width}.png`,animations:'disabled'});
});
