const { test, expect } = require('@playwright/test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const root = join(__dirname, '../..');
const source = file => readFileSync(join(root, file), 'utf8');

async function mount(page, width = 1280) {
  await page.setViewportSize({ width, height: 900 });
  await page.setContent('<html lang="vi" data-app-view="admin" data-theme="light"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body></body></html>');
  await page.addStyleTag(process.env.WORKSPACE_BOOTSTRAP_CSS ? { path: process.env.WORKSPACE_BOOTSTRAP_CSS } : { url: 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' });
  for (const file of ['theme-variables','components','admin/base','admin/pi-devices','admin/premium-light']) await page.addStyleTag({content:source(`frontend/css/${file}.css`)});
  await page.addScriptTag({content:source('frontend/js/templates/admin/gnss-project-modals.js')});
  await page.evaluate(() => { document.body.innerHTML = window.LegacyTemplateParts['gnss-project-modals']; });
  for (const file of ['core','users']) await page.addScriptTag({content:source(`frontend/js/admin/${file}.js`)});
  await page.evaluate(() => {
    window.bootstrap = { Modal: class {
      constructor(element) { this.element = element; }
      static getOrCreateInstance(element) { return new this(element); }
      static getInstance(element) { return new this(element); }
      show() { this.element.style.display = 'block'; this.element.classList.add('show'); }
      hide() { this.element.style.display = 'none'; this.element.classList.remove('show'); }
    }};
    window.adminManager = Object.create(window.AdminManager.prototype);
    window.adminManager.token = 'test-token';
    window.adminManager.usersData = [{id:4,username:'operator1',full_name:'Vận hành',role:'operator',assigned_projects:[2]}];
    window.requests = [];
    window.fetch = async (url, options = {}) => {
      if (String(url).includes('/projects')) return new Response(JSON.stringify(window.failProjects ? {} : [{id:2,name:'Sín Quyền <b>2</b>',project_code:'SQ-2026'}]), {status:window.failProjects ? 503 : 200});
      window.requests.push({url, ...options});
      if (options.method) return new Promise(resolve => { window.releaseSave = resolve; });
      return new Response('[]');
    };
  });
}

test('create user validates Unicode password policy, keeps server errors and prevents duplicate submissions', async ({page}) => {
  await mount(page, 390);
  await page.evaluate(async () => { bootstrap.Modal.getOrCreateInstance(document.getElementById('addUserModal')).show(); await adminManager.loadProjectsForModal(); });
  await page.locator('#addUserModal').getByLabel('Tài khoản', {exact:true}).fill('new.operator');
  await page.locator('#addUserModal').getByLabel('Mật khẩu', {exact:true}).fill('short');
  await page.locator('#create-user-btn').click();
  await expect(page.locator('#new-password')).toBeFocused();
  await expect(page.locator('#new-password')).toHaveAttribute('aria-invalid','true');
  await expect(page.locator('#new-password-error')).toContainText('12 ký tự');
  expect(await page.evaluate(() => requests.length)).toBe(0);
  await page.locator('#new-password').fill('ắ'.repeat(25));
  await page.locator('#create-user-btn').click();
  await expect(page.locator('#new-password-error')).toContainText('72 byte');
  await page.locator('#new-password').fill('a long passphrase');
  await page.locator('#project-checkbox-list input').check();
  await page.evaluate(() => { void adminManager.createUser(); void adminManager.createUser(); });
  await expect(page.locator('#create-user-btn')).toBeDisabled();
  expect(await page.evaluate(() => requests.length)).toBe(1);
  await page.evaluate(() => releaseSave(new Response(JSON.stringify({detail:[{msg:'Tài khoản đã tồn tại'}]}), {status:422})));
  await expect(page.locator('#new-user-error')).toContainText('Tài khoản đã tồn tại');
  await expect(page.locator('#new-user-error')).toBeFocused();
  await expect(page.locator('#new-password')).toHaveValue('a long passphrase');
  await expect(page.locator('#create-user-btn')).toBeEnabled();
  await expect(page.locator('#project-checkbox-list b')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({path:'test-results/user-create-validation-mobile.png',animations:'disabled'});
});

test('edit user requires project load success and preserves edits across retry', async ({page}) => {
  await mount(page);
  await page.evaluate(async () => { window.failProjects = true; await adminManager.showEditUserModal(4); });
  await expect(page.locator('#save-user-config-btn')).toBeDisabled();
  await page.locator('#edit-user-fullname').fill('Tên được giữ lại');
  await page.evaluate(() => adminManager.saveUserConfiguration());
  expect(await page.evaluate(() => requests.length)).toBe(0);
  await page.evaluate(() => { window.failProjects = false; });
  await page.locator('#edit-user-projects').getByRole('button',{name:'Thử lại'}).click();
  await expect(page.locator('#save-user-config-btn')).toBeEnabled();
  await expect(page.locator('#edit-user-fullname')).toHaveValue('Tên được giữ lại');
  await expect(page.locator('#edit-user-projects input[value="2"]')).toBeChecked();
  await page.locator('#edit-user-password').fill('too short');
  await page.locator('#save-user-config-btn').click();
  await expect(page.locator('#edit-password-error')).toContainText('12 ký tự');
  await page.locator('#edit-user-password').fill('');
  await page.locator('#save-user-config-btn').click();
  await expect(page.locator('#save-user-config-btn')).toBeDisabled();
  expect(await page.evaluate(() => JSON.parse(requests[0].body).assigned_projects)).toEqual([2]);
  await page.evaluate(() => releaseSave(new Response(JSON.stringify({detail:'Không thể lưu lúc này. Hãy thử lại.'}), {status:503})));
  await expect(page.locator('#edit-user-error')).toContainText('Hãy thử lại');
  await page.screenshot({path:'test-results/user-edit-project-scope.png',animations:'disabled'});
});
