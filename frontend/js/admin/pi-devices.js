(() => {
class AdminPiDevicesFeature extends window.AdminManager {
    // =========================================================================
    // PI DEVICES MANAGEMENT
    // =========================================================================

    /** Load and render Pi devices in the "Pi Devices" tab */
    async loadPiDevices(isAuto = false) {
        if (isAuto && this._piSelectMode) return; // Skip auto-refresh when selecting to avoid wiping selection
        if (!isAuto) this._piSelectMode = false;
        try {
            const res = await fetch('/api/field/pi-devices', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) throw new Error('Failed to load Pi devices');
            let devices = await res.json();

            const isOperator = this.currentUserRole === 'operator';

            // ─── Operator: only show devices assigned to their projects ───
            if (isOperator && this.currentUserAssignedProjects?.length > 0) {
                const myProjects = this.currentUserAssignedProjects;
                devices = devices.filter(d =>
                    d.status === 'assigned' && d.project_id && myProjects.includes(d.project_id)
                );
            }

            this._piDevicesData = devices;

            if (!isOperator) {
                const pending = devices.filter(d => d.status === 'pending' || d.status === 'activating');
                const activated = devices.filter(d => d.status === 'activated');
                const assigned = devices.filter(d => d.status === 'assigned');

                // ─── Update summary cards ───
                const setCount = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
                setCount('pi-pending-count', pending.length);
                setCount('pi-activated-count', activated.length);
                setCount('pi-assigned-count', assigned.length);

                const descEl = document.getElementById('pi-pending-desc');
                if (descEl) descEl.textContent = pending.length === 0
                    ? 'No devices awaiting handshake'
                    : `${pending.length} device(s) awaiting activation`;
            }

            // ─── Render grid table ───
            this._renderPiGrid(devices);

            // ─── Inject action bar (admin only) ───
            if (isOperator) {
                // Operator: hide select toggle button, read-only view
                const selectToggle = document.getElementById('pi-select-toggle');
                if (selectToggle) selectToggle.style.display = 'none';
            } else if (!document.getElementById('pi-action-bar')) {
                const bar = document.createElement('div');
                bar.id = 'pi-action-bar';
                bar.style.cssText = `
                    position:fixed; bottom:-80px; left:50%; transform:translateX(-50%);
                    z-index:9999; padding:12px 24px; border-radius:16px;
                    background:rgba(15,23,42,.95); backdrop-filter:blur(12px);
                    border:1px solid rgba(255,255,255,.1); box-shadow:0 -4px 30px rgba(0,0,0,.4);
                    display:flex; gap:10px; align-items:center;
                    transition: bottom .35s cubic-bezier(.4,0,.2,1);
                `;
                bar.innerHTML = `
                    <span id="pi-sel-count" style="color:#94a3b8;font-size:.85rem;margin-right:6px">0 đã chọn</span>
                    <button class="btn btn-sm btn-primary"   id="pi-act-activate" onclick="window.adminManager._piActionBatch('activate')" style="display:none">
                        <i class="bi bi-key me-1"></i>Kích hoạt</button>
                    <button class="btn btn-sm btn-warning"   id="pi-act-unassign" onclick="window.adminManager._piActionBatch('unassign')" style="display:none">
                        <i class="bi bi-x-circle me-1"></i>Bỏ gán</button>
                    <button class="btn btn-sm btn-secondary" id="pi-act-lock"     onclick="window.adminManager._piActionBatch('lock')" style="display:none">
                        <i class="bi bi-lock me-1"></i>Khóa</button>
                    <button class="btn btn-sm btn-success"   id="pi-act-unlock"   onclick="window.adminManager._piActionBatch('unlock')" style="display:none">
                        <i class="bi bi-unlock me-1"></i>Mở khóa</button>
                    <button class="btn btn-sm btn-info"      id="pi-act-reset"    onclick="window.adminManager._piActionBatch('reset')" style="display:none">
                        <i class="bi bi-arrow-counterclockwise me-1"></i>Reset</button>
                    <button class="btn btn-sm btn-danger"    id="pi-act-delete"   onclick="window.adminManager._piActionBatch('delete')">
                        <i class="bi bi-trash me-1"></i>Xóa</button>
                    <button class="btn btn-sm btn-outline-warning" id="pi-act-assign-center" onclick="window.adminManager.assignSelectedPointToCenter()" style="display:none">
                        <i class="bi bi-link-45deg me-1"></i>Gán vào Pi Trung tâm</button>
                    <button class="btn btn-sm btn-outline-light ms-2" onclick="window.adminManager.togglePiSelectMode()">
                        <i class="bi bi-x-lg"></i></button>
                `;
                document.body.appendChild(bar);
            }
        } catch (e) {
            console.error('Error loading Pi devices:', e);
            window.toast?.error('Không thể tải danh sách Pi');
        }
    }

    /** Render devices into the grid table */
    _renderPiGrid(devices) {
        const tbody = document.getElementById('pi-grid-body');
        const infoEl = document.getElementById('pi-grid-info');
        if (!tbody) return;

        // Tách riêng pi center và pi point
        const trueCenters = devices.filter(d => (d.pi_center_id === null || d.pi_center_id === undefined) && d.device_type !== 'pi_point');
        const points = devices.filter(d => d.pi_center_id !== null && d.pi_center_id !== undefined);
        const unassignedPoints = devices.filter(d => (d.pi_center_id === null || d.pi_center_id === undefined) && d.device_type === 'pi_point');

        if (trueCenters.length === 0 && points.length === 0 && unassignedPoints.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">No devices found</td></tr>';
            if (infoEl) infoEl.textContent = 'Showing 0 entries';
            return;
        }

        let html = '';
        const statusColors = { pending: '#f59e0b', activating: '#f59e0b', activated: '#22c55e', assigned: '#0ea5e9' };
        const statusLabels = { pending: 'Pending', activating: 'Activating', activated: 'Activated', assigned: 'Assigned' };

        // Render từng center
        trueCenters.forEach(c => {
            const childPoints = points.filter(p => p.pi_center_id === c.id);

            // Status badge for center
            const color = statusColors[c.status] || '#6b7280';
            let statusBadge = `<span class="badge" style="background:${color};color:#000;font-size:.72rem">â— ${statusLabels[c.status] || c.status}</span>`;
            if (c.is_locked) {
                statusBadge += ` <span class="badge bg-danger" style="font-size:.65rem" title="Thiết bị bị khóa">🔒</span>`;
            }
            if (c.status === 'assigned') {
                statusBadge += `<br><small class="pi-assign-detail">${c.station_name || ''}${c.project_name ? ' · ' + c.project_name : ''}</small>`;

                // Thêm nút gắn Pi Hiện trường (nếu chưa có thiết bị con nào được gắn)
                if (childPoints.length === 0) {
                    statusBadge += `<div class="mt-1"><button class="btn btn-sm btn-outline-success py-0 px-2" style="font-size:0.7rem" onclick="window.adminManager.openAssignPiPointModal(${c.id})"><i class="bi bi-plus"></i> Gắn Pi Hiện trường</button></div>`;
                }
            }

            let devType = 'Pi Trung tâm';
            if (c.device_type && c.device_type.toLowerCase() === 'win') devType = 'PC Window Trung tâm';

            let pointsHtml = '';
            if (childPoints.length > 0) {
                pointsHtml = childPoints.map(p => {
                    const pIsOnline = p.last_seen && (Date.now() / 1000 - p.last_seen) < 120;
                    const pLastPingText = p.last_seen ? this._formatTimeAgo(p.last_seen, pIsOnline) : 'â€”';
                    return `
                    <div style="margin-top: 6px; padding: 4px 8px; background-color: rgba(255, 193, 7, 0.15); border-left: 3px solid #ffc107; border-radius: 4px; font-size: 0.75rem; display: inline-block;">
                        <span class="badge bg-warning text-dark me-1" style="font-size:.6rem">Pi Hiện trường</span>
                        <strong style="color:var(--text-color)">${p.name}</strong>
                        <code class="text-muted mx-1">${p.serial}</code>
                        <span class="mx-1" style="font-size: 0.7rem; color: ${pIsOnline ? '#10b981' : '#ef4444'}">â— ${pLastPingText}</span>
                        <a href="javascript:void(0)" class="text-danger ms-2 text-decoration-none" title="Bỏ gán điểm này" onclick="window.adminManager.unassignPiDevice(${p.id}, event)">
                            <i class="bi bi-x-circle"></i>
                        </a>
                    </div>`;
                }).join('<br>');
            }

            // Box để bọc name
            const stationTag = c.station_id
                ? `<span class="badge me-2" style="background:#1e293b;color:#0ea5e9;border:1px solid #0ea5e933;font-size:.7rem">${c.station_id}</span>`
                : '';
            const nameLabel = c.status === 'assigned'
                ? `<strong>${c.station_name || c.name}</strong><br><small class="text-muted"><span class="badge bg-secondary me-1" style="font-size:.6rem">${devType}</span></small>`
                : `<strong>${c.name}</strong>`;

            const fullCellLabel = `<div style="line-height:1.4">${stationTag}${nameLabel}</div>${pointsHtml ? '<div>' + pointsHtml + '</div>' : ''}`;

            const isOnline = c.last_seen && (Date.now() / 1000 - c.last_seen) < 120;
            const lastPingText = c.last_seen ? this._formatTimeAgo(c.last_seen, isOnline) : 'â€”';

            html += `<tr class="pi-grid-row" data-pi-id="${c.id}" data-pi-status="${c.status}" data-pi-locked="${c.is_locked ? '1' : '0'}" data-pi-type="${c.device_type || 'pi'}" data-search="${(c.name + c.serial + (c.station_name || '')).toLowerCase()}" style="background-color: var(--bs-table-bg);">
            <td>
                <div class="pi-check-overlay" style="display:none">
                    <input type="checkbox" class="form-check-input pi-checkbox" data-pi-id="${c.id}"
                        style="width:18px;height:18px;cursor:pointer" onchange="window.adminManager._onPiCheckChange()">
                </div>
            </td>
            <td>${fullCellLabel}</td>
            <td><code style="font-size:.8rem;color:var(--text-muted)">${c.serial}</code></td>
            <td>${statusBadge}</td>
            <td><span class="${isOnline ? 'ping-online' : 'ping-offline'} me-1">â—</span><small>${lastPingText}</small></td>
        </tr>`;
        });

        // Những điểm (pi points) chưa được gán pi_center_id sẽ nằm riêng ở cuối
        // unassignedPoints đã được khai báo ở đầu hàm (line 1827)
        unassignedPoints.forEach(p => {
            const pColor = statusColors[p.status] || '#6b7280';
            let pStatusBadge = `<span class="badge" style="background:${pColor};color:#000;font-size:.72rem">â— ${statusLabels[p.status] || p.status}</span>`;
            if (p.is_locked) {
                pStatusBadge += ` <span class="badge bg-danger" style="font-size:.65rem" title="Thiết bị bị khóa">🔒</span>`;
            }

            const nameLabel = `<strong>${p.name}</strong><br><small class="text-muted"><span class="badge bg-warning text-dark me-1" style="font-size:.6rem">Pi Hiện trường</span><span style="font-size:.6rem">(Chưa Gắn)</span></small>`;
            const pIsOnline = p.last_seen && (Date.now() / 1000 - p.last_seen) < 120;
            const pLastPingText = p.last_seen ? this._formatTimeAgo(p.last_seen, pIsOnline) : 'â€”';

            html += `<tr class="pi-grid-row" data-pi-id="${p.id}" data-pi-status="${p.status}" data-pi-locked="${p.is_locked ? '1' : '0'}" data-pi-type="pi_point" data-search="${(p.name + p.serial).toLowerCase()}" style="background-color: var(--bs-table-bg);">
                <td>
                    <div class="pi-check-overlay" style="display:none">
                        <input type="checkbox" class="form-check-input pi-checkbox" data-pi-id="${p.id}"
                            style="width:18px;height:18px;cursor:pointer" onchange="window.adminManager._onPiCheckChange()">
                    </div>
                </td>
                <td><div style="line-height:1.4">${nameLabel}</div></td>
                <td><code style="font-size:.8rem;color:var(--text-muted)">${p.serial}</code></td>
                <td>${pStatusBadge}</td>
                <td><span class="${pIsOnline ? 'ping-online' : 'ping-offline'} me-1">â—</span><small>${pLastPingText}</small></td>
            </tr>`;
        });

        tbody.innerHTML = html;
        if (infoEl) infoEl.textContent = `Showing 1 to ${devices.length} of ${devices.length} entries`;
    }

    /** Format epoch timestamp to human-readable time ago */
    _formatTimeAgo(epoch, isOnline) {
        if (!epoch) return 'â€”';
        const now = Math.floor(Date.now() / 1000);
        const diff = now - epoch;

        if (isOnline) {
            if (diff < 60) return 'Just now';
            return `${Math.floor(diff / 60)}m ago`;
        } else {
            // Detailed offline duration formatting
            if (diff < 3600) {
                return `Off ${Math.floor(diff / 60)}m`;
            } else if (diff < 86400) {
                const h = Math.floor(diff / 3600);
                const m = Math.floor((diff % 3600) / 60);
                return `Off ${h}h ${m}m`;
            } else {
                const d = Math.floor(diff / 86400);
                const h = Math.floor((diff % 86400) / 3600);
                const m = Math.floor((diff % 3600) / 60);
                return `Off ${d}d ${h}h ${m}m`;
            }
        }
    }

    /** Filter grid rows by search query */
    _filterPiGrid(query) {
        const q = query.toLowerCase().trim();
        document.querySelectorAll('.pi-grid-row').forEach(row => {
            const match = !q || row.dataset.search.includes(q);
            row.style.display = match ? '' : 'none';
        });
    }


    /** Toggle select mode on Pi cards */
    togglePiSelectMode() {
        this._piSelectMode = !this._piSelectMode;
        const overlays = document.querySelectorAll('.pi-check-overlay');
        const btn = document.getElementById('pi-select-toggle');
        const bar = document.getElementById('pi-action-bar');

        if (this._piSelectMode) {
            overlays.forEach(el => el.style.display = 'block');
            if (btn) { btn.classList.replace('btn-outline-secondary', 'btn-primary'); btn.innerHTML = '<i class="bi bi-x-lg me-1"></i>Hủy chọn'; }
        } else {
            overlays.forEach(el => { el.style.display = 'none'; el.querySelector('input').checked = false; });
            if (btn) { btn.classList.replace('btn-primary', 'btn-outline-secondary'); btn.innerHTML = '<i class="bi bi-check2-square me-1"></i>Chọn'; }
            if (bar) bar.style.bottom = '-80px';
        }
    }

    /** Update action bar when checkboxes change */
    _onPiCheckChange() {
        const checked = document.querySelectorAll('.pi-checkbox:checked');
        const bar = document.getElementById('pi-action-bar');
        const countEl = document.getElementById('pi-sel-count');

        if (checked.length > 0) {
            bar.style.bottom = '24px';
            countEl.textContent = `${checked.length} đã chọn`;

            // Determine which actions to show based on selected statuses
            const statuses = new Set();
            checked.forEach(cb => {
                const row = cb.closest('.pi-grid-row') || cb.closest('tr');
                if (row) statuses.add(row.dataset.piStatus);
            });

            // Check lock states of selected items
            const lockStates = new Set();
            checked.forEach(cb => {
                const row = cb.closest('.pi-grid-row') || cb.closest('tr');
                if (row) lockStates.add(row.dataset.piLocked);
            });

            const show = (id, visible) => { const el = document.getElementById(id); if (el) el.style.display = visible ? '' : 'none'; };
            show('pi-act-activate', statuses.has('pending') || statuses.has('activating'));
            show('pi-act-unassign', statuses.has('assigned'));
            show('pi-act-lock', lockStates.has('0'));   // Show lock if any unlocked
            show('pi-act-unlock', lockStates.has('1')); // Show unlock if any locked
            show('pi-act-reset', statuses.has('activated') || statuses.has('assigned'));
            show('pi-act-delete', true);

            // Show "Gán vào Pi Trung tâm" if any selected is pi_point + activated
            const types = new Set();
            checked.forEach(cb => {
                const row = cb.closest('.pi-grid-row') || cb.closest('tr');
                if (row) types.add(row.dataset.piType);
            });
            show('pi-act-assign-center', types.has('pi_point') && statuses.has('activated'));
        } else {
            bar.style.bottom = '-80px';
        }
    }

    /** Execute batch action on selected Pi devices */
    async _piActionBatch(action) {
        const checked = document.querySelectorAll('.pi-checkbox:checked');
        const ids = Array.from(checked).map(cb => parseInt(cb.dataset.piId));
        if (ids.length === 0) return;

        const actionMap = {
            'activate': { method: 'POST', path: id => `/api/field/pi-devices/${id}/activate`, label: 'Kích hoạt' },
            'unassign': { method: 'PUT', path: id => `/api/field/pi-devices/${id}/unassign`, label: 'Bỏ gán' },
            'lock': { method: 'PUT', path: id => `/api/field/pi-devices/${id}/lock`, body: { is_locked: true }, label: 'Khóa' },
            'unlock': { method: 'PUT', path: id => `/api/field/pi-devices/${id}/lock`, body: { is_locked: false }, label: 'Mở khóa' },
            'reset': { method: 'POST', path: id => `/api/field/pi-devices/${id}/reset`, label: 'Reset' },
            'delete': { method: 'DELETE', path: id => `/api/field/pi-devices/${id}`, label: 'Xóa' },
        };
        const cfg = actionMap[action];
        if (!cfg) return;

        window.toast?.info(`⏳ Đang ${cfg.label} ${ids.length} thiết bị...`);

        let ok = 0, fail = 0;
        for (const id of ids) {
            try {
                const r = await fetch(cfg.path(id), {
                    method: cfg.method,
                    headers: { 'Authorization': `Bearer ${this.token}`, 'Content-Type': 'application/json' }
                });
                if (r.ok) ok++; else fail++;
            } catch { fail++; }
        }

        if (ok > 0) window.toast?.success(`✅ ${cfg.label}: ${ok} thành công`);
        if (fail > 0) window.toast?.error(`❌ ${fail} thất bại`);

        this._piSelectMode = false;
        const toggleBtn = document.getElementById('pi-select-toggle');
        if (toggleBtn) { toggleBtn.classList.replace('btn-primary', 'btn-outline-secondary'); toggleBtn.innerHTML = '<i class="bi bi-check2-square me-1"></i>Chọn'; }
        const bar = document.getElementById('pi-action-bar');
        if (bar) bar.style.bottom = '-80px';

        setTimeout(() => this.loadPiDevices(), 500);
    }


    /** Activate a Pi device - generate key and send via MQTT */
    async activatePiDevice(piId) {
        try {
            window.toast?.info('⏳ Đang gửi yêu cầu kích hoạt...');
            const res = await fetch(`/api/field/pi-devices/${piId}/activate`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi kích hoạt');
            }
            window.toast?.success('✅ Đã gửi key kích hoạt đến Pi qua MQTT. Vui lòng chờ Pi xác nhận...');
            setTimeout(() => this.loadPiDevices(), 2000);
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

    /** Assign Pi from the Pi Devices tab (using dropdown select) */
    async assignPiFromTab(piId) {
        const selectEl = document.getElementById(`assign-station-${piId}`);
        const stationId = selectEl?.value;
        if (!stationId) {
            window.toast?.warning('Vui lòng chọn trạm trước');
            return;
        }
        try {
            const res = await fetch(`/api/field/pi-devices/${piId}/assign`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ station_id: parseInt(stationId) })
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi gán trạm');
            }
            const data = await res.json();
            window.toast?.success(`✅ Đã gán Pi vào trạm "${data.station_name}"`);
            this.loadPiDevices();
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

    /** Remove Pi assignment (set back to activated) */
    async unassignPiDevice(piId, event) {
        if (event) event.stopPropagation();
        if (!confirm('Bạn có chắc chắn muốn BỎ GÁN thiết bị này không?')) return;

        try {
            const res = await fetch(`/api/field/pi-devices/${piId}/unassign`, {
                method: 'PUT',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) throw new Error('Lỗi bỏ gán');
            window.toast?.success('✅ Đã bỏ gán Pi khỏi trạm');
            this.loadPiDevices();
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

    /** Delete a Pi device record */
    async deletePiDevice(piId) {
        try {
            const res = await fetch(`/api/field/pi-devices/${piId}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) throw new Error('Lỗi xóa');
            window.toast?.success('✅ Đã xóa Pi');
            setTimeout(() => this.loadPiDevices(), 500);
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

    /** Factory-reset a Pi device: clear license, station, set back to pending */
    async resetPiDevice(piId) {
        try {
            window.toast?.info('🔄 Đang reset thiết bị Pi...');
            const res = await fetch(`/api/field/pi-devices/${piId}/reset`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi reset');
            }
            window.toast?.success('✅ Pi đã được reset về trạng thái ban đầu (pending)');
            setTimeout(() => this.loadPiDevices(), 500);
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

}
window.applyAdminFeature(AdminPiDevicesFeature);
})();
