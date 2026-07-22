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
            <div class="row g-3">
                ${this.stationsData.map(s => {
                    const alertingDisabled = (s.config?.alerting?.enabled === false) || s.config?.alerting_enabled === false;
                    const offlineDisplayEnabled = (s.config?.offline_display?.enabled === true) || s.config?.offline_display_enabled === true;
                    const statusAccent = s.status === 'online' ? 'success' : (s.status === 'stale' ? 'warning' : 'secondary');
                    return `
                    <div class="col-md-6">
                        <div class="card hover-lift station-card">
                            <div class="card-body position-relative" style="z-index: 2;">
                                <div class="d-flex justify-content-between align-items-start mb-2">
                                    <div>
                                        <h6 class="mb-1 fw-bold neon-text" style="color: var(--accent-${statusAccent})">
                                            <i class="bi bi-broadcast-pin me-2"></i>
                                            ${s.name}
                                        </h6>
                                        <small class="text-muted font-monospace">${s.station_code}</small>
                                        ${alertingDisabled ? '<span class="badge bg-warning text-dark ms-2">Không cảnh báo</span>' : ''}
                                        ${offlineDisplayEnabled ? '<span class="badge bg-info text-dark ms-2">Offline giám sát</span>' : ''}
                                    </div>
                                    <div class="d-flex align-items-center gap-2">
                                        <span class="status-dot ${s.status === 'online' ? 'pulsing' : ''}"
                                              style="background-color: var(--accent-${statusAccent})"></span>
                                        <span class="small font-monospace text-uppercase" style="color: var(--accent-${statusAccent})">
                                            ${s.status || 'OFFLINE'}
                                        </span>
                                    </div>
                                </div>
                                ${s.location ? `
                                    <div class="text-muted small mb-2 font-monospace">
                                        <i class="bi bi-geo-alt me-1"></i>
                                        LAT: ${s.location.lat?.toFixed(6)} | LON: ${s.location.lon?.toFixed(6)}
                                    </div>
                                ` : ''}


                            </div>
                            <div class="card-footer bg-transparent border-top-0 position-relative" style="z-index: 2;">
                                <div class="d-flex gap-2">
                                    <button class="btn btn-sm btn-outline-primary flex-1" onclick="window.adminManager.editStation(${s.id})">
                                        <i class="bi bi-pencil me-1"></i> CONFIGURE
                                    </button>
                                    <button class="btn btn-sm btn-outline-danger" onclick="window.adminManager.deleteStation(${s.id})">
                                        <i class="bi bi-trash"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
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
