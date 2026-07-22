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
            <div class="row g-3">
                ${this.projectsData.map(p => `
                    <div class="col-md-6 col-xl-4">
                        <div class="card hover-lift project-card" style="cursor: pointer;" onclick="window.adminManager.loadStations(${p.id})">
                            <div class="card-body position-relative" style="z-index: 2;">
                                <div class="d-flex justify-content-between align-items-start mb-3">
                                    <div>
                                        <h5 class="card-title mb-1 neon-text">
                                            <i class="bi bi-folder-fill me-2"></i>
                                            ${p.name}
                                        </h5>
                                        <small class="text-muted font-monospace">${p.project_code}</small>
                                    </div>
                                    <span class="badge bg-primary bg-opacity-10 text-primary border border-primary">${p.station_count || 0} STATION</span>
                                </div>
                                ${p.description ? `<p class="text-muted small mb-0">${p.description}</p>` : ''}
                                ${p.location ? `<p class="text-muted small mb-0 mt-2"><i class="bi bi-geo-alt"></i> ${typeof p.location === 'string' ? p.location : (p.location.address || p.location.source || `${p.location.lat ?? ''}, ${p.location.lon ?? ''}`)}</p>` : ''}

                            </div>
                            <div class="card-footer bg-transparent border-top-0 position-relative" style="z-index: 2;">
                                <div class="d-flex gap-2">
                                    <button class="btn btn-sm btn-outline-primary flex-1" onclick="event.stopPropagation(); window.adminManager.loadStations(${p.id})">
                                        <i class="bi bi-box-arrow-in-right me-1"></i> ACCESS
                                    </button>
                                    <button class="btn btn-sm btn-outline-success" onclick="event.stopPropagation(); window.adminManager.openProjectConfigModal(${p.id})" title="Cấu hình dự án">
                                        <i class="bi bi-gear-fill"></i>
                                    </button>
                                    <button class="btn btn-sm btn-outline-danger" onclick="event.stopPropagation(); window.adminManager.deleteProject(${p.id})">
                                        <i class="bi bi-trash"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
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
