(() => {
class AdminUsersFeature extends window.AdminManager {
    // =========================================================================
    // USER MANAGEMENT
    // =========================================================================

    async loadUsers() {
        const requestId = this.userListRequestId = (this.userListRequestId || 0) + 1;
        const tbody = document.getElementById('user-table-body');
        if (tbody) tbody.innerHTML = '<tr><td colspan="6"><div class="ops-loading"><span class="spinner-border spinner-border-sm" aria-hidden="true"></span><span>Đang tải người dùng…</span></div></td></tr>';
        try {
            const query = new URLSearchParams({ sort: 'username', limit: '500' });
            const q = document.getElementById('user-search')?.value.trim() || '';
            const role = document.getElementById('user-role-filter')?.value || '';
            const active = document.getElementById('user-status-filter')?.value || '';
            if (q) query.set('q', q);
            if (role) query.set('role', role);
            if (active) query.set('is_active', active);
            const res = await fetch(`/api/admin/users?${query}`, {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (res.status === 401) {
                void window.authManager?.handleUnauthorizedResponse?.('admin-users');
                return;
            }

            if (!res.ok) throw new Error('Failed to load users');

            const users = await res.json();
            if (requestId !== this.userListRequestId) return;
            this.usersData = users;
            this.renderUsers(users);
        } catch (e) {
            if (requestId !== this.userListRequestId) return;
            console.error('Error loading users:', e);
            if (tbody) tbody.innerHTML = '<tr><td colspan="6"><div class="ops-empty is-error"><i class="bi bi-exclamation-circle"></i><strong>Không tải được người dùng</strong><button class="btn btn-outline-primary" onclick="window.adminManager.loadUsers()">Thử lại</button></div></td></tr>';
        }
    }

    scheduleUserFilter() {
        clearTimeout(this.userSearchTimer);
        this.userSearchTimer = setTimeout(() => this.loadUsers(), 250);
    }

    escapeUserValue(value) {
        return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
    }

    renderUsers(users) {
        const tbody = document.getElementById('user-table-body');
        if (!tbody) return;

        if (!users || users.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">Chưa có người dùng</td></tr>`;
            return;
        }

        const roleBadge = (role) => {
            const labels = { admin: 'Admin', operator: 'Operator', viewer: 'Viewer' };
            const l = labels[role] || role;
            return `<span class="badge user-role-badge">${this.escapeUserValue(l)}</span>`;
        };

        tbody.innerHTML = users.map(u => {
            // Show assigned projects for operators (by name)
            let projectBadges = '';
            if ((u.role === 'operator' || u.role === 'viewer') && u.assigned_projects?.length > 0) {
                const projectItems = u.assigned_projects
                    .map(pid => `<span class="user-project-badge">${this.escapeUserValue(this.getProjectName(pid))}</span>`)
                    .join(' ');
                projectBadges = `<br><small class="text-muted">Dự án: ${projectItems}</small>`;
            } else if (u.role === 'viewer') {
                projectBadges = `<br><small class="text-muted">Dự án: <span class="user-project-badge">Tất cả</span></small>`;
            }

            const toggleBtnClass = u.is_active ? 'warning' : 'success';
            const toggleTitle = u.is_active ? 'Khóa tài khoản' : 'Mở khóa';
            const toggleLabel = u.is_active ? 'Khóa' : 'Mở khóa';
            const toggleIcon = u.is_active ? 'lock' : 'unlock';
            const statusClass = u.is_active ? 'is-active' : 'is-locked';
            const statusIcon = u.is_active ? 'check-circle' : 'lock';
            const statusText = u.is_active ? 'Hoạt động' : 'Đã khóa';
            const adminActions = u.username === 'admin' ? '' : `
                        <button class="btn btn-outline-${toggleBtnClass} management-icon-btn" onclick="window.adminManager.toggleUserStatus(${u.id}, ${!u.is_active})" title="${toggleTitle}" aria-label="${toggleLabel} ${this.escapeUserValue(u.username)}">
                            <i class="bi bi-${toggleIcon}"></i>
                        </button>
                        <button class="btn btn-outline-danger management-icon-btn" onclick="window.adminManager.deleteUser(${u.id})" title="Xóa tài khoản" aria-label="Xóa ${this.escapeUserValue(u.username)}">
                            <i class="bi bi-trash"></i>
                        </button>`;

            return `
            <tr class="management-table-row">
                <td class="font-monospace text-muted">#${u.id}</td>
                <td><strong class="management-primary-text">${this.escapeUserValue(u.username)}</strong></td>
                <td>${this.escapeUserValue(u.full_name || '--')}</td>
                <td>${roleBadge(u.role)}${projectBadges}</td>
                <td>
                    <div class="d-flex align-items-center gap-2">
                        <span class="management-status ${statusClass}">
                            <i class="bi bi-${statusIcon}" aria-hidden="true"></i>
                            ${statusText}
                        </span>
                    </div>
                </td>
                <td>
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-primary management-icon-btn" onclick="window.adminManager.showEditUserModal(${u.id})" title="Sửa cấu hình" aria-label="Sửa cấu hình ${this.escapeUserValue(u.username)}"><i class="bi bi-sliders"></i></button>
                        ${adminActions}
                    </div>
                </td>
            </tr>
        `}).join('');
    }

    async showEditUserModal(userId) {
        const user = (this.usersData || []).find(item => Number(item.id) === Number(userId));
        if (!user) return;
        document.getElementById('edit-user-id').value = user.id;
        document.getElementById('edit-user-username').value = user.username || '';
        document.getElementById('edit-user-fullname').value = user.full_name || '';
        document.getElementById('edit-user-password').value = '';
        this.clearUserFormError('edit');
        const roleSelect = document.getElementById('edit-user-role');
        roleSelect.value = user.role || 'viewer';
        roleSelect.disabled = user.username === 'admin';

        bootstrap.Modal.getOrCreateInstance(document.getElementById('editUserModal')).show();
        this.syncEditUserProjectVisibility();
        await this.loadEditUserProjects(userId);
    }

    async loadEditUserProjects(userId = Number(document.getElementById('edit-user-id').value)) {
        const user = (this.usersData || []).find(item => Number(item.id) === Number(userId));
        if (!user) return;
        const container = document.getElementById('edit-user-projects');
        const button = document.getElementById('save-user-config-btn');
        this.editUserProjectsReady = false;
        button.disabled = true;
        container.setAttribute('aria-busy', 'true');
        container.innerHTML = '<span class="text-muted small">Đang tải dự án…</span>';
        try {
            const res = await fetch('/api/admin/projects', { headers: { 'Authorization': `Bearer ${this.token}` } });
            if (!res.ok) throw new Error('Không tải được dự án. Hãy thử lại trước khi lưu.');
            const projects = await res.json();
            if (Number(document.getElementById('edit-user-id').value) !== Number(userId)) return;
            const assigned = new Set((user.assigned_projects || []).map(Number));
            if (!projects.length) {
                container.innerHTML = '<span class="text-muted small">Chưa có dự án</span>';
            } else {
                container.innerHTML = projects.map(project => {
                    const isChecked = assigned.has(Number(project.id)) ? 'checked' : '';
                    const title = this.escapeUserValue(project.name || project.project_code);
                    const code = this.escapeUserValue(project.project_code || ('#' + project.id));
                    return `<label class="user-project-option"><input type="checkbox" value="${Number(project.id)}" ${isChecked}><span><strong>${title}</strong><small>${code}</small></span></label>`;
                }).join('');
            }
            this.editUserProjectsReady = true;
            button.disabled = false;
        } catch (error) {
            if (Number(document.getElementById('edit-user-id').value) !== Number(userId)) return;
            container.replaceChildren();
            const span = document.createElement('span');
            span.className = 'text-danger small';
            span.setAttribute('role', 'alert');
            span.textContent = error?.message || 'Không tải được dự án';
            const retryBtn = document.createElement('button');
            retryBtn.type = 'button';
            retryBtn.className = 'btn btn-outline-primary btn-sm ms-2';
            retryBtn.textContent = 'Thử lại';
            retryBtn.onclick = () => window.adminManager?.loadEditUserProjects();
            container.append(span, retryBtn);
        } finally {
            if (Number(document.getElementById('edit-user-id').value) === Number(userId)) container.removeAttribute('aria-busy');
        }
    }

    clearUserFormError(mode) {
        const summary = document.getElementById(`${mode}-user-error`);
        if (summary) { summary.hidden = true; summary.textContent = ''; }
        const field = document.getElementById(mode === 'new' ? 'new-password' : 'edit-user-password');
        field?.removeAttribute('aria-invalid');
        if (mode === 'new') document.getElementById('new-username')?.removeAttribute('aria-invalid');
        const error = document.getElementById(`${mode}-password-error`);
        if (error) error.textContent = '';
    }

    showUserFormError(mode, message, fieldId) {
        const summary = document.getElementById(`${mode}-user-error`);
        if (summary) { summary.textContent = message; summary.hidden = false; }
        const field = fieldId && document.getElementById(fieldId);
        if (field) {
            field.setAttribute('aria-invalid', 'true');
            const error = document.getElementById(`${mode}-password-error`);
            if (error && field.type === 'password') error.textContent = message;
            field.focus();
        } else summary?.focus();
    }

    validateUserPassword(mode, required = false) {
        const fieldId = mode === 'new' ? 'new-password' : 'edit-user-password';
        const password = document.getElementById(fieldId).value;
        if (!password && !required) return true;
        let message = '';
        if ([...password].length < 12) {
            message = 'Mật khẩu cần ít nhất 12 ký tự.';
        } else if (new TextEncoder().encode(password).length > 72) {
            message = 'Mật khẩu quá dài. Giới hạn 72 byte UTF-8; ký tự có dấu có thể chiếm nhiều byte.';
        }
        if (message) this.showUserFormError(mode, message, fieldId);
        return !message;
    }

    async userResponseError(response) {
        const payload = await response.json().catch(() => ({}));
        if (Array.isArray(payload.detail)) return payload.detail.map(item => item.msg).join('. ');
        return typeof payload.detail === 'string' ? payload.detail : `Không thể lưu thay đổi (HTTP ${response.status}).`;
    }

    syncEditUserProjectVisibility() {
        const role = document.getElementById('edit-user-role')?.value;
        const group = document.getElementById('edit-user-project-group');
        if (group) group.hidden = !['operator', 'viewer'].includes(role);
    }

    async saveUserConfiguration() {
        const userId = Number(document.getElementById('edit-user-id').value);
        const role = document.getElementById('edit-user-role').value;
        const password = document.getElementById('edit-user-password').value;
        this.clearUserFormError('edit');
        if (!this.validateUserPassword('edit')) return;
        if (!this.editUserProjectsReady) {
            this.showUserFormError('edit', 'Danh sách dự án chưa sẵn sàng. Hãy tải lại trước khi lưu.');
            return;
        }
        const assignedProjects = [...document.querySelectorAll('#edit-user-projects input:checked')].map(input => Number(input.value));
        const button = document.getElementById('save-user-config-btn');
        if (button.disabled) return;
        const originalButtonHtml = button.innerHTML;
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Đang lưu…';
        try {
            const res = await fetch(`/api/admin/users/${userId}`, {
                method: 'PUT',
                headers: { 'Authorization': `Bearer ${this.token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    full_name: document.getElementById('edit-user-fullname').value.trim(),
                    role,
                    password: password || null,
                    assigned_projects: ['operator', 'viewer'].includes(role) ? assignedProjects : [],
                }),
            });
            if (!res.ok) throw new Error(await this.userResponseError(res));
            bootstrap.Modal.getInstance(document.getElementById('editUserModal'))?.hide();
            window.toast?.success('Đã cập nhật cấu hình người dùng');
            await this.loadUsers();
        } catch (error) {
            this.showUserFormError('edit', error.message);
        } finally {
            button.disabled = false;
            button.innerHTML = originalButtonHtml;
        }
    }

    async createUser() {
        const username = document.getElementById('new-username').value.trim();
        const password = document.getElementById('new-password').value;
        const fullname = document.getElementById('new-fullname').value.trim();
        const role = document.getElementById('new-role').value;

        // Collect assigned projects (checkboxes)
        const assignedProjects = [];
        document.querySelectorAll('#project-checkbox-list input[type="checkbox"]:checked').forEach(cb => {
            assignedProjects.push(Number.parseInt(cb.value));
        });

        this.clearUserFormError('new');
        if (!username || /\s/.test(username)) {
            this.showUserFormError('new', 'Nhập tài khoản không chứa khoảng trắng.', 'new-username');
            return;
        }
        if (!this.validateUserPassword('new', true)) return;
        if (role !== 'admin' && !this.newUserProjectsReady) {
            this.showUserFormError('new', 'Danh sách dự án chưa sẵn sàng. Hãy tải lại trước khi tạo tài khoản.');
            return;
        }
        const button = document.getElementById('create-user-btn');
        if (button.disabled) return;
        const originalButtonHtml = button.innerHTML;
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
        button.textContent = 'Đang tạo…';
        try {
            const res = await fetch('/api/admin/users', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    username, password, full_name: fullname, role,
                    assigned_projects: (role === 'operator' || role === 'viewer') ? assignedProjects : []
                })
            });

            if (res.ok) {
                window.toast?.success('Tạo tài khoản thành công');
                bootstrap.Modal.getInstance(document.getElementById('addUserModal'))?.hide();
                document.getElementById('addUserForm').reset();
                document.getElementById('project-assign-group').style.display = 'block';
                await this.loadUsers();
            } else {
                throw new Error(await this.userResponseError(res));
            }
        } catch (e) {
            this.showUserFormError('new', e.message);
        } finally {
            button.disabled = false;
            button.removeAttribute('aria-busy');
            button.innerHTML = originalButtonHtml;
        }
    }

    async deleteUser(userId) {
        const username = (this.usersData || []).find(user => Number(user.id) === Number(userId))?.username || `#${userId}`;
        if (!confirm(`Xóa người dùng ${username}?`)) return;
        try {
            const res = await fetch(`/api/admin/users/${userId}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (res.ok) {
                window.toast?.success('Đã xóa người dùng');
                await this.loadUsers();
            } else {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi xóa');
            }
        } catch (e) {
            console.error('Lỗi khóa/mở khóa người dùng:', e);
            window.toast?.error(e.message);
        }
    }

    async toggleUserStatus(userId, isActive) {
        const username = (this.usersData || []).find(user => Number(user.id) === Number(userId))?.username || `#${userId}`;
        const action = isActive ? 'mở khóa' : 'khóa';
        if (!confirm(`Bạn có chắc muốn ${action} người dùng ${username}?`)) return;
        try {
            const res = await fetch(`/api/admin/users/${userId}/status`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ is_active: isActive })
            });

            if (res.ok) {
                window.toast?.success(`Đã ${action} người dùng ${username}`);
                void this.loadUsers();
            } else {
                const err = await res.json();
                throw new Error(err.detail || `Lỗi ${action} tài khoản`);
            }
        } catch (e) {
            console.error('Lỗi khóa/mở khóa người dùng:', e);
            window.toast?.error(e.message);
        }
    }

    /** Load project list into the Add User modal checkboxes */
    async loadProjectsForModal() {
        this.newUserProjectsReady = false;
        const container = document.getElementById('project-checkbox-list');
        if (!container) return;
        container.innerHTML = '<small class="text-muted">Đang tải dự án…</small>';
        try {
            const res = await fetch('/api/admin/projects', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) throw new Error('Không tải được dự án');
            const projects = await res.json();
            this.newUserProjectsReady = true;

            if (projects.length === 0) {
                container.innerHTML = '<small class="text-muted">Chưa có dự án nào</small>';
                return;
            }

            container.innerHTML = projects.map(p => `
                <div class="form-check mb-1">
                    <input class="form-check-input" type="checkbox" value="${p.id}" id="assign-proj-${p.id}">
                    <label class="form-check-label small" for="assign-proj-${p.id}">${this.escapeUserValue(p.name)} <span class="text-muted">(#${p.id})</span></label>
                </div>
            `).join('');
        } catch (e) {
            console.error('Error loading projects for modal:', e);
            container.innerHTML = '<span class="text-danger small" role="alert">Không tải được dự án.</span><button type="button" class="btn btn-outline-primary btn-sm ms-2" onclick="window.adminManager.loadProjectsForModal()">Thử lại</button>';
        }
    }

    /** Apply viewer restrictions — hide all edit/create/delete UI elements */
    applyViewerRestrictions() {
        console.log('🔒 Applying viewer restrictions');

        // Hide sidebar tabs: Users, Database, System, Pi Devices (only show Projects)
        document.querySelectorAll('.admin-sidebar .nav-item').forEach(item => {
            const link = item.querySelector('[data-tab]');
            if (link) {
                const tab = link.dataset.tab;
                if (tab !== 'tab-projects') {
                    item.style.display = 'none';
                }
            }
        });

        // Hide all create/edit/delete buttons in Projects tab
        document.querySelectorAll('#action-buttons-container, #btn-back-nav').forEach(el => {
            // Keep back button but hide create buttons
        });
        const createProjBtn = document.querySelector('#action-buttons-container');
        if (createProjBtn) createProjBtn.style.display = 'none';

        // Hide "Thêm user" button
        const addUserBtn = document.querySelector('[data-bs-target="#addUserModal"]');
        if (addUserBtn) addUserBtn.style.display = 'none';

        // Switch to projects tab by default
        const projLink = document.querySelector('[data-tab="tab-projects"]');
        if (projLink) this.switchTab('tab-projects', projLink);
    }

}
window.applyAdminFeature(AdminUsersFeature);
})();
