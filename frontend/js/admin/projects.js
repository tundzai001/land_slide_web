(() => {
class AdminProjectsFeature extends window.AdminManager {
    // =========================================================================
    // PROJECTS MANAGEMENT
    // =========================================================================

    async loadProjects() {
        try {
            const res = await fetch('/api/admin/projects', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (res.status === 401) {
                void window.authManager?.handleUnauthorizedResponse?.('admin-projects');
                return;
            }

            if (!res.ok) throw new Error('Failed to load projects');

            this.projectsData = await res.json();
            this.renderProjects();
        } catch (e) {
            console.error('Error loading projects:', e);
            window.toast?.error('Không thể tải danh sách dự án');
        }
    }

    renderProjects() {
        const container = document.getElementById('projects-content-area');
        const title = document.getElementById('current-view-title');
        const actionButtons = document.getElementById('action-buttons-container');

        if (title) title.textContent = 'Danh sách Dự án';
        if (actionButtons) {
            actionButtons.innerHTML = `
                <button class="btn btn-gradient" onclick="window.adminManager.openCreateProjectModal()">
                    <i class="bi bi-plus-circle me-2"></i>Tạo Dự án
                </button>
            `;
        }

        if (!this.projectsData || this.projectsData.length === 0) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="bi bi-inbox fs-1 text-muted"></i>
                    <p class="text-muted mt-2">Chưa có dự án nào</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="row g-4 management-project-grid">
                ${this.projectsData.map(p => `
                    <div class="col-md-6 col-xl-4">
                        <article class="card project-card management-project-card h-100" onclick="window.adminManager.loadStations(${p.id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();window.adminManager.loadStations(${p.id})}" tabindex="0" aria-label="Mở dự án ${p.name}">
                            <div class="card-body">
                                <div class="d-flex justify-content-between align-items-start mb-3">
                                    <div class="d-flex align-items-center gap-3 min-w-0">
                                        <span class="project-icon" aria-hidden="true"><i class="bi bi-diagram-3"></i></span>
                                        <div class="min-w-0">
                                            <h5 class="card-title mb-1 text-truncate">${p.name}</h5>
                                            <small class="project-code">${p.project_code}</small>
                                        </div>
                                    </div>
                                    <span class="project-count"><strong>${p.station_count || 0}</strong> trạm</span>
                                </div>
                                <p class="project-description">${p.description || 'Chưa có mô tả cho dự án này.'}</p>
                                ${p.location ? `<p class="project-location mb-0"><i class="bi bi-geo-alt" aria-hidden="true"></i><span>${typeof p.location === 'string' ? p.location : (p.location.address || p.location.source || `${p.location.lat ?? ''}, ${p.location.lon ?? ''}`)}</span></p>` : ''}

                            </div>
                            <div class="card-footer">
                                <div class="d-flex gap-2 align-items-center">
                                    <button class="btn btn-sm btn-primary flex-grow-1" onclick="event.stopPropagation(); window.adminManager.loadStations(${p.id})">
                                        Mở dự án <i class="bi bi-arrow-right ms-1" aria-hidden="true"></i>
                                    </button>
                                    <button class="btn btn-sm btn-outline-primary project-action-btn project-edit-btn" onclick="event.stopPropagation(); window.adminManager.openProjectConfigModal(${p.id})" title="Chỉnh sửa dự án" aria-label="Chỉnh sửa dự án ${p.name}">
                                        <i class="bi bi-pencil-square" aria-hidden="true"></i><span>Chỉnh sửa</span>
                                    </button>
                                    <button class="btn btn-sm btn-outline-danger project-action-btn" onclick="event.stopPropagation(); window.adminManager.deleteProject(${p.id})" title="Xóa dự án" aria-label="Xóa dự án ${p.name}">
                                        <i class="bi bi-trash" aria-hidden="true"></i>
                                    </button>
                                </div>
                            </div>
                        </article>
                    </div>
                `).join('')}
            </div>
        `;
    }

    openCreateProjectModal() {
        const modal = new bootstrap.Modal(document.getElementById('createProjectModal'));
        modal.show();
    }

    async createProject() {
        const code = document.getElementById('project-code').value.trim();
        const name = document.getElementById('project-name').value.trim();
        const desc = document.getElementById('project-desc').value.trim();
        const location = document.getElementById('project-location').value.trim();

        if (!code || !name) {
            window.toast?.warning('Vui lòng nhập đầy đủ thông tin');
            return;
        }

        try {
            const res = await fetch('/api/admin/projects', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    project_code: code,
                    name: name,
                    description: desc,
                    location: location
                })
            });

            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || 'Lỗi tạo dự án');
            }

            window.toast?.success('✅ Tạo dự án thành công!');

            const modal = bootstrap.Modal.getInstance(document.getElementById('createProjectModal'));
            modal.hide();

            document.getElementById('createProjectForm').reset();
            this.loadProjects();

        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

    async deleteProject(projectId) {
        if (!confirm('Bạn có chắc muốn xóa dự án này? Tất cả trạm bên trong sẽ bị xóa!')) return;

        try {
            const res = await fetch(`/api/admin/projects/${projectId}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) throw new Error('Failed');

            window.toast?.success('✅ Xóa dự án thành công!');
            this.loadProjects();

        } catch (e) {
            window.toast?.error('❌ Lỗi xóa dự án');
        }
    }

}
window.applyAdminFeature(AdminProjectsFeature);
})();
