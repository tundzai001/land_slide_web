(() => {
const escapeConfigHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
class AdminProjectConfigFeature extends window.AdminManager {
    // =========================================================================
    // PROJECT CONFIG (CORS Base & GNSS Clusters)
    // =========================================================================

    async openProjectConfigModal(projectId) {
        const project = (this.projectsData || []).find(p => p.id === projectId);
        if (!project) return;

        this.currentProjectId = projectId;
        this.projectStationsData = [];

        const locationText = typeof project.location === 'string'
            ? project.location
            : (project.location?.address || project.location?.source || '');
        document.getElementById('project-config-code').value = project.project_code || '';
        document.getElementById('project-config-name').value = project.name || '';
        document.getElementById('project-config-description').value = project.description || '';
        document.getElementById('project-config-location').value = locationText;
        this.setupProjectMapPosition('project-config', project.location);

        document.getElementById('projectConfigModalTitle').textContent = `Chỉnh sửa dự án: ${project.name}`;
        const clustersContainer = document.getElementById('project-gnss-clusters-container');
        clustersContainer.innerHTML = `
            <div class="project-config-skeleton" role="status" aria-live="polite">
                <span class="visually-hidden">Đang tải cấu hình dự án</span>
                <div class="skeleton-line skeleton-line-title"></div>
                <div class="skeleton-line"></div>
                <div class="skeleton-line skeleton-line-short"></div>
            </div>`;

        if (!this.projectConfigModal) {
            this.projectConfigModal = new bootstrap.Modal(document.getElementById('projectConfigModal'));
        }
        this.projectConfigModal.show();

        try {
            this._projectConfigCache ||= new Map();
            const cached = this._projectConfigCache.get(projectId);
            const cacheFresh = cached && Date.now() - cached.timestamp < 30000;
            const stationsPromise = cacheFresh
                ? Promise.resolve(cached.stations)
                : fetch(`/api/admin/projects/${projectId}/stations?include_runtime=false`, {
                    headers: { 'Authorization': `Bearer ${this.token}` }
                }).then(async res => {
                    if (!res.ok) throw new Error('Không thể tải danh sách trạm');
                    const stations = await res.json();
                    this._projectConfigCache.set(projectId, { stations, timestamp: Date.now() });
                    return stations;
                });

            const [stations] = await Promise.all([stationsPromise, this.fetchCorsStations()]);
            if (this.currentProjectId !== projectId) return;
            this.projectStationsData = stations;
            this.syncProjectMapPosition('project-config', true);
        } catch (e) {
            console.error('Error fetching project stations:', e);
            clustersContainer.innerHTML = `
                <div class="project-config-error" role="alert">
                    <i class="bi bi-exclamation-circle"></i>
                    <div><strong>Không tải được cấu hình.</strong><span>${e.message}</span></div>
                    <button type="button" class="btn btn-sm btn-outline-primary" onclick="window.adminManager.openProjectConfigModal(${projectId})">Thử lại</button>
                </div>`;
            return;
        }

        const clusters = project.gnss_clusters || [];
        clustersContainer.innerHTML = '';
        
        if (clusters.length === 0) {
            this.addClusterRow(clustersContainer);
        } else {
            clusters.forEach(c => this.addClusterRow(clustersContainer, c.name, c.description, c.base_station, c.stations, c.base_stream, c));
        }

        if (typeof this.loadAutoAdjustmentConfig === 'function') {
            this.loadAutoAdjustmentConfig(project);
        }
    }

    addClusterRow(container, name = '', desc = '', base_station_code = '', stations = [], base_stream = '', clusterConfig = {}) {
        const row = document.createElement('div');
        row.className = 'cluster-row row g-2 mb-2 align-items-center';
        
        const randomId = Math.random().toString(36).substring(2, 9);
        const stationOptions = (this.projectStationsData || []).map((s, idx) => {
            const isChecked = (stations || []).includes(s.station_code);
            const inputId = `chk_${s.station_code}_${randomId}_${idx}`;
            return `
                <div class="px-2 py-1">
                    <div class="form-check">
                        <input class="form-check-input station-checkbox" type="checkbox" value="${escapeConfigHtml(s.station_code)}" id="${escapeConfigHtml(inputId)}" ${isChecked ? 'checked' : ''} onchange="window.adminManager.updateSelectedStationsLabel(this)">
                        <label class="form-check-label text-slate-300 small" style="cursor: pointer;" for="${escapeConfigHtml(inputId)}">
                            ${escapeConfigHtml(s.station_name || s.name || s.station_code)} (${escapeConfigHtml(s.station_code)})
                        </label>
                    </div>
                </div>
            `;
        }).join('') || '<div class="px-3 py-2 text-muted small">Không tìm thấy trạm nào</div>';

        let baseOptionsHtml = '<option value="">-- Chọn Trạm Base --</option>';
        if (this.corsStationsData?.length > 0) {
            this.corsStationsData.forEach(st => {
                const isSelected = (st.name === base_station_code || st.code === base_station_code) ? 'selected' : '';
                const online = st.is_online === true || ['online', 'active', 'connected', 'streaming'].includes(String(st.status || '').toLowerCase());
                const alt = st.h ?? st.alt ?? 0;
                baseOptionsHtml += `<option value="${escapeConfigHtml(st.name || st.code)}" data-online="${online}" data-serial="${escapeConfigHtml(st.serial || '')}" data-lat="${st.lat}" data-lon="${st.lon}" data-alt="${alt}" data-streams="${encodeURIComponent(JSON.stringify(st.streams || []))}" data-service-config="${encodeURIComponent(JSON.stringify(st.service_config || {}))}" ${isSelected}>${online ? '🟢' : '🔴'} ${escapeConfigHtml(st.name || st.code)} (${online ? 'ONLINE' : 'OFFLINE'})</option>`;
            });
        }
        if (base_station_code && !this.corsStationsData?.some(st => (st.name === base_station_code || st.code === base_station_code))) {
            baseOptionsHtml += `<option value="${escapeConfigHtml(base_station_code)}" selected>${escapeConfigHtml(base_station_code)}</option>`;
        }

        const backupBaseCode = clusterConfig.backup_base_station || '';
        const backupBaseStream = clusterConfig.backup_base_stream || '';
        let backupBaseOptionsHtml = '<option value="">-- Backup fixed base (optional) --</option>';
        if (this.corsStationsData?.length > 0) {
            this.corsStationsData.forEach(st => {
                const selected = (st.name === backupBaseCode || st.code === backupBaseCode) ? 'selected' : '';
                const online = st.is_online === true || ['online', 'active', 'connected', 'streaming'].includes(String(st.status || '').toLowerCase());
                const alt = st.h ?? st.alt ?? 0;
                backupBaseOptionsHtml += `<option value="${escapeConfigHtml(st.name || st.code)}" data-online="${online}" data-serial="${escapeConfigHtml(st.serial || '')}" data-lat="${st.lat}" data-lon="${st.lon}" data-alt="${alt}" data-streams="${encodeURIComponent(JSON.stringify(st.streams || []))}" data-service-config="${encodeURIComponent(JSON.stringify(st.service_config || {}))}" ${selected}>${online ? '🟢' : '🔴'} ${escapeConfigHtml(st.name || st.code)} (${online ? 'ONLINE' : 'OFFLINE'})</option>`;
            });
        }
        if (backupBaseCode && !this.corsStationsData?.some(st => (st.name === backupBaseCode || st.code === backupBaseCode))) {
            backupBaseOptionsHtml += `<option value="${escapeConfigHtml(backupBaseCode)}" selected>${escapeConfigHtml(backupBaseCode)}</option>`;
        }

        const conflictBases = clusterConfig.conflict_bases || [];
        let conflictBaseOptionsHtml = '';
        if (this.corsStationsData) {
            this.corsStationsData.forEach(st => {
                const isSelected = conflictBases.some(cb => cb.serial === st.serial) ? 'selected' : '';
                conflictBaseOptionsHtml += `<option value="${escapeConfigHtml(st.serial)}" data-name="${escapeConfigHtml(st.name || st.code)}" ${isSelected}>${escapeConfigHtml(st.name || st.code)}</option>`;
            });
        }


        row.innerHTML = `
            <!-- COMPACT ROW -->
            <div class="col-md-2">
                <input type="text" class="form-control form-control-sm cluster-name fw-bold" placeholder="Tên cụm (vd: Cụm 1)" value="${escapeConfigHtml(name)}">
            </div>
            <div class="col-md-2">
                <select class="form-select form-select-sm cluster-type text-primary fw-medium" style="background-color: #f8fafc; border-color: #cbd5e1;">
                    <option value="normal" ${clusterConfig.cluster_type === 'total' ? '' : 'selected'}>⚡ Cụm thường</option>
                    <option value="total" ${clusterConfig.cluster_type === 'total' ? 'selected' : ''}>🌐 Cụm tổng</option>
                </select>
            </div>
            <div class="col-md-3">
                <div class="dropdown w-100">
                    <button class="btn btn-outline-secondary btn-sm dropdown-toggle w-100 text-start overflow-hidden text-truncate selected-stations-label" type="button" data-bs-toggle="dropdown" data-bs-auto-close="outside" aria-expanded="false">
                        Chọn trạm...
                    </button>
                    <div class="dropdown-menu p-2 station-checkbox-list w-100" style="min-width: 240px; max-height: 200px; overflow-y: auto;">
                        ${stationOptions}
                    </div>
                </div>
            </div>
            <div class="col-md-2">
                <input type="text" class="form-control form-control-sm cluster-desc" placeholder="Mô tả..." value="${escapeConfigHtml(desc)}">
            </div>
            <div class="col-md-3 text-end d-flex gap-1 justify-content-end">
                <button type="button" class="btn btn-sm btn-primary" onclick="const bsCollapse = new bootstrap.Collapse(this.closest('.cluster-row').querySelector('.config-collapse'), {toggle: true});">
                    <i class="bi bi-gear"></i> Cấu hình Base
                </button>
                <button type="button" class="btn btn-sm btn-outline-danger" onclick="this.closest('.cluster-row').remove()">
                    <i class="bi bi-trash"></i>
                </button>
            </div>
            
            <!-- COLLAPSED CONFIGURATION PANEL -->
            <div class="col-12 collapse config-collapse mt-2">
                <div class="card card-body bg-light border-0 shadow-sm p-3">
                    <div class="row">
                        <!-- Primary Base config -->
                        <div class="col-md-6 border-end">
                            <label class="form-label small fw-bold text-primary mb-1"><i class="bi bi-broadcast"></i> Trạm Base Chính</label>
                            <select class="form-select cluster-base-select mb-2" style="font-size:0.85rem;" onchange="window.adminManager.onBaseStationSelected(this)">
                                ${baseOptionsHtml}
                            </select>
                            <select class="form-select cluster-stream-select" style="font-size:0.85rem; display: ${base_stream ? 'block' : 'none'};" data-selected-stream="${escapeConfigHtml(base_stream)}">
                                <option value="">-- Chọn Luồng (S1/S2) --</option>
                            </select>
                            <div class="base-station-info mt-2" style="display: none; font-size: 0.75rem; background: rgba(14,165,233,0.08); border: 1px solid rgba(14,165,233,0.25); border-radius: 6px; padding: 8px;">
                                <div class="d-flex align-items-center gap-1 mb-1">
                                    <strong class="base-info-name text-info">--</strong>
                                </div>
                                <div class="text-muted" style="line-height: 1.4;">
                                    <span class="base-info-lat">--</span> · <span class="base-info-lon">--</span> · Alt: <span class="base-info-alt">--</span>m
                                </div>
                            </div>
                        </div>
                        
                        <!-- Conflict Bases config -->
                        <div class="col-12 mt-3 conflict-bases-container" style="display: ${clusterConfig.cluster_type === 'total' ? 'block' : 'none'};">
                            <label class="form-label small fw-bold text-danger mb-1"><i class="bi bi-power"></i> Các Trạm Base Phụ Cần Tắt (Khi chạy Cụm Tổng)</label>
                            <select class="form-select cluster-conflict-bases-select mb-2" multiple style="font-size:0.85rem; height: 80px;">
                                ${conflictBaseOptionsHtml}
                            </select>
                            <div class="form-text mt-0" style="font-size: 0.75rem;">Chọn các trạm vật lý phụ thuộc (VD: SinQuyen1) cần ép đi ngủ để tránh xung đột mốc khi Base Chính đẩy S2. Nhấn Ctrl để chọn nhiều.</div>
                        </div>
                        
                        <!-- Backup Base config -->
                        <div class="col-md-6">
                            <label class="form-label small fw-bold text-warning mb-1"><i class="bi bi-shield-check"></i> Trạm Base Dự Phòng</label>
                            <select class="form-select cluster-backup-base-select mb-2" style="font-size:0.85rem;" onchange="window.adminManager.onBaseStationSelected(this)">
                                ${backupBaseOptionsHtml}
                            </select>
                            <select class="form-select cluster-backup-stream-select" style="font-size:0.85rem; display:${backupBaseStream ? 'block' : 'none'};" data-selected-stream="${escapeConfigHtml(backupBaseStream)}">
                                <option value="">-- Chọn Luồng Base Phụ --</option>
                            </select>
                            <div class="backup-base-station-info mt-2" style="display:none; font-size:0.75rem; background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.25); border-radius:6px; padding:8px;">
                                <strong class="base-info-name text-warning">--</strong>
                                <div class="text-muted"><span class="base-info-lat">--</span> · <span class="base-info-lon">--</span> · Alt: <span class="base-info-alt">--</span>m</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        container.appendChild(row);

        const clusterTypeSelect = row.querySelector('.cluster-type');
        const conflictBasesContainer = row.querySelector('.conflict-bases-container');
        if (clusterTypeSelect && conflictBasesContainer) {
            clusterTypeSelect.addEventListener('change', function() {
                conflictBasesContainer.style.display = this.value === 'total' ? 'block' : 'none';
            });
        }

        const baseSelect = row.querySelector('.cluster-base-select');
        if (baseSelect?.value) {
            this.onBaseStationSelected(baseSelect);
        }
        const backupBaseSelect = row.querySelector('.cluster-backup-base-select');
        if (backupBaseSelect?.value) {
            this.onBaseStationSelected(backupBaseSelect);
        }

        const firstCheckbox = row.querySelector('.station-checkbox');
        if (firstCheckbox) {
            this.updateSelectedStationsLabel(firstCheckbox);
        }
    }

    onBaseStationSelected(selectEl) {
        const row = selectEl.closest('.cluster-row');
        const selectedOpt = selectEl.options[selectEl.selectedIndex];
        const isBackup = selectEl.classList.contains('cluster-backup-base-select');
        
        // --- 1. Stream Selection ---
        const streamSelect = row.querySelector(
            isBackup ? '.cluster-backup-stream-select' : '.cluster-stream-select'
        );
        const selectedStreamVal = streamSelect.dataset.selectedStream;
        
        streamSelect.innerHTML = '<option value="">-- Chọn Luồng --</option>';
        
        if (selectedOpt?.dataset.devices) {
            try {
                const devices = JSON.parse(decodeURIComponent(selectedOpt.dataset.devices));
                const gnssDevices = devices.filter(d => d.device_type === 'gnss' || d.device_code.toLowerCase().includes('gnss') || d.device_code.toLowerCase().includes('s1') || d.device_code.toLowerCase().includes('s2'));
                
                if (gnssDevices.length > 0) {
                    gnssDevices.forEach(d => {
                        const isSelected = (d.device_code === selectedStreamVal || d.mqtt_topic === selectedStreamVal) ? 'selected' : '';
                        streamSelect.innerHTML += `<option value="${d.device_code}" ${isSelected}>${d.name || d.device_code} (${d.mqtt_topic || 'No topic'})</option>`;
                    });
                    streamSelect.style.display = 'block';
                } else {
                    streamSelect.style.display = 'none';
                }
            } catch(e) {
                console.error("Error parsing devices config", e);
                streamSelect.style.display = 'none';
            }
        } else if (selectedOpt?.dataset.streams) {
            try {
                const streams = JSON.parse(decodeURIComponent(selectedOpt.dataset.streams));
                if (streams.length > 0) {
                    streams.forEach(s => {
                        const isSelected = (s.stream_id === selectedStreamVal || s.mountpoint === selectedStreamVal) ? 'selected' : '';
                        const hostLabel = s.host ? ` [${s.host}:${s.port}]` : '';
                        streamSelect.innerHTML += `<option value="${escapeConfigHtml(s.stream_id)}" data-server-id="${escapeConfigHtml(s.server_id || String(s.stream_id || '').replace(/\D/g, ''))}" data-host="${escapeConfigHtml(s.host || '')}" data-port="${escapeConfigHtml(s.port || '')}" data-mp="${escapeConfigHtml(s.mountpoint || '')}" ${isSelected}>Luồng: ${escapeConfigHtml(String(s.stream_id || '').toUpperCase())} - ${escapeConfigHtml(s.mountpoint)}${escapeConfigHtml(hostLabel)}</option>`;
                    });
                    streamSelect.style.display = 'block';
                } else {
                    streamSelect.style.display = 'none';
                }
            } catch(e) {
                console.error("Error parsing streams", e);
                streamSelect.style.display = 'none';
            }
        } else {
            // No devices or mountpoints
            streamSelect.style.display = 'none';
        }

        // --- 2. Base Info Display ---
        const infoPanel = row.querySelector(
            isBackup ? '.backup-base-station-info' : '.base-station-info'
        );
        if (!selectEl.value) {
            if (infoPanel) infoPanel.style.display = 'none';
            return;
        }

        const lat = selectedOpt.dataset.lat || '--';
        const lon = selectedOpt.dataset.lon || '--';
        const alt = selectedOpt.dataset.alt || '0';
        const name = selectEl.value;
        const online = selectedOpt.dataset.online === 'true';

        if (infoPanel) {
            infoPanel.querySelector('.base-info-name').textContent = `${online ? '🟢 ONLINE' : '🔴 OFFLINE'} · ${name}`;
            infoPanel.querySelector('.base-info-lat').textContent = `Lat: ${lat}`;
            infoPanel.querySelector('.base-info-lon').textContent = `Lon: ${lon}`;
            infoPanel.querySelector('.base-info-alt').textContent = alt;
            infoPanel.style.display = 'block';
        }
    }

    updateSelectedStationsLabel(el) {
        const row = el.closest('.cluster-row');
        const checkedList = Array.from(row.querySelectorAll('.station-checkbox:checked')).map(c => c.value);
        const btn = row.querySelector('.selected-stations-label');
        if (!btn) return;
        
        if (checkedList.length === 0) {
            btn.textContent = 'Chọn trạm...';
            btn.classList.remove('btn-outline-primary');
            btn.classList.add('btn-outline-secondary');
        } else {
            btn.textContent = `Đã chọn: ${checkedList.join(', ')}`;
            btn.classList.remove('btn-outline-secondary');
            btn.classList.add('btn-outline-primary');
        }
    }

    async fetchCorsStations() {
        if (this.corsStationsData?.length > 0) return; // Cache check

        try {
            const res = await fetch('/api/admin/projects/cors-stations', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) throw new Error('Không thể lấy danh sách trạm CORS từ URL');
            
            const data = await res.json();
            const stations = Array.isArray(data) ? data : (data.data || data.stations || []);
            
            this.corsStationsData = stations;
            
        } catch (e) {
            console.error(e);
            window.toast?.error('❌ ' + e.message);
        }
    }

    _parseClusterRow(row) {
        const name = row.querySelector('.cluster-name')?.value.trim();
        if (!name) return null;

        const desc = row.querySelector('.cluster-desc')?.value.trim() || '';
        const baseSelect = row.querySelector('.cluster-base-select');
        const baseStation = baseSelect?.value || '';
        const selectedOpt = baseSelect?.options[baseSelect.selectedIndex];
        const baseLat = selectedOpt?.dataset?.lat ? Number.parseFloat(selectedOpt.dataset.lat) : null;
        const baseLon = selectedOpt?.dataset?.lon ? Number.parseFloat(selectedOpt.dataset.lon) : null;
        const baseAlt = selectedOpt?.dataset?.alt ? Number.parseFloat(selectedOpt.dataset.alt) : null;
        const backupSelect = row.querySelector('.cluster-backup-base-select');
        const backupOpt = backupSelect?.options[backupSelect.selectedIndex];
        const backupStreamSelect = row.querySelector('.cluster-backup-stream-select');
        const primaryStreamSelect = row.querySelector('.cluster-stream-select');
        const st = Array.from(row.querySelectorAll('.station-checkbox:checked')).map(c => c.value);
        const conflictBasesSelect = row.querySelector('.cluster-conflict-bases-select');
        const conflictBases = conflictBasesSelect ? Array.from(conflictBasesSelect.selectedOptions).map(opt => ({
            serial: opt.value,
            name: opt.dataset.name
        })) : [];

        const backupBaseStation = backupSelect?.value || '';
        const backupStreamHost = backupStreamSelect?.selectedIndex >= 0 ? (backupStreamSelect.options[backupStreamSelect.selectedIndex]?.dataset?.host || '') : '';
        const backupStreamMp = backupStreamSelect?.selectedIndex >= 0 ? (backupStreamSelect.options[backupStreamSelect.selectedIndex]?.dataset?.mp || '') : '';
        const primaryStreamMp = primaryStreamSelect?.selectedIndex >= 0 ? (primaryStreamSelect.options[primaryStreamSelect.selectedIndex]?.dataset?.mp || '') : '';
        let error = '';
        if (backupBaseStation && backupBaseStation === baseStation) {
            error = `${name}: base dự phòng phải khác base chính.`;
        } else if (backupBaseStation && (!backupStreamHost || !backupStreamMp)) {
            error = `${name}: hãy chọn đúng luồng CORS S1/S2 cho base dự phòng.`;
        } else if (backupBaseStation && backupStreamMp !== primaryStreamMp) {
            error = `${name}: luồng S2 dự phòng phải gửi vào cùng mountpoint của S1 chính.`;
        }

        const cluster = {
            name, description: desc,
            base_station: baseStation,
            base_lat: baseLat, base_lon: baseLon, base_alt: baseAlt,
            base_stream: row.querySelector('.cluster-stream-select')?.value || '',
            base_stream_host: (row.querySelector('.cluster-stream-select')?.selectedIndex >= 0) ? (row.querySelector('.cluster-stream-select')?.options[row.querySelector('.cluster-stream-select')?.selectedIndex]?.dataset?.host || '') : '',
            base_stream_port: (row.querySelector('.cluster-stream-select')?.selectedIndex >= 0) ? (row.querySelector('.cluster-stream-select')?.options[row.querySelector('.cluster-stream-select')?.selectedIndex]?.dataset?.port || '') : '',
            base_stream_mp: (row.querySelector('.cluster-stream-select')?.selectedIndex >= 0) ? (row.querySelector('.cluster-stream-select')?.options[row.querySelector('.cluster-stream-select')?.selectedIndex]?.dataset?.mp || '') : '',
            base_service_config: selectedOpt?.dataset?.serviceConfig ? JSON.parse(decodeURIComponent(selectedOpt.dataset.serviceConfig)) : {},
            base_serial: selectedOpt?.dataset?.serial || '',
            base_server_id: row.querySelector('.cluster-stream-select')?.selectedIndex >= 0 ? (row.querySelector('.cluster-stream-select')?.options[row.querySelector('.cluster-stream-select')?.selectedIndex]?.dataset?.serverId || '') : '',
            backup_base_station: backupBaseStation,
            backup_base_lat: backupOpt?.dataset?.lat ? Number.parseFloat(backupOpt.dataset.lat) : null,
            backup_base_lon: backupOpt?.dataset?.lon ? Number.parseFloat(backupOpt.dataset.lon) : null,
            backup_base_alt: backupOpt?.dataset?.alt ? Number.parseFloat(backupOpt.dataset.alt) : null,
            backup_base_stream: backupStreamSelect?.value || '',
            backup_base_stream_host: backupStreamHost,
            backup_base_stream_port: backupStreamSelect?.selectedIndex >= 0 ? (backupStreamSelect.options[backupStreamSelect.selectedIndex]?.dataset?.port || '') : '',
            backup_base_stream_mp: backupStreamMp,
            backup_base_service_config: backupOpt?.dataset?.serviceConfig ? JSON.parse(decodeURIComponent(backupOpt.dataset.serviceConfig)) : {},
            backup_base_serial: backupOpt?.dataset?.serial || '',
            backup_base_server_id: backupStreamSelect?.selectedIndex >= 0 ? (backupStreamSelect.options[backupStreamSelect.selectedIndex]?.dataset?.serverId || '') : '',
            cluster_type: row.querySelector('.cluster-type')?.value || 'normal',
            conflict_bases: conflictBases,
            stations: st
        };
        return { cluster, error };
    }

    async saveProjectConfig() {
        if (document.getElementById('project-config-save-btn')?.disabled) return;
        const projectId = this.currentProjectId;
        if (!projectId) return;

        const projectCode = document.getElementById('project-config-code')?.value.trim() || '';
        const projectName = document.getElementById('project-config-name')?.value.trim() || '';
        const projectDescription = document.getElementById('project-config-description')?.value.trim() || '';
        const projectLocation = document.getElementById('project-config-location')?.value.trim() || '';
        const mapPosition = this.collectProjectMapPosition('project-config');
        if (!mapPosition) return;
        if (!projectCode || !projectName) {
            window.toast?.error('Mã dự án và tên dự án không được để trống');
            document.getElementById(!projectCode ? 'project-config-code' : 'project-config-name')?.focus();
            return;
        }

        // Collect Clusters
        const clusters = [];
        let clusterConfigError = '';
        document.querySelectorAll('#project-gnss-clusters-container .cluster-row').forEach(row => {
            const parsed = this._parseClusterRow(row);
            if (parsed) {
                if (parsed.error) clusterConfigError ||= parsed.error;
                clusters.push(parsed.cluster);
            }
        });

        if (clusterConfigError) {
            window.toast?.error(clusterConfigError);
            return;
        }

        try {
            this.setProjectSaveBusy('project-config', true);
            const res = await fetch(`/api/admin/projects/${projectId}`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    project_code: projectCode,
                    name: projectName,
                    description: projectDescription || null,
                    location: projectLocation || null,
                    map_position: mapPosition,
                    gnss_clusters: clusters,
                    auto_adjustment_config: typeof this.collectAutoAdjustmentConfig === 'function' ? this.collectAutoAdjustmentConfig() : undefined
                })
            });

            if (!res.ok) {
                const error = await res.json().catch(() => ({}));
                throw new Error(error.detail || 'Lỗi lưu cấu hình dự án');
            }

            window.toast?.success('Đã lưu thay đổi dự án');
            this.projectConfigModal.hide();
            await this.loadProjects();
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        } finally {
            this.setProjectSaveBusy('project-config', false);
        }
    }

}
window.applyAdminFeature(AdminProjectConfigFeature);
})();
