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
        this._managementDemViewer?.destroy();
        this._managementDemViewer = null;
        this._managementDemGrid = null;
        this._managementDemPlacement = false;
        const container = document.getElementById('projects-content-area');
        const title = document.getElementById('current-view-title');
        const actionButtons = document.getElementById('action-buttons-container');

        const projectName = this.getProjectName(this.currentProjectId);

        if (title) title.textContent = `Trạm trong "${projectName}"`;
        const project = (this.projectsData || []).find(item => String(item.id) === String(this.currentProjectId)) || null;
        const dems = project?.dems || [];
        const hasDem = dems.length > 0 || Boolean(project?.has_dem);
        const canUploadDem = this.currentUserRole === 'admin';
        if (actionButtons) {
            actionButtons.innerHTML = `
                ${canUploadDem ? `<input type="file" id="project-dem-file" accept=".asc,text/plain" hidden onchange="window.adminManager.uploadProjectDem(this.files[0]); this.value='';">
                <button class="btn btn-outline-primary" type="button" onclick="document.getElementById('project-dem-file').click()">
                    <i class="bi bi-upload me-2" aria-hidden="true"></i>${hasDem ? 'Thêm khu DEM' : 'Tải DEM'}
                </button>` : ''}
                <button class="btn btn-outline-primary" type="button" id="dem-placement-toggle" onclick="window.adminManager.toggleDemPlacementMode()" ${hasDem ? '' : 'disabled'} aria-pressed="false">
                    <i class="bi bi-crosshair me-2" aria-hidden="true"></i>Chọn ô đặt trạm
                </button>
                <button class="btn btn-gradient" onclick="window.adminManager.openAddStationModal()">
                    <i class="bi bi-plus-circle me-2"></i>Thêm Trạm
                </button>
            `;
        }

        if (!dems.some(model => model.id === this._selectedDemId)) this._selectedDemId = dems[0]?.id || null;
        const demWorkspace = this.renderProjectDemWorkspace(project, canUploadDem);

        if (!this.stationsData || this.stationsData.length === 0) {
            container.innerHTML = `
                ${demWorkspace}
                <div class="text-center py-5">
                    <i class="bi bi-hdd-network fs-1 text-muted"></i>
                    <p class="text-muted mt-2">Chưa có trạm nào</p>
                </div>
            `;
            if (hasDem) this.loadProjectDem(this._selectedDemId);
            return;
        }

        container.innerHTML = `
            ${demWorkspace}
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
        if (hasDem) this.loadProjectDem(this._selectedDemId);
    }

    renderProjectDemWorkspace(project, canUpload) {
        const dems = project?.dems || [];
        const hasDem = dems.length > 0 || Boolean(project?.has_dem);
        return `
            <section class="management-dem-workspace" aria-labelledby="management-dem-title">
                <div class="management-dem-heading">
                    <div><h2 id="management-dem-title">Địa hình số · ${this.escapeHtml(project?.name || this.getProjectName(this.currentProjectId))}</h2>
                    <p>${hasDem ? 'Mô hình DEM · EPSG:32648 · chọn ô lưới để đặt vị trí trạm.' : 'Tải DEM của công trình lên để xem địa hình và chọn vị trí trạm.'}</p></div>
                    ${hasDem ? '<span class="badge text-bg-success">Đã có DEM</span>' : ''}
                </div>
                ${canUpload ? `
                    <div class="management-dem-upload-row">
                        <label for="project-dem-name">Tên khu địa hình</label>
                        <input class="form-control" id="project-dem-name" maxlength="100" placeholder="Ví dụ: Thân đập, Bờ mỏ">
                        <small class="text-muted">Tên đã có sẽ cập nhật đúng khu đó; tên mới sẽ tạo thêm một khu DEM.</small>
                    </div>
                ` : ''}
                ${hasDem ? `
                    <div class="management-dem-controls">
                        ${dems.length > 1 ? `<label class="management-dem-select-label" for="management-dem-select">Khu địa hình
                            <select class="form-select form-select-sm" id="management-dem-select">${dems.map(model => `<option value="${this.escapeHtml(model.id)}" ${model.id === this._selectedDemId ? 'selected' : ''}>${this.escapeHtml(model.name)}</option>`).join('')}</select>
                        </label>` : `<span class="management-dem-current-name">${this.escapeHtml(dems[0]?.name || 'Địa hình')}</span>`}
                        <span class="small text-muted">Cuộn để zoom · kéo để di chuyển · mỗi ô theo lưới DEM</span>
                        <div class="dem-grid-toolbar" aria-label="Điều khiển mô hình DEM">
                            <button type="button" class="btn btn-sm btn-outline-secondary" data-dem-admin-action="out" aria-label="Thu nhỏ mô hình">−</button>
                            <button type="button" class="btn btn-sm btn-outline-secondary" data-dem-admin-action="fit" aria-label="Vừa khung mô hình"><i class="bi bi-arrows-angle-contract" aria-hidden="true"></i></button>
                            <button type="button" class="btn btn-sm btn-outline-secondary" data-dem-admin-action="in" aria-label="Phóng to mô hình">+</button>
                        </div>
                    </div>
                    <div class="dem-grid-viewport management-dem-viewport"><canvas id="management-dem-canvas" tabindex="0" role="application" aria-label="Mô hình DEM. Dùng phím mũi tên để chọn ô và Enter để đặt trạm."></canvas></div>
                    <p class="management-dem-selection" id="management-dem-selection" role="status" aria-live="polite">${canUpload ? 'Chọn “Chọn ô đặt trạm”, sau đó bấm một ô trên mô hình.' : 'Mô hình địa hình của dự án.'}</p>
                ` : `
                    <div class="management-dem-empty" role="status">
                        <i class="bi bi-mountains" aria-hidden="true"></i>
                        <strong>${canUpload ? 'Chưa có mô hình địa hình' : 'Dự án chưa có DEM'}</strong>
                        <span>${canUpload ? 'Tải lên file ESRI ASCII Grid (.asc), hệ tọa độ UTM 48N.' : 'Liên hệ quản trị viên để tải mô hình DEM lên.'}</span>
                    </div>
                `}
            </section>`;
    }

    async uploadProjectDem(file) {
        if (!file || !this.currentProjectId) return;
        const demName = document.getElementById('project-dem-name')?.value?.trim();
        const status = document.getElementById('management-dem-selection');
        const uploadButton = document.querySelector('#action-buttons-container button[onclick*="project-dem-file"]');
        if (!demName) {
            window.toast?.warning('Nhập tên khu địa hình, ví dụ “Thân đập” hoặc “Bờ mỏ”.');
            document.getElementById('project-dem-name')?.focus();
            return;
        }
        if (status) status.textContent = 'Đang tải và kiểm tra lưới DEM…';
        if (uploadButton) { uploadButton.disabled = true; uploadButton.setAttribute('aria-busy', 'true'); }
        try {
            const form = new FormData();
            form.append('dem_file', file);
            form.append('dem_name', demName);
            const response = await fetch(`/api/admin/projects/${this.currentProjectId}/dems`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${this.token}` },
                body: form,
            });
            const responseText = await response.text();
            let result = {};
            try { result = JSON.parse(responseText); } catch { /* Proxy errors may be HTML. */ }
            if (!response.ok) {
                const detail = result.detail || (response.status === 413
                    ? `Máy chủ từ chối file (HTTP 413): ${file.name} (${(file.size / (1024 * 1024)).toFixed(1)} MiB). Đối chiếu log backend “Project DEM upload received”; nếu không có dòng này, IIS hoặc proxy đã chặn trước ứng dụng.`
                    : `Không tải được DEM (HTTP ${response.status}).`);
                throw new Error(detail);
            }
            const project = (this.projectsData || []).find(item => String(item.id) === String(this.currentProjectId));
            if (project) { project.dems = result.models || []; project.has_dem = true; }
            this._selectedDemId = result.dem_id;
            window.toast?.success(`Đã lưu “${result.dem?.name || demName}”: ${result.dem?.ncols} × ${result.dem?.nrows} ô, UTM 48N.`);
            this.renderStations();
        } catch (error) {
            if (status) status.textContent = error.message;
            window.toast?.error(error.message || 'Không tải được mô hình DEM');
        } finally {
            if (uploadButton) { uploadButton.disabled = false; uploadButton.removeAttribute('aria-busy'); }
        }
    }

    async loadProjectDem(demId = this._selectedDemId) {
        const canvas = document.getElementById('management-dem-canvas');
        if (!canvas || !window.DemGrid || !demId) return;
        const projectId = this.currentProjectId;
        const requestId = (this._managementDemRequest || 0) + 1;
        this._managementDemRequest = requestId;
        this._selectedDemId = demId;
        this._managementDemViewer?.destroy();
        const status = document.getElementById('management-dem-selection');
        if (status) status.textContent = 'Đang đọc mô hình địa hình…';
        try {
            const response = await fetch(`/api/projects/${projectId}/dems/${encodeURIComponent(demId)}`, {
                headers: { Authorization: `Bearer ${this.token}` },
            });
            if (!response.ok) throw new Error(`Không tải được DEM (HTTP ${response.status}).`);
            const grid = window.DemGrid.parse(await response.text());
            if (!canvas.isConnected || requestId !== this._managementDemRequest || String(projectId) !== String(this.currentProjectId)) return;
            this._managementDemPlacement = false;
            this._managementDemGrid = grid;
            this._managementDemModel = (this.projectsData || []).find(item => String(item.id) === String(projectId))?.dems?.find(model => model.id === demId) || null;
            this._managementDemViewer = window.DemGrid.mount(canvas, grid, {
                selectable: true,
                onSelect: (point, interaction) => this.handleProjectDemCell(point, interaction),
            });
            document.querySelectorAll('[data-dem-admin-action]').forEach(button => button.onclick = () => {
                const action = button.dataset.demAdminAction;
                if (action === 'in') this._managementDemViewer?.zoomIn();
                else if (action === 'out') this._managementDemViewer?.zoomOut();
                else this._managementDemViewer?.fit();
            });
            const selector = document.getElementById('management-dem-select');
            if (selector) selector.onchange = () => this.loadProjectDem(selector.value);
            if (status) status.textContent = `${grid.ncols} × ${grid.nrows} ô · cao độ ${grid.min.toFixed(1)}–${grid.max.toFixed(1)} m · UTM 48N`;
        } catch (error) {
            if (requestId === this._managementDemRequest) {
                if (status) status.textContent = error.message || 'Không thể đọc file DEM.';
                window.toast?.error(error.message || 'Không thể đọc file DEM');
            }
        }
    }

    toggleDemPlacementMode() {
        if (!this._managementDemGrid) return;
        this._managementDemPlacement = !this._managementDemPlacement;
        const button = document.getElementById('dem-placement-toggle');
        button?.setAttribute('aria-pressed', String(this._managementDemPlacement));
        button?.classList.toggle('btn-primary', this._managementDemPlacement);
        button?.classList.toggle('btn-outline-primary', !this._managementDemPlacement);
        const status = document.getElementById('management-dem-selection');
        if (status) status.textContent = this._managementDemPlacement
            ? 'Đang chọn vị trí trạm · bấm vào một ô lưới trên địa hình.'
            : 'Đã dừng chọn vị trí trạm.';
        document.getElementById('management-dem-canvas')?.focus({ preventScroll: true });
    }

    handleProjectDemCell(point, interaction = { commit: true }) {
        const status = document.getElementById('management-dem-selection');
        if (!interaction.commit) {
            if (status) status.textContent = `${this._managementDemPlacement ? 'Đang chọn' : 'Ô'} ${point.column + 1}, ${point.row + 1} · ${point.elevation.toFixed(1)} m · ${point.lat.toFixed(7)}, ${point.lon.toFixed(7)}${this._managementDemPlacement ? ' · nhấn Enter để đặt trạm' : ''}`;
            return;
        }
        if (!this._managementDemPlacement) {
            if (status) status.textContent = `Ô ${point.column + 1}, ${point.row + 1} · ${point.elevation.toFixed(1)} m · ${point.lat.toFixed(7)}, ${point.lon.toFixed(7)}`;
            return;
        }
        this._managementDemPlacement = false;
        this.pendingStationLocation = {
            lat: point.lat,
            lon: point.lon,
            h: point.elevation,
            source: 'project-dem-grid',
            dem_id: this._selectedDemId,
            dem_name: this._managementDemModel?.name || '',
            grid: { row: point.row, column: point.column, easting: point.easting, northing: point.northing },
        };
        document.getElementById('dem-placement-toggle')?.setAttribute('aria-pressed', 'false');
        if (status) status.textContent = `Đã chọn ô ${point.column + 1}, ${point.row + 1} · ${point.elevation.toFixed(1)} m. Đang mở biểu mẫu tạo trạm…`;
        this.openAddStationModal({ location: this.pendingStationLocation });
    }

}
window.applyAdminFeature(AdminStationsFeature);
})();
