(() => {
class AdminStationsFeature extends window.AdminManager {
    // =========================================================================
    // STATIONS MANAGEMENT
    // =========================================================================

    async loadStations(projectId) {
        try {
            if (this.currentView === 'projects') {
                this.navigationStack.push({ view: 'projects' });
            }

            this.currentView = 'stations';
            this.currentProjectId = projectId;

            const res = await fetch(`/api/admin/projects/${projectId}/stations`, {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) throw new Error('Failed to load stations');

            this.stationsData = await res.json();
            this.renderStations();
            this.updateBreadcrumb();
            this.updateBackButton();

        } catch (e) {
            console.error('Error loading stations:', e);
            window.toast?.error('Không thể tải danh sách trạm');
        }
    }

    renderStations() {
        const container = document.getElementById('projects-content-area');
        const title = document.getElementById('current-view-title');
        const actionButtons = document.getElementById('action-buttons-container');

        const projectName = this.getProjectName(this.currentProjectId);

        if (title) title.textContent = `Trạm trong "${projectName}"`;
        if (actionButtons) {
            actionButtons.innerHTML = `
                <button class="btn btn-gradient" onclick="window.adminManager.openAddStationModal()">
                    <i class="bi bi-plus-circle me-2"></i>Thêm Trạm
                </button>
            `;
        }

        if (!this.stationsData || this.stationsData.length === 0) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="bi bi-hdd-network fs-1 text-muted"></i>
                    <p class="text-muted mt-2">Chưa có trạm nào</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="row g-4 management-station-grid">
                ${this.stationsData.map(s => {
                    const alertingDisabled = (s.config?.alerting?.enabled === false) || s.config?.alerting_enabled === false;
                    const offlineDisplayEnabled = (s.config?.offline_display?.enabled === true) || s.config?.offline_display_enabled === true;
                    const statusAccent = s.status === 'online' ? 'success' : (s.status === 'stale' ? 'warning' : 'secondary');
                    return `
                    <div class="col-md-6 col-xl-4">
                        <article class="card station-card management-station-card h-100">
                            <div class="card-body">
                                <div class="d-flex justify-content-between align-items-start mb-2">
                                    <div class="d-flex gap-3 min-w-0">
                                        <span class="station-icon is-${statusAccent}" aria-hidden="true"><i class="bi bi-broadcast-pin"></i></span>
                                        <div class="min-w-0">
                                            <h6 class="mb-1 fw-bold text-truncate">${s.name}</h6>
                                            <small class="project-code">${s.station_code}</small>
                                        </div>
                                    </div>
                                    <span class="management-status is-${statusAccent}"><i class="bi bi-circle-fill" aria-hidden="true"></i>${s.status || 'offline'}</span>
                                </div>
                                <div class="station-tags">
                                    ${alertingDisabled ? '<span class="station-tag is-warning"><i class="bi bi-bell-slash"></i> Không cảnh báo</span>' : ''}
                                    ${offlineDisplayEnabled ? '<span class="station-tag is-info"><i class="bi bi-eye"></i> Theo dõi offline</span>' : ''}
                                </div>
                                ${s.location ? `
                                    <div class="station-coordinate">
                                        <i class="bi bi-geo-alt" aria-hidden="true"></i>
                                        <span>${s.location.lat?.toFixed(6)}, ${s.location.lon?.toFixed(6)}</span>
                                    </div>
                                ` : ''}


                            </div>
                            <div class="card-footer">
                                <div class="d-flex gap-2">
                                    <button class="btn btn-sm btn-primary flex-grow-1" onclick="window.adminManager.editStation(${s.id})">
                                        <i class="bi bi-sliders me-1"></i> Cấu hình
                                    </button>
                                    <button class="btn btn-sm btn-outline-danger management-icon-btn" onclick="window.adminManager.deleteStation(${s.id})" aria-label="Xóa trạm ${s.name}" title="Xóa trạm">
                                        <i class="bi bi-trash"></i>
                                    </button>
                                </div>
                            </div>
                        </article>
                    </div>
                `;
                }).join('')
            }
            </div >
    `;
    }

}
window.applyAdminFeature(AdminStationsFeature);
})();
