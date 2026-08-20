(() => {
class AdminPiDevicesFeature extends window.AdminManager {
    async loadPiDevices(isAuto = false) {
        if (isAuto && this._piSelectMode) return;
        if (!isAuto) this._piSelectMode = false;
        const body = document.getElementById('pi-grid-body');
        const syncButton = document.getElementById('pi-sync-button');
        if (!isAuto && body) body.innerHTML = '<div class="ops-loading"><span class="spinner-border spinner-border-sm" aria-hidden="true"></span><span>Đang đồng bộ thiết bị…</span></div>';
        if (!isAuto && syncButton) {
            syncButton.disabled = true;
            syncButton.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Đang đồng bộ';
        }
        try {
            const res = await fetch('/api/field/pi-devices', { headers: { 'Authorization': `Bearer ${this.token}` } });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            let devices = await res.json();
            const isOperator = this.currentUserRole === 'operator';
            if (isOperator && this.currentUserAssignedProjects?.length > 0) {
                const allowed = this.currentUserAssignedProjects;
                devices = devices.filter(device => device.status === 'assigned' && device.project_id && allowed.includes(device.project_id));
            }
            this._piDevicesData = devices;
            this._updatePiSummary(devices);
            this._renderPiGrid(devices);
            this._ensurePiActionBar?.();
            if (!isAuto) this._clearPiSelection?.();
            const selectToggle = document.getElementById('pi-select-toggle');
            if (selectToggle) selectToggle.hidden = isOperator;
        } catch (error) {
            console.error('Error loading Pi devices:', error);
            if (body) body.innerHTML = `<div class="ops-empty is-error"><i class="bi bi-exclamation-circle" aria-hidden="true"></i><strong>Không tải được thiết bị Pi</strong><p>${this._escapePi(error.message)}</p><button class="btn btn-outline-primary" onclick="window.adminManager.loadPiDevices()">Thử lại</button></div>`;
            window.toast?.error('Không thể tải danh sách Pi');
        } finally {
            if (!isAuto && syncButton) {
                syncButton.disabled = false;
                syncButton.innerHTML = '<i class="bi bi-arrow-clockwise me-1" aria-hidden="true"></i>Đồng bộ';
            }
        }
    }

    _updatePiSummary(devices) {
        const counts = {
            pending: devices.filter(device => ['pending', 'activating'].includes(device.status)).length,
            activated: devices.filter(device => device.status === 'activated').length,
            assigned: devices.filter(device => device.status === 'assigned').length,
            online: devices.filter(device => this._isPiOnline(device)).length,
        };
        Object.entries(counts).forEach(([key, value]) => {
            const element = document.getElementById(`pi-${key}-count`);
            if (element) element.textContent = value.toLocaleString('vi-VN');
        });
        const description = document.getElementById('pi-pending-desc');
        if (description) description.textContent = counts.pending ? `${counts.pending} thiết bị cần xử lý` : 'Không có thiết bị chờ';
    }

    _renderPiGrid(devices) {
        const body = document.getElementById('pi-grid-body');
        const info = document.getElementById('pi-grid-info');
        if (!body) return;
        const centers = devices.filter(device => device.pi_center_id == null && device.device_type !== 'pi_point');
        const childPoints = devices.filter(device => device.pi_center_id != null);
        const loosePoints = devices.filter(device => device.pi_center_id == null && device.device_type === 'pi_point');
        const rows = [
            ...centers.map(center => this._renderPiDeviceRow(center, childPoints.filter(point => Number(point.pi_center_id) === Number(center.id)))),
            ...loosePoints.map(point => this._renderPiDeviceRow(point, [])),
        ];
        body.innerHTML = rows.length ? rows.join('') : '<div class="ops-empty"><i class="bi bi-cpu" aria-hidden="true"></i><strong>Chưa có thiết bị</strong><p>Thiết bị mới sẽ xuất hiện sau lần handshake đầu tiên.</p></div>';
        if (info) info.textContent = `${devices.length.toLocaleString('vi-VN')} thiết bị`;
        this._filterPiGrid();
    }

    _renderPiDeviceRow(device, children) {
        const online = this._isPiOnline(device);
        const status = this._piStatus(device);
        const typeLabel = device.device_type === 'pi_point' ? 'Pi hiện trường' : String(device.device_type || '').toLowerCase() === 'win' ? 'PC trung tâm' : 'Pi trung tâm';
        const displayName = device.status === 'assigned' ? device.station_name || device.name : device.name;
        const scope = [typeLabel, device.project_name, device.station_name && device.station_name !== displayName ? device.station_name : ''].filter(Boolean).join(' · ');
        const search = [device.name, device.serial, device.station_name, device.project_name].filter(Boolean).join(' ').toLowerCase();
        const addPoint = device.status === 'assigned' && device.device_type !== 'pi_point' && children.length === 0
            ? `<button class="btn btn-sm btn-outline-primary mt-2" onclick="window.adminManager.openAssignPiPointModal(${Number(device.id)})"><i class="bi bi-plus-lg me-1" aria-hidden="true"></i>Gắn Pi hiện trường</button>` : '';
        const childList = children.length ? `<div class="pi-child-list">${children.map(child => this._renderPiChild(child)).join('')}</div>` : '';
        return `<article class="pi-device-row pi-grid-row" data-pi-id="${Number(device.id)}" data-pi-status="${this._escapePi(device.status || '')}" data-pi-locked="${device.is_locked ? '1' : '0'}" data-pi-type="${this._escapePi(device.device_type || 'pi')}" data-online="${online ? 'online' : 'offline'}" data-search="${this._escapePi(search)}">
            <div class="pi-device-identity"><label class="pi-device-select" aria-label="Chọn ${this._escapePi(device.name || device.serial)}"><input type="checkbox" class="pi-checkbox" data-pi-id="${Number(device.id)}" onchange="window.adminManager._onPiCheckChange()"></label><span class="pi-device-icon" aria-hidden="true"><i class="bi bi-${device.device_type === 'pi_point' ? 'geo-alt' : 'cpu'}"></i></span><div class="pi-device-name"><strong>${this._escapePi(displayName || `Thiết bị #${device.id}`)}</strong><small>${this._escapePi(scope || 'Chưa gán phạm vi')}</small>${addPoint}</div></div>
            <code class="pi-device-serial" title="${this._escapePi(device.serial || '')}">${this._escapePi(device.serial || 'Chưa có serial')}</code>
            <span class="pi-device-status ${status.className}"><i class="bi bi-${status.icon}" aria-hidden="true"></i>${status.label}</span>
            <span class="pi-connection is-${online ? 'online' : 'offline'}"><i class="bi bi-circle-fill" aria-hidden="true"></i>${this._formatTimeAgo(device.last_seen, online)}</span>${childList}
        </article>`;
    }

    _renderPiChild(device) {
        const online = this._isPiOnline(device);
        return `<div class="pi-child-device"><i class="bi bi-diagram-2" aria-hidden="true"></i><strong>${this._escapePi(device.name || 'Pi hiện trường')}</strong><small>${this._escapePi(device.serial || '')}</small><span class="pi-connection is-${online ? 'online' : 'offline'}"><i class="bi bi-circle-fill" aria-hidden="true"></i>${this._formatTimeAgo(device.last_seen, online)}</span><button class="btn btn-sm btn-outline-danger" onclick="window.adminManager.unassignPiDevice(${Number(device.id)}, event)" aria-label="Bỏ gán ${this._escapePi(device.name || 'Pi hiện trường')}"><i class="bi bi-link-45deg" aria-hidden="true"></i></button></div>`;
    }

    _piStatus(device) {
        if (device.is_locked) return { label: 'Đã khóa', className: 'is-locked', icon: 'lock' };
        const values = { pending: ['Chờ kích hoạt', 'is-pending', 'hourglass-split'], activating: ['Đang kích hoạt', 'is-pending', 'key'], activated: ['Chưa gán trạm', 'is-activated', 'check2-circle'], assigned: ['Đã gán trạm', 'is-assigned', 'broadcast-pin'] };
        const [label, className, icon] = values[device.status] || ['Chưa xác định', 'is-pending', 'question-circle'];
        return { label, className, icon };
    }

    _isPiOnline(device) {
        const age = Math.floor(Date.now() / 1000) - Number(device.last_seen || 0);
        return Boolean(device.last_seen && age >= 0 && age < 120);
    }

    _formatTimeAgo(epoch, online = false) {
        if (!epoch) return 'Chưa nhận heartbeat';
        const seconds = Math.max(0, Math.floor(Date.now() / 1000) - Number(epoch));
        if (online) return seconds < 60 ? 'Vừa nhận' : `${Math.floor(seconds / 60)} phút trước`;
        if (seconds < 3600) return `Mất kết nối ${Math.max(1, Math.floor(seconds / 60))} phút`;
        if (seconds < 86400) return `Mất kết nối ${Math.floor(seconds / 3600)} giờ`;
        return `Mất kết nối ${Math.floor(seconds / 86400)} ngày`;
    }

    _filterPiGrid() {
        const query = document.getElementById('pi-search-input')?.value.toLowerCase().trim() || '';
        const filter = document.getElementById('pi-status-filter')?.value || 'all';
        let visible = 0;
        document.querySelectorAll('.pi-grid-row').forEach(row => {
            const statusMatch = filter === 'all' || filter === row.dataset.online || filter === row.dataset.piStatus || (filter === 'locked' && row.dataset.piLocked === '1');
            const matches = (!query || row.dataset.search.includes(query)) && statusMatch;
            row.hidden = !matches;
            if (matches) visible += 1;
        });
        const info = document.getElementById('pi-grid-info');
        if (info) info.textContent = query || filter !== 'all'
            ? `${visible} thiết bị phù hợp`
            : `${(this._piDevicesData || []).length.toLocaleString('vi-VN')} thiết bị`;
    }

    _escapePi(value) {
        return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
    }
}
window.applyAdminFeature(AdminPiDevicesFeature);
})();
