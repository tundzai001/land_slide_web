(() => {
class AdminProjectsFeature extends window.AdminManager {
    setupProjectMapPosition(prefix, location = null) {
        const mode = document.getElementById(`${prefix}-map-mode`);
        if (!mode) return;
        mode.value = prefix === 'project' ? 'manual' : (location?.map_mode || (location?.lat != null && location?.lon != null ? 'manual' : 'auto'));
        const pickerContainer = document.getElementById(`${prefix}-map-picker`);
        const pickerToggle = document.getElementById(`${prefix}-map-picker-toggle`);
        if (pickerContainer) pickerContainer.hidden = true;
        if (pickerToggle) {
            pickerToggle.setAttribute('aria-expanded', 'false');
            pickerToggle.innerHTML = '<i class="bi bi-map me-1" aria-hidden="true"></i>Chọn điểm dự án trên bản đồ';
        }
        for (const key of ['lat', 'lon']) {
            const input = document.getElementById(`${prefix}-map-${key}`);
            input.value = location?.[key] ?? '';
            input.onblur = () => {
                this.collectProjectMapPosition(prefix, false);
                this.updateProjectPickerMarker(prefix);
            };
            input.oninput = () => {
                input.removeAttribute('aria-invalid');
                document.getElementById(`${prefix}-map-error`).hidden = true;
            };
        }
        mode.onchange = () => this.syncProjectMapPosition(prefix, true);
        if (pickerToggle) pickerToggle.onclick = () => this.toggleProjectMapPicker(prefix);
        this.syncProjectMapPosition(prefix);
        this.updateProjectPickerMarker(prefix);
    }

    async ensureProjectMapLibrary() {
        if (window.L) return;
        const cssUrl = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
        const jsUrl = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
        if (!document.querySelector(`link[href="${cssUrl}"]`)) {
            const style = document.createElement('link');
            style.rel = 'stylesheet';
            style.href = cssUrl;
            document.head.appendChild(style);
        }
        if (!this._projectLeafletPromise) {
            this._projectLeafletPromise = new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = jsUrl;
                script.onload = resolve;
                script.onerror = () => reject(new Error('Không tải được bản đồ. Bạn vẫn có thể nhập tọa độ trực tiếp.'));
                document.head.appendChild(script);
            });
        }
        await this._projectLeafletPromise;
    }

    async toggleProjectMapPicker(prefix) {
        const container = document.getElementById(`${prefix}-map-picker`);
        const button = document.getElementById(`${prefix}-map-picker-toggle`);
        if (!container || !button) return;
        const opening = container.hidden;
        container.hidden = !opening;
        button.setAttribute('aria-expanded', String(opening));
        button.innerHTML = opening
            ? '<i class="bi bi-map me-1" aria-hidden="true"></i>Ẩn bản đồ chọn điểm'
            : '<i class="bi bi-map me-1" aria-hidden="true"></i>Chọn điểm dự án trên bản đồ';
        if (!opening) return;
        try {
            await this.ensureProjectMapLibrary();
            const element = document.getElementById(`${prefix}-map-picker-canvas`);
            let picker = this._projectMapPickers?.get(prefix);
            if (!picker) {
                this._projectMapPickers ||= new Map();
                const lat = Number(document.getElementById(`${prefix}-map-lat`).value);
                const lon = Number(document.getElementById(`${prefix}-map-lon`).value);
                const hasPoint = Number.isFinite(lat) && Number.isFinite(lon) && (lat !== 0 || lon !== 0);
                const map = window.L.map(element, { scrollWheelZoom: false }).setView(hasPoint ? [lat, lon] : [21.5, 104.5], hasPoint ? 12 : 6);
                window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    maxZoom: 19,
                    attribution: '&copy; OpenStreetMap',
                }).addTo(map);
                picker = { map, marker: null };
                map.on('click', event => this.setProjectMapPoint(prefix, event.latlng.lat, event.latlng.lng));
                this._projectMapPickers.set(prefix, picker);
                this.updateProjectPickerMarker(prefix);
            }
            requestAnimationFrame(() => picker.map.invalidateSize());
        } catch (error) {
            container.hidden = false;
            const hint = document.getElementById(`${prefix}-map-hint`);
            hint.textContent = error.message;
            hint.setAttribute('role', 'alert');
        }
    }

    setProjectMapPoint(prefix, lat, lon) {
        if (document.getElementById(`${prefix}-map-mode`).value !== 'manual') return;
        document.getElementById(`${prefix}-map-lat`).value = Number(lat).toFixed(7);
        document.getElementById(`${prefix}-map-lon`).value = Number(lon).toFixed(7);
        this.syncProjectMapPosition(prefix);
        this.updateProjectPickerMarker(prefix);
    }

    updateProjectPickerMarker(prefix) {
        const picker = this._projectMapPickers?.get(prefix);
        if (!picker) return;
        const latValue = document.getElementById(`${prefix}-map-lat`).value.trim();
        const lonValue = document.getElementById(`${prefix}-map-lon`).value.trim();
        if (!latValue && !lonValue) {
            if (picker.marker) picker.map.removeLayer(picker.marker);
            picker.marker = null;
            picker.map.setView([21.5, 104.5], 6);
            return;
        }
        const lat = Number(latValue);
        const lon = Number(lonValue);
        if (!latValue || !lonValue || !Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180 || (lat === 0 && lon === 0)) return;
        if (!picker.marker) picker.marker = window.L.marker([lat, lon], { draggable: true }).addTo(picker.map);
        else picker.marker.setLatLng([lat, lon]);
        picker.marker.off('dragend');
        picker.marker.on('dragend', event => {
            const point = event.target.getLatLng();
            this.setProjectMapPoint(prefix, point.lat, point.lng);
        });
        if (picker.map.getZoom() < 10) picker.map.setView([lat, lon], 12);
    }

    syncProjectMapPosition(prefix, recalculate = false) {
        const manual = document.getElementById(`${prefix}-map-mode`).value === 'manual';
        const pickerToggle = document.getElementById(`${prefix}-map-picker-toggle`);
        if (pickerToggle) {
            pickerToggle.disabled = !manual;
            if (!manual) {
                pickerToggle.setAttribute('aria-expanded', 'false');
                pickerToggle.innerHTML = '<i class="bi bi-map me-1" aria-hidden="true"></i>Chọn điểm dự án trên bản đồ';
            }
        }
        const pickerContainer = document.getElementById(`${prefix}-map-picker`);
        if (!manual && pickerContainer) pickerContainer.hidden = true;
        const fields = ['lat', 'lon'].map(key => document.getElementById(`${prefix}-map-${key}`));
        fields.forEach(input => { input.readOnly = !manual; input.required = manual; input.removeAttribute('aria-invalid'); });
        document.getElementById(`${prefix}-map-error`).hidden = true;
        if (!manual && recalculate) {
            const points = (prefix === 'project-config' ? this.projectStationsData || [] : [])
                .map(station => station.location)
                .filter(point => point?.lat != null && point?.lon != null && String(point.lat).trim() !== '' && String(point.lon).trim() !== ''
                    && typeof point.lat !== 'boolean' && typeof point.lon !== 'boolean'
                    && Number.isFinite(Number(point.lat)) && Number.isFinite(Number(point.lon))
                    && Math.abs(Number(point.lat)) <= 90 && Math.abs(Number(point.lon)) <= 180
                    && !(Number(point.lat) === 0 && Number(point.lon) === 0));
            fields.forEach((input, index) => {
                const key = index === 0 ? 'lat' : 'lon';
                input.value = points.length ? (points.reduce((sum, point) => sum + Number(point[key]), 0) / points.length).toFixed(8) : '';
            });
        }
        document.getElementById(`${prefix}-map-hint`).textContent = manual
            ? (prefix === 'project'
                ? 'Điểm này đại diện cho công trình trên bản đồ; nhập tọa độ hoặc chọn vị trí trên bản đồ.'
                : 'Tọa độ WGS84 (độ thập phân). Điểm nhập tay giữ nguyên khi cảm biến thay đổi.')
            : (fields[0].value ? 'Tự cập nhật theo các trạm cảm biến có tọa độ hợp lệ.' : 'Điểm sẽ xuất hiện khi dự án có cảm biến với tọa độ hợp lệ.');
        this.updateProjectPickerMarker(prefix);
    }

    collectProjectMapPosition(prefix, focusError = true) {
        const mode = document.getElementById(`${prefix}-map-mode`)?.value || 'auto';
        if (mode === 'auto') return { mode };
        const fields = ['lat', 'lon'].map(key => document.getElementById(`${prefix}-map-${key}`));
        const invalid = fields.find(input => !input.value.trim() || !input.checkValidity() || !Number.isFinite(Number(input.value)));
        const zeroPoint = fields.every(input => Number(input.value) === 0);
        if (invalid || zeroPoint) {
            const input = invalid || fields[0];
            const error = document.getElementById(`${prefix}-map-error`);
            error.textContent = zeroPoint && !invalid ? 'Không dùng điểm (0, 0).' : 'Nhập vĩ độ từ -90 đến 90 và kinh độ từ -180 đến 180.';
            error.hidden = false;
            input.setAttribute('aria-invalid', 'true');
            if (focusError) input.focus();
            return null;
        }
        document.getElementById(`${prefix}-map-error`).hidden = true;
        return { mode, lat: Number(fields[0].value), lon: Number(fields[1].value) };
    }

    setProjectSaveBusy(prefix, busy) {
        const button = document.getElementById(`${prefix}-save-btn`);
        if (!button) return;
        button.disabled = busy;
        button.setAttribute('aria-busy', String(busy));
        if (busy) {
            button.dataset.idleLabel = button.innerHTML;
            button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Đang lưu…';
        } else if (button.dataset.idleLabel) button.innerHTML = button.dataset.idleLabel;
    }
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

        if (title) title.textContent = 'Danh mục dự án';
        const canEdit = this.currentUserRole === 'admin';
        if (actionButtons) {
            actionButtons.innerHTML = canEdit ? `
                <button class="btn btn-gradient" onclick="window.adminManager.openCreateProjectModal()">
                    <i class="bi bi-plus-circle me-2"></i>Tạo Dự án
                </button>
            ` : '';
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

        const cardsHtml = this.projectsData.map(p => {
            let locationText = '';
            if (p.location) {
                if (typeof p.location === 'string') {
                    locationText = p.location;
                } else {
                    const coords = `${p.location.lat ?? ''}, ${p.location.lon ?? ''}`;
                    locationText = p.location.address || p.location.source || coords;
                }
            }
            const locationHtml = p.location
                ? `<p class="project-location mb-0"><i class="bi bi-geo-alt" aria-hidden="true"></i><span>${this.escapeHtml(locationText)}</span></p>`
                : '';

            const editButtonsHtml = canEdit ? `<button class="btn btn-sm btn-outline-primary project-action-btn project-edit-btn" onclick="event.stopPropagation(); window.adminManager.openProjectConfigModal(${Number(p.id)})" title="Chỉnh sửa dự án" aria-label="Chỉnh sửa dự án ${this.escapeHtml(p.name)}">
                                        <i class="bi bi-pencil-square" aria-hidden="true"></i><span>Chỉnh sửa</span>
                                    </button>
                                    <button class="btn btn-sm btn-outline-danger project-action-btn" onclick="event.stopPropagation(); window.adminManager.deleteProject(${Number(p.id)})" title="Xóa dự án" aria-label="Xóa dự án ${this.escapeHtml(p.name)}">
                                        <i class="bi bi-trash" aria-hidden="true"></i>
                                    </button>` : '';

            return `
                    <div class="col-md-6 col-xl-4">
                        <article class="card project-card management-project-card h-100" onclick="window.adminManager.loadStations(${Number(p.id)})" onkeydown="if(event.target===this&&(event.key==='Enter'||event.key===' ')){event.preventDefault();window.adminManager.loadStations(${Number(p.id)})}" tabindex="0" aria-label="Mở dự án ${this.escapeHtml(p.name)}">
                            <div class="card-body">
                                <div class="d-flex justify-content-between align-items-start mb-3">
                                    <div class="d-flex align-items-center gap-3 min-w-0">
                                        <span class="project-icon" aria-hidden="true"><i class="bi bi-diagram-3"></i></span>
                                        <div class="min-w-0">
                                            <h5 class="card-title mb-1 text-truncate">${this.escapeHtml(p.name)}</h5>
                                            <small class="project-code">${this.escapeHtml(p.project_code)}</small>
                                        </div>
                                    </div>
                                    <span class="project-count"><strong>${Number(p.station_count) || 0}</strong> trạm</span>
                                </div>
                                <p class="project-description">${this.escapeHtml(p.description || 'Chưa có mô tả cho dự án này.')}</p>
                                ${locationHtml}
                                <p class="project-dem-summary mb-0"><i class="bi bi-layers" aria-hidden="true"></i>${Number(p.dems?.length) || 0} khu địa hình DEM</p>

                            </div>
                            <div class="card-footer">
                                <div class="d-flex gap-2 align-items-center">
                                    <button class="btn btn-sm btn-primary flex-grow-1" onclick="event.stopPropagation(); window.adminManager.loadStations(${Number(p.id)})">
                                        Mở dự án <i class="bi bi-arrow-right ms-1" aria-hidden="true"></i>
                                    </button>
                                    ${editButtonsHtml}
                                </div>
                            </div>
                        </article>
                    </div>`;
        }).join('');

        container.innerHTML = `
            <div class="project-directory-summary" aria-label="Tổng quan dự án">
                <span><strong>${this.projectsData.length}</strong> dự án</span>
                <span><strong>${this.projectsData.reduce((total, project) => total + (Number(project.station_count) || 0), 0)}</strong> trạm quan trắc</span>
            </div>
            <div class="row g-3 management-project-grid">
                ${cardsHtml}
            </div>
        `;
    }

    openCreateProjectModal() {
        document.getElementById('createProjectForm').reset();
        this.setupProjectMapPosition('project');
        const modal = new bootstrap.Modal(document.getElementById('createProjectModal'));
        modal.show();
    }

    async createProject() {
        if (document.getElementById('project-save-btn')?.disabled) return;
        const code = document.getElementById('project-code').value.trim();
        const name = document.getElementById('project-name').value.trim();
        const desc = document.getElementById('project-desc').value.trim();
        const location = document.getElementById('project-location').value.trim();
        const mapPosition = this.collectProjectMapPosition('project');
        if (!mapPosition) return;

        if (!code || !name) {
            window.toast?.warning('Vui lòng nhập đầy đủ thông tin');
            return;
        }

        try {
            this.setProjectSaveBusy('project', true);
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
                    location: location,
                    map_position: mapPosition,
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
            await this.loadProjects();

        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        } finally {
            this.setProjectSaveBusy('project', false);
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
            await this.loadProjects();

        } catch (e) {
            window.toast?.error('❌ Lỗi xóa dự án');
        }
    }

}
window.applyAdminFeature(AdminProjectsFeature);
})();
