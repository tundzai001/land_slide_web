const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

test('admin base picker keeps offline stations and treats API text as text', async ({page}) => {
  await page.setContent('<div id="clusters"></div>');
  await page.evaluate(() => {
    window.AdminManager = class {};
    window.applyAdminFeature = Feature => { window.ProjectConfigFeature = Feature; };
  });
  await page.addScriptTag({content:readFileSync(join(__dirname, '../../frontend/js/admin/project-config.js'), 'utf8')});
  await page.evaluate(() => {
    const manager = new window.ProjectConfigFeature();
    manager.projectStationsData = [];
    manager.corsStationsData = [
      {name:'SinQuyen1', serial:'BASE-1', status:'awaiting_license', lat:22.6, lon:103.8, alt:165,
        streams:[{stream_id:'s1', host:'caster.example', port:2101, mountpoint:'SinQuyen1', enabled:false}]},
      {name:'<img src=x onerror=alert(1)>', serial:'BASE-2', status:'online', lat:21, lon:105,
        streams:[{stream_id:'s1', host:'caster.example', port:2101, mountpoint:'<img src=x onerror=alert(1)>', enabled:true}]}
    ];
    manager.addClusterRow(document.getElementById('clusters'));
    window.adminManager = manager;
  });
  await expect(page.locator('.cluster-base-select option')).toContainText(['-- Chọn Trạm Base --', '🔴 SinQuyen1 (OFFLINE)', '🟢 <img src=x onerror=alert(1)> (ONLINE)']);
  await expect(page.locator('#clusters img')).toHaveCount(0);
  await page.locator('.cluster-base-select').selectOption('SinQuyen1');
  await expect(page.locator('.cluster-stream-select option')).toContainText(['-- Chọn Luồng --', 'Luồng: S1 - SinQuyen1 [caster.example:2101]']);
});
