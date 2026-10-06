const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const source = path => readFileSync(join(__dirname, '../..', path), 'utf8');

async function mount(page, width = 1366) {
  await page.setViewportSize({ width, height: 1000 });
  const css = ['frontend/css/theme-variables.css', 'frontend/css/admin/premium-light.css', 'frontend/css/admin/operations.css'].map(source).join('\n');
  await page.setContent(`<html><head><style>*{box-sizing:border-box}body{margin:16px;font:16px system-ui}.form-control,.form-select{display:block;width:100%;padding:8px}.btn{padding:8px 12px;border:1px solid #526b70;border-radius:8px;cursor:pointer}.ops-page-header{display:flex;justify-content:space-between;gap:16px;margin-bottom:20px}.ops-eyebrow{font-size:12px}.table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px;vertical-align:top}.visually-hidden{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}[hidden]{display:none!important}${css}</style></head><body></body></html>`);
  for (const file of ['frontend/js/templates/admin/operations.js','frontend/js/admin/core.js','frontend/js/admin/operations.js']) {
    await page.addScriptTag({ content: source(file) });
  }
  await page.evaluate(() => {
    document.body.innerHTML = window.LegacyTemplateParts.operations;
    window.adminManager = Object.create(window.AdminManager.prototype);
    Object.assign(window.adminManager, { token:'test', currentUserRole:'admin', _refreshIntervals:[], canAccessTab:() => true });
    window.operationCalls = [];
    window.activeStorage = {};
    Object.defineProperty(window, 'sessionStorage', { value:{ getItem:k => window.activeStorage[k] || null, setItem:(k,v) => window.activeStorage[k]=v, removeItem:k => delete window.activeStorage[k] } });
    window.fetch = async (url, options = {}) => {
      window.operationCalls.push({url:String(url),method:options.method || 'GET',body:options.body});
      let data;
      if (url.endsWith('/backups')) data = options.method === 'POST' ? {job_id:'abc'} : {backups:[],schedule:{frequency:'disabled'}};
      else if (url.endsWith('/log-options')) data = {accounts:[{username:'admin',full_name:'Administrator',is_active:true},{username:'new-user',is_active:true}],journals:{audit_log:{actions:['PUT /api/admin/stations/7/config'],usernames:['admin']},operation_log:{actions:['service.starting'],usernames:[]}}};
      else if (url.endsWith('/devices')) data = [{id:7,name:'Trạm nước',device_type:'water',acquisition:{protocol:'mqtt',enabled:false}}];
      else if (url.includes('/logs?') && url.includes('operation_log')) data = {total:1,rows:[{timestamp:1791210000,username:null,role:null,action:'service.starting',status:null,details:{}}]};
      else if (url.includes('/logs?')) data = {total:1,rows:[{timestamp:1791210000,username:'admin',role:'admin',action:'PUT /api/admin/stations/7/config',status:200,details:{changes:[{table:'stations',operation:'update',changes:{name:{old:'<script>bad</script>',new:'new'}}}]}}]};
      else if (url.endsWith('/ntp')) data = {config:{server:'ntp.internal'},last_check:null};
      else if (url.includes('/jobs/')) data = {status:'completed'};
      else if (url.endsWith('/backup-schedule')) data = JSON.parse(options.body);
      else if (url.endsWith('/acquisition')) data = {status:'saved'};
      else if (url.endsWith('/ntp/check')) return new Response(JSON.stringify({detail:'NTP unavailable'}),{status:502});
      else data = {};
      return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
    };
  });
  await page.evaluate(() => window.adminManager.loadOperations());
}

test('operations page works at desktop and mobile widths', async ({page}) => {
  await mount(page);
  await expect(page.getByRole('heading',{name:'Vận hành hệ thống'})).toBeVisible();
  await expect(page.locator('#operations-backups')).toContainText('Chưa có bản sao lưu');
  await page.getByRole('button',{name:'Audit log Ai đã thay đổi điều gì?'}).click();
  await expect(page.locator('#operations-logs')).toContainText('admin / admin');
  await page.getByRole('button',{name:'Xem chi tiết'}).click();
  await expect(page.locator('#operations-inspector-content')).toContainText('<script>bad</script>');
  expect(await page.locator('#operations-inspector script').count()).toBe(0);
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('button',{name:'Đóng chi tiết nhật ký'})).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(page.getByRole('button',{name:'Xem chi tiết'})).toBeFocused();
  await page.getByRole('button',{name:'Nhật ký vận hành Hệ thống đã thực hiện gì?'}).click();
  await expect(page.locator('#operations-log-description')).toContainText('Sự kiện hệ thống');
  await expect(page.locator('#operations-logs')).toContainText('Khởi động dịch vụ');
  await expect(page.locator('#operations-logs')).toContainText('Hệ thống');
  expect(await page.evaluate(() => window.operationCalls.at(-1).url)).toContain('kind=operation_log');
  await page.screenshot({path:'test-results/operations-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button',{name:'Sao lưu & phục hồi Bảo vệ dữ liệu quan trắc'}).click();
  await page.locator('.operations-schedule summary').click();
  await expect(page.locator('#operations-frequency')).toHaveCSS('min-height','44px');
  await page.screenshot({path:'test-results/operations-mobile.png',fullPage:true});
});

test('schedule and protocol save show feedback; failures restore controls', async ({page}) => {
  await mount(page);
  await page.locator('.operations-schedule summary').click();
  await expect(page.getByLabel('Giữ bản tự động')).toHaveValue('30');
  await page.getByLabel('Giữ bản tự động').fill('12');
  await page.getByLabel('Lịch tự động').selectOption('daily');
  await page.getByRole('button',{name:'Lưu lịch'}).click();
  await expect(page.locator('#operations-feedback')).toContainText('Đã lưu lịch');
  const scheduleCall = await page.evaluate(() => window.operationCalls.find(call => call.url.endsWith('/backup-schedule')));
  expect(JSON.parse(scheduleCall.body).retention_count).toBe(12);
  await page.getByRole('button',{name:'Kết nối & thời gian MQTT, gateway và NTP'}).click();
  await page.getByLabel('Nguồn dữ liệu tại hiện trường').selectOption('modbus_tcp');
  await expect(page.locator('#operations-profile-fields')).toBeVisible();
  await page.getByLabel('Cấu hình đọc và ánh xạ trường dữ liệu (JSON)').fill('{broken');
  await page.getByRole('button',{name:'Lưu cấu hình',exact:true}).click();
  await expect(page.locator('#operations-feedback')).toHaveAttribute('role','alert');
  await expect(page.getByRole('button',{name:'Lưu cấu hình',exact:true})).toBeEnabled();
  await page.getByLabel('Nguồn dữ liệu tại hiện trường').selectOption('mqtt');
  await expect(page.locator('#operations-profile-fields')).toBeHidden();
  await page.getByRole('button',{name:'Lưu cấu hình',exact:true}).click();
  await expect(page.locator('#operations-feedback')).toContainText('Đã lưu nguồn MQTT');
  await expect(page.getByLabel('Máy chủ NTP')).toHaveAttribute('readonly','');
  await page.getByRole('button',{name:'Kiểm tra độ lệch'}).click();
  await expect(page.locator('#operations-ntp-status')).toContainText('NTP unavailable');
  await expect(page.getByRole('button',{name:'Kiểm tra độ lệch'})).toBeEnabled();
  expect(await page.evaluate(() => window.operationCalls.some(call => call.url.endsWith('/ntp') && call.method === 'PUT'))).toBe(false);
});


test('inspectors keep detail readable in dark mode and on narrow screens', async ({page}) => {
  await mount(page);
  await page.screenshot({path:'test-results/operations-backup.png',fullPage:true});
  for (const width of [375, 768, 1366]) {
    await page.setViewportSize({width,height:900});
    await page.evaluate(() => document.documentElement.dataset.theme='dark');
    await page.getByRole('button',{name:'Audit log Ai đã thay đổi điều gì?'}).click();
    await page.getByRole('button',{name:'Xem chi tiết'}).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByText('Trước thay đổi',{exact:true})).toBeVisible();
    await expect(page.getByText('Sau thay đổi',{exact:true})).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path:`test-results/operations-detail-dark-${width}.png`,fullPage:true});
    await page.keyboard.press('Shift+Tab');
    await expect(page.getByRole('button',{name:'Đóng chi tiết',exact:true})).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toBeHidden();
  }
});


test('account, action and method filters submit together and motion respects preference', async ({page}) => {
  await mount(page);
  await page.getByRole('button',{name:'Audit log Ai đã thay đổi điều gì?'}).click();
  await expect(page.locator('#operations-log-user option[value="new-user"]')).toHaveCount(1);
  await page.getByLabel('Tài khoản', {exact:true}).selectOption('admin');
  await page.getByLabel('Hành động', {exact:true}).selectOption('PUT /api/admin/stations/7/config');
  await page.getByLabel('HTTP method').selectOption('PUT');
  await page.getByRole('button',{name:'Lọc nhật ký'}).click();
  const url = await page.evaluate(() => window.operationCalls.at(-1).url);
  const params = new URL(url,'http://test').searchParams;
  expect(params.get('username')).toBe('admin');
  expect(params.get('action')).toBe('PUT /api/admin/stations/7/config');
  expect(params.get('method')).toBe('PUT');
  await expect(page.locator('.operations-card[data-ops-view="logs"]')).toHaveCSS('animation-name','operations-enter');
  await page.emulateMedia({reducedMotion:'reduce'});
  await expect(page.locator('.operations-card[data-ops-view="logs"]')).toHaveCSS('animation-name','none');
  await page.getByRole('button',{name:'Nhật ký vận hành Hệ thống đã thực hiện gì?'}).click();
  await expect(page.getByLabel('HTTP method')).toBeDisabled();
  await expect(page.getByLabel('Hành động', {exact:true})).toHaveValue('');
});
