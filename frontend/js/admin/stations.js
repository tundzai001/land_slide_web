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
            let uploadDemHtml = '';
            if (canUploadDem) {
                const uploadDemLabel = hasDem ? 'Thêm khu DEM' : 'Tải DEM';
                uploadDemHtml = `<input type="file" id="project-dem-file" accept=".asc,text/plain" hidden onchange="window.adminManager.uploadProjectDem(this.files[0]); this.value='';">
                <button class="btn btn-outline-primary" type="button" onclick="document.getElementById('project-dem-file').click()">
                    <i class="bi bi-upload me-2" aria-hidden="true"></i>${uploadDemLabel}
                </button>`;
            }
            actionButtons.innerHTML = `
                ${uploadDemHtml}
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
            if (hasDem) void this.loadProjectDem(this._selectedDemId).catch(error => console.error('DEM load failed:', error));
            return;
        }

        container.innerHTML = `
            ${demWorkspace}
            <div class="row g-4 management-station-grid">
                ${this.stationsData.map(s => {
                    const alertingDisabled = (s.config?.alerting?.enabled === false) || s.config?.alerting_enabled === false;
                    const offlineDisplayEnabled = (s.config?.offline_display?.enabled === true) || s.config?.offline_display_enabled === true;
                    let statusAccent = 'secondary';
                    if (s.status === 'online') statusAccent = 'success';
                    else if (s.status === 'stale') statusAccent = 'warning';
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
        if (hasDem) void this.loadProjectDem(this._selectedDemId).catch(error => console.error('DEM load failed:', error));
    }

    renderProjectDemWorkspace(project, canUpload) {
        const dems = project?.dems || [];
        const hasDem = dems.length > 0 || Boolean(project?.has_dem);
        const headingDesc = hasDem ? 'Mô hình DEM · EPSG:32648 · chọn ô lưới để đặt vị trí trạm.' : 'Tải DEM của công trình lên để xem địa hình và chọn vị trí trạm.';
        const badgeHtml = hasDem ? '<span class="badge text-bg-success">Đã có DEM</span>' : '';

        let demUploadRowHtml = '';
        if (canUpload) {
            demUploadRowHtml = `
                    <div class="management-dem-upload-row">
                        <label for="project-dem-name">Tên khu địa hình</label>
                        <input class="form-control" id="project-dem-name" maxlength="100" placeholder="Ví dụ: Thân đập, Bờ mỏ">
                        <small class="text-muted">Tên đã có sẽ cập nhật đúng khu đó; tên mới sẽ tạo thêm một khu DEM.</small>
                    </div>`;
        }

        let mainDemBody = '';
        if (hasDem) {
            let demSelectOrNameHtml = `<span class="management-dem-current-name">${this.escapeHtml(dems[0]?.name || 'Địa hình')}</span>`;
            if (dems.length > 1) {
                const optionsHtml = dems.map(model => `<option value="${this.escapeHtml(model.id)}" ${model.id === this._selectedDemId ? 'selected' : ''}>${this.escapeHtml(model.name)}</option>`).join('');
                demSelectOrNameHtml = `<label class="management-dem-select-label" for="management-dem-select">Khu địa hình
                    <select class="form-select form-select-sm" id="management-dem-select">${optionsHtml}</select>
                </label>`;
            }

            const demSelectionText = canUpload ? 'Chọn “Chọn ô đặt trạm”, sau đó bấm một ô trên mô hình.' : 'Mô hình địa hình của dự án.';
            const editDemButtonHtml = canUpload ? `
                                <button type="button" class="btn btn-sm btn-outline-primary" id="btn-edit-dem-coords" onclick="window.adminManager.openEditDemCoordinatesModal()">
                                    <i class="bi bi-pencil-square me-1"></i>Chỉnh sửa tọa độ DEM
                                </button>` : '';

            mainDemBody = `
                    <div class="management-dem-controls">
                        ${demSelectOrNameHtml}
                        <span class="small text-muted">Kéo để xoay · cuộn để zoom · chọn vị trí trên địa hình 3D</span>
                        <div class="dem-grid-toolbar" aria-label="Điều khiển mô hình DEM">
                            <button type="button" class="btn btn-sm btn-outline-secondary" data-dem-admin-action="out" aria-label="Thu nhỏ mô hình">−</button>
                            <button type="button" class="btn btn-sm btn-outline-secondary" data-dem-admin-action="fit" aria-label="Vừa khung mô hình"><i class="bi bi-arrows-angle-contract" aria-hidden="true"></i></button>
                            <button type="button" class="btn btn-sm btn-outline-secondary" data-dem-admin-action="in" aria-label="Phóng to mô hình">+</button>
                        </div>
                    </div>
                    <div class="dem-grid-viewport management-dem-viewport"><canvas id="management-dem-canvas" tabindex="0" role="application" aria-label="Mô hình DEM. Dùng phím mũi tên để chọn ô và Enter để đặt trạm."></canvas></div>
                    <p class="management-dem-selection" id="management-dem-selection" role="status" aria-live="polite">${demSelectionText}</p>
                    <div class="card border mt-3 shadow-none bg-body-tertiary" id="management-dem-georef-card" style="border-radius: 8px;">
                        <div class="card-body p-3">
                            <div class="d-flex justify-content-between align-items-center mb-2 flex-wrap gap-2">
                                <span class="fw-bold small text-uppercase" style="letter-spacing: 0.5px;">
                                    <i class="bi bi-geo-alt-fill text-primary me-1" aria-hidden="true"></i>Thông số tọa độ &amp; Địa lý DEM
                                </span>
                                ${editDemButtonHtml}
                            </div>
                            <div class="row g-2 small">
                                <div class="col-6 col-md-3">
                                    <span class="text-muted d-block" style="font-size: 0.78rem;">Hệ tọa độ (CRS)</span>
                                    <strong id="dem-georef-crs">EPSG:32648 (UTM 48N)</strong>
                                </div>
                                <div class="col-6 col-md-3">
                                    <span class="text-muted d-block" style="font-size: 0.78rem;">Gốc Tây-Nam (X, Y)</span>
                                    <strong id="dem-georef-origin">—</strong>
                                </div>
                                <div class="col-6 col-md-3">
                                    <span class="text-muted d-block" style="font-size: 0.78rem;">Tâm địa lý (WGS84)</span>
                                    <strong id="dem-georef-center">—</strong>
                                </div>
                                <div class="col-6 col-md-3">
                                    <span class="text-muted d-block" style="font-size: 0.78rem;">Lưới &amp; Cao độ</span>
                                    <strong id="dem-georef-elevation">—</strong>
                                </div>
                            </div>
                        </div>
                    </div>`;
        } else {
            const emptyTitle = canUpload ? 'Chưa có mô hình địa hình' : 'Dự án chưa có DEM';
            const emptyDesc = canUpload ? 'Tải lên file ESRI ASCII Grid (.asc), hệ tọa độ UTM 48N.' : 'Liên hệ quản trị viên để tải mô hình DEM lên.';
            mainDemBody = `
                    <div class="management-dem-empty" role="status">
                        <i class="bi bi-mountains" aria-hidden="true"></i>
                        <strong>${emptyTitle}</strong>
                        <span>${emptyDesc}</span>
                    </div>`;
        }

        return `
            <section class="management-dem-workspace" aria-labelledby="management-dem-title">
                <div class="management-dem-heading">
                    <div><h2 id="management-dem-title">Địa hình số · ${this.escapeHtml(project?.name || this.getProjectName(this.currentProjectId))}</h2>
                    <p>${headingDesc}</p></div>
                    ${badgeHtml}
                </div>
                ${demUploadRowHtml}
                ${mainDemBody}
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
            try { result = JSON.parse(responseText); } catch (err) { console.debug('Response is not JSON:', err); }
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
            const viewer = await window.DemGrid.mount(canvas, grid, {
                selectable: true,
                onSelect: (point, interaction) => this.handleProjectDemCell(point, interaction),
            });
            if (!canvas.isConnected || requestId !== this._managementDemRequest) { viewer.destroy(); return; }
            this._managementDemViewer = viewer;
            document.querySelectorAll('[data-dem-admin-action]').forEach(button => button.onclick = () => {
                const action = button.dataset.demAdminAction;
                if (action === 'in') this._managementDemViewer?.zoomIn();
                else if (action === 'out') this._managementDemViewer?.zoomOut();
                else this._managementDemViewer?.fit();
            });
            const selector = document.getElementById('management-dem-select');
            if (selector) selector.onchange = () => this.loadProjectDem(selector.value);
            if (status) status.textContent = `${grid.ncols} × ${grid.nrows} ô · cao độ ${grid.min.toFixed(1)}–${grid.max.toFixed(1)} m · UTM 48N`;

            const centerEasting = grid.xllcorner + (grid.ncols * grid.cellsize) / 2;
            const centerNorthing = grid.yllcorner + (grid.nrows * grid.cellsize) / 2;
            const centerWgs = window.DemGrid.utm48ToWgs84(centerEasting, centerNorthing);

            const elOrigin = document.getElementById('dem-georef-origin');
            const elCenter = document.getElementById('dem-georef-center');
            const elElev = document.getElementById('dem-georef-elevation');
            if (elOrigin) elOrigin.textContent = `X: ${grid.xllcorner.toFixed(1)}, Y: ${grid.yllcorner.toFixed(1)}`;
            if (elCenter) elCenter.textContent = `${centerWgs.lat.toFixed(6)}°, ${centerWgs.lon.toFixed(6)}°`;
            if (elElev) elElev.textContent = `${grid.ncols} × ${grid.nrows} ô (${grid.cellsize}m) · ${grid.min.toFixed(1)}m đến ${grid.max.toFixed(1)}m`;
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

    handleProjectDemCell(point, interaction = null) {
        const commit = interaction?.commit ?? true;
        const status = document.getElementById('management-dem-selection');
        if (!commit) {
            if (status) status.textContent = `${this._managementDemPlacement ? 'Đang chọn' : 'Ô'} ${point.column + 1}, ${point.row + 1} · cao độ ${point.elevation.toFixed(1)} m${this._managementDemPlacement ? ' · nhấn Enter để đặt trạm' : ''}`;
            return;
        }
        if (!this._managementDemPlacement) {
            if (status) status.textContent = `Ô ${point.column + 1}, ${point.row + 1} · cao độ ${point.elevation.toFixed(1)} m`;
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

    openEditDemCoordinatesModal() {
        const modalEl = document.getElementById('editDemCoordinatesModal');
        if (!modalEl || !this._selectedDemId) return;
        const project = (this.projectsData || []).find(item => String(item.id) === String(this.currentProjectId));
        const dem = project?.dems?.find(model => model.id === this._selectedDemId) || this._managementDemModel;
        if (!dem) return;

        document.getElementById('edit-dem-id').value = dem.id;
        document.getElementById('edit-dem-name').value = dem.name || '';
        document.getElementById('edit-dem-xll').value = dem.xllcorner != null ? Number(dem.xllcorner).toFixed(4) : '';
        document.getElementById('edit-dem-yll').value = dem.yllcorner != null ? Number(dem.yllcorner).toFixed(4) : '';

        if (this._managementDemGrid && dem.xllcorner != null && dem.yllcorner != null) {
            const grid = this._managementDemGrid;
            const centerE = Number(dem.xllcorner) + (grid.ncols * grid.cellsize) / 2;
            const centerN = Number(dem.yllcorner) + (grid.nrows * grid.cellsize) / 2;
            const centerWgs = window.DemGrid.utm48ToWgs84(centerE, centerN);
            document.getElementById('edit-dem-lat').value = centerWgs.lat.toFixed(7);
            document.getElementById('edit-dem-lon').value = centerWgs.lon.toFixed(7);
        }

        const modal = new bootstrap.Modal(modalEl);
        modal.show();
    }

    onDemUtmInput() {
        if (!this._managementDemGrid || !window.DemGrid) return;
        const xll = Number.parseFloat(document.getElementById('edit-dem-xll')?.value);
        const yll = Number.parseFloat(document.getElementById('edit-dem-yll')?.value);
        if (!Number.isFinite(xll) || !Number.isFinite(yll)) return;
        const grid = this._managementDemGrid;
        const centerE = xll + (grid.ncols * grid.cellsize) / 2;
        const centerN = yll + (grid.nrows * grid.cellsize) / 2;
        const centerWgs = window.DemGrid.utm48ToWgs84(centerE, centerN);
        const latInput = document.getElementById('edit-dem-lat');
        const lonInput = document.getElementById('edit-dem-lon');
        if (latInput) latInput.value = centerWgs.lat.toFixed(7);
        if (lonInput) lonInput.value = centerWgs.lon.toFixed(7);
    }

    onDemWgsInput() {
        if (!this._managementDemGrid || !window.DemGrid?.wgs84ToUtm48) return;
        const lat = Number.parseFloat(document.getElementById('edit-dem-lat')?.value);
        const lon = Number.parseFloat(document.getElementById('edit-dem-lon')?.value);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
        const utm = window.DemGrid.wgs84ToUtm48(lat, lon);
        const grid = this._managementDemGrid;
        const xll = utm.easting - (grid.ncols * grid.cellsize) / 2;
        const yll = utm.northing - (grid.nrows * grid.cellsize) / 2;
        const xllInput = document.getElementById('edit-dem-xll');
        const yllInput = document.getElementById('edit-dem-yll');
        if (xllInput) xllInput.value = xll.toFixed(4);
        if (yllInput) yllInput.value = yll.toFixed(4);
    }

    async saveDemCoordinates() {
        const demId = document.getElementById('edit-dem-id')?.value;
        const name = document.getElementById('edit-dem-name')?.value?.trim();
        const xll = Number.parseFloat(document.getElementById('edit-dem-xll')?.value);
        const yll = Number.parseFloat(document.getElementById('edit-dem-yll')?.value);
        const saveBtn = document.getElementById('btn-save-dem-coords');

        if (!demId || !this.currentProjectId) return;
        if (!name) {
            window.toast?.warning('Vui lòng nhập tên khu địa hình');
            return;
        }
        if (!Number.isFinite(xll) || !Number.isFinite(yll)) {
            window.toast?.warning('Vui lòng nhập tọa độ X và Y hợp lệ');
            return;
        }

        if (saveBtn) { saveBtn.disabled = true; saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Đang lưu…'; }
        try {
            const response = await fetch(`/api/admin/projects/${this.currentProjectId}/dems/${encodeURIComponent(demId)}`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ xllcorner: xll, yllcorner: yll, name: name })
            });

            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || 'Không thể lưu tọa độ DEM');
            }

            const result = await response.json();
            const project = (this.projectsData || []).find(item => String(item.id) === String(this.currentProjectId));
            if (project) {
                project.dems = result.models || [];
            }
            bootstrap.Modal.getInstance(document.getElementById('editDemCoordinatesModal'))?.hide();
            window.toast?.success('✅ Đã cập nhật tọa độ mô hình DEM thành công!');
            await this.loadProjectDem(demId);
        } catch (error) {
            window.toast?.error(error.message || 'Lỗi khi cập nhật tọa độ DEM');
        } finally {
            if (saveBtn) { saveBtn.disabled = false; saveBtn.innerHTML = '<i class="bi bi-check2-circle me-1"></i>Lưu tọa độ DEM'; }
        }
    }

}
window.applyAdminFeature(AdminStationsFeature);
})();
