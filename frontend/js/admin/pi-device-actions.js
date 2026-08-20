(() => {
class AdminPiDeviceActionsFeature extends window.AdminManager {
    _ensurePiActionBar() {
        if (this.currentUserRole === 'operator' || document.getElementById('pi-action-bar')) return;
        const bar = document.createElement('div');
        bar.id = 'pi-action-bar';
        bar.className = 'pi-action-bar';
        bar.innerHTML = `<span id="pi-sel-count">0 đã chọn</span>
            <button class="btn btn-sm btn-primary" id="pi-act-activate" onclick="window.adminManager._piActionBatch('activate')" hidden><i class="bi bi-key me-1"></i>Kích hoạt</button>
            <button class="btn btn-sm btn-warning" id="pi-act-unassign" onclick="window.adminManager._piActionBatch('unassign')" hidden><i class="bi bi-x-circle me-1"></i>Bỏ gán</button>
            <button class="btn btn-sm btn-secondary" id="pi-act-lock" onclick="window.adminManager._piActionBatch('lock')" hidden><i class="bi bi-lock me-1"></i>Khóa</button>
            <button class="btn btn-sm btn-success" id="pi-act-unlock" onclick="window.adminManager._piActionBatch('unlock')" hidden><i class="bi bi-unlock me-1"></i>Mở khóa</button>
            <button class="btn btn-sm btn-info" id="pi-act-reset" onclick="window.adminManager._piActionBatch('reset')" hidden><i class="bi bi-arrow-counterclockwise me-1"></i>Reset</button>
            <button class="btn btn-sm btn-danger" id="pi-act-delete" onclick="window.adminManager._piActionBatch('delete')" hidden><i class="bi bi-trash me-1"></i>Xóa</button>
            <button class="btn btn-sm btn-outline-warning" id="pi-act-assign-center" onclick="window.adminManager.assignSelectedPointToCenter()" hidden><i class="bi bi-link-45deg me-1"></i>Gán Pi trung tâm</button>
            <button class="btn btn-sm btn-outline-light" onclick="window.adminManager.togglePiSelectMode()" aria-label="Đóng chế độ chọn"><i class="bi bi-x-lg"></i></button>`;
        document.body.appendChild(bar);
    }

    togglePiSelectMode() {
        this._piSelectMode = !this._piSelectMode;
        document.querySelectorAll('.pi-device-select').forEach(element => {
            element.classList.toggle('is-visible', this._piSelectMode);
            const input = element.querySelector('input');
            if (!this._piSelectMode && input) input.checked = false;
        });
        const button = document.getElementById('pi-select-toggle');
        if (button) {
            button.classList.toggle('btn-primary', !this._piSelectMode);
            button.classList.toggle('btn-outline-secondary', this._piSelectMode);
            button.innerHTML = this._piSelectMode ? '<i class="bi bi-x-lg me-1"></i>Hủy chọn' : '<i class="bi bi-check2-square me-1"></i>Chọn thiết bị';
        }
        if (!this._piSelectMode) this._clearPiSelection();
    }

    _clearPiSelection() {
        document.querySelectorAll('.pi-device-select').forEach(element => {
            element.classList.remove('is-visible');
            const input = element.querySelector('input');
            if (input) input.checked = false;
        });
        document.querySelectorAll('.pi-grid-row').forEach(row => row.classList.remove('is-selected'));
        document.getElementById('pi-action-bar')?.classList.remove('is-visible');
        const button = document.getElementById('pi-select-toggle');
        if (button) {
            button.classList.add('btn-primary');
            button.classList.remove('btn-outline-secondary');
            button.innerHTML = '<i class="bi bi-check2-square me-1"></i>Chọn thiết bị';
        }
    }

    _onPiCheckChange() {
        const checked = [...document.querySelectorAll('.pi-checkbox:checked')];
        const bar = document.getElementById('pi-action-bar');
        if (!bar) return;
        document.querySelectorAll('.pi-grid-row').forEach(row => row.classList.toggle('is-selected', Boolean(row.querySelector('.pi-checkbox:checked'))));
        bar.classList.toggle('is-visible', checked.length > 0);
        const count = document.getElementById('pi-sel-count');
        if (count) count.textContent = `${checked.length} đã chọn`;
        const rows = checked.map(input => input.closest('.pi-grid-row')).filter(Boolean);
        const statuses = new Set(rows.map(row => row.dataset.piStatus));
        const locks = new Set(rows.map(row => row.dataset.piLocked));
        const types = new Set(rows.map(row => row.dataset.piType));
        const show = (id, visible) => { const element = document.getElementById(id); if (element) element.hidden = !visible; };
        show('pi-act-activate', statuses.has('pending') || statuses.has('activating'));
        show('pi-act-unassign', statuses.has('assigned'));
        show('pi-act-lock', locks.has('0'));
        show('pi-act-unlock', locks.has('1'));
        show('pi-act-reset', statuses.has('activated') || statuses.has('assigned'));
        show('pi-act-delete', checked.length > 0);
        show('pi-act-assign-center', types.has('pi_point') && statuses.has('activated'));
    }

    async _piActionBatch(action) {
        const ids = [...document.querySelectorAll('.pi-checkbox:checked')].map(input => Number(input.dataset.piId));
        if (!ids.length) return;
        const actions = {
            activate: { method: 'POST', path: id => `/api/field/pi-devices/${id}/activate`, label: 'kích hoạt' },
            unassign: { method: 'PUT', path: id => `/api/field/pi-devices/${id}/unassign`, label: 'bỏ gán', confirm: true },
            lock: { method: 'PUT', path: id => `/api/field/pi-devices/${id}/lock`, body: { is_locked: true }, label: 'khóa' },
            unlock: { method: 'PUT', path: id => `/api/field/pi-devices/${id}/lock`, body: { is_locked: false }, label: 'mở khóa' },
            reset: { method: 'POST', path: id => `/api/field/pi-devices/${id}/reset`, label: 'reset', confirm: true },
            delete: { method: 'DELETE', path: id => `/api/field/pi-devices/${id}`, label: 'xóa', confirm: true },
        };
        const config = actions[action];
        if (!config || (config.confirm && !confirm(`Xác nhận ${config.label} ${ids.length} thiết bị?`))) return;
        const buttons = [...document.querySelectorAll('#pi-action-bar button')];
        buttons.forEach(button => { button.disabled = true; });
        window.toast?.info(`Đang ${config.label} ${ids.length} thiết bị…`);
        const results = await Promise.all(ids.map(async id => {
            try {
                const response = await fetch(config.path(id), { method: config.method, headers: { 'Authorization': `Bearer ${this.token}`, 'Content-Type': 'application/json' }, body: config.body ? JSON.stringify(config.body) : undefined });
                return response.ok;
            } catch { return false; }
        }));
        const succeeded = results.filter(Boolean).length;
        const failed = results.length - succeeded;
        if (succeeded) window.toast?.success(`${succeeded} thiết bị đã ${config.label} thành công`);
        if (failed) window.toast?.error(`${failed} thiết bị xử lý thất bại`);
        buttons.forEach(button => { button.disabled = false; });
        this._piSelectMode = false;
        this._clearPiSelection();
        await this.loadPiDevices();
    }

    async _requestPiAction(path, options, successMessage) {
        const response = await fetch(path, { ...options, headers: { 'Authorization': `Bearer ${this.token}`, ...(options.headers || {}) } });
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `HTTP ${response.status}`);
        window.toast?.success(successMessage);
        await this.loadPiDevices();
        return response;
    }

    async activatePiDevice(piId) {
        try { await this._requestPiAction(`/api/field/pi-devices/${piId}/activate`, { method: 'POST' }, 'Đã gửi yêu cầu kích hoạt'); }
        catch (error) { window.toast?.error(error.message); }
    }

    async assignPiFromTab(piId) {
        const stationId = Number(document.getElementById(`assign-station-${piId}`)?.value);
        if (!stationId) return window.toast?.warning('Vui lòng chọn trạm trước');
        try { await this._requestPiAction(`/api/field/pi-devices/${piId}/assign`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ station_id: stationId }) }, 'Đã gán Pi vào trạm'); }
        catch (error) { window.toast?.error(error.message); }
    }

    async unassignPiDevice(piId, event) {
        event?.stopPropagation();
        if (!confirm('Bỏ gán thiết bị này khỏi Pi trung tâm?')) return;
        try { await this._requestPiAction(`/api/field/pi-devices/${piId}/unassign`, { method: 'PUT' }, 'Đã bỏ gán thiết bị'); }
        catch (error) { window.toast?.error(error.message); }
    }

    async deletePiDevice(piId) {
        if (!confirm('Xóa thiết bị Pi này? Thao tác không thể hoàn tác.')) return;
        try { await this._requestPiAction(`/api/field/pi-devices/${piId}`, { method: 'DELETE' }, 'Đã xóa thiết bị Pi'); }
        catch (error) { window.toast?.error(error.message); }
    }

    async resetPiDevice(piId) {
        if (!confirm('Reset thiết bị về trạng thái chờ kích hoạt?')) return;
        try { await this._requestPiAction(`/api/field/pi-devices/${piId}/reset`, { method: 'POST' }, 'Đã reset thiết bị Pi'); }
        catch (error) { window.toast?.error(error.message); }
    }
}
window.applyAdminFeature(AdminPiDeviceActionsFeature);
})();
