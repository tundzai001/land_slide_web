(() => {
class AdminOperationsFeature extends window.AdminManager {
    operationFeedback(message, error = false) {
        const target = document.getElementById('operations-feedback');
        if (!target) return;
        target.hidden = false;
        target.textContent = message;
        target.classList.toggle('is-error', error);
        target.setAttribute('role', error ? 'alert' : 'status');
        if (error) target.focus();
    }

    async operationRequest(path, options = {}) {
        const response = await fetch(`/api/admin/operations${path}`, {
            ...options, headers: { Authorization: `Bearer ${this.token}`, ...options.headers }, cache: 'no-store',
        });
        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            const detail = Array.isArray(body.detail) ? body.detail.map(item => item.msg).join('; ') : body.detail;
            throw new Error(detail || `HTTP ${response.status}`);
        }
        return response;
    }

    async operationJSON(path, method, value) {
        return (await this.operationRequest(path, {
            method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
        })).json();
    }

    async loadOperations() {
        if (!this.canAccessTab('tab-operations')) return;
        this.operationFeedback('Đang tải thông tin vận hành…');
        try {
            const [backup, ntp, devices] = await Promise.all([
                this.operationRequest('/backups').then(r => r.json()),
                this.operationRequest('/ntp').then(r => r.json()),
                this.operationRequest('/devices').then(r => r.json()),
            ]);
            if (this._disposed) return;
            this.renderOperationBackups(backup.backups);
            document.getElementById('operations-frequency').value = backup.schedule.frequency;
            document.getElementById('operations-retention').value = backup.schedule.retention_count || 30;
            const next = backup.schedule.next_at ? new Date(backup.schedule.next_at * 1000) : null;
            document.getElementById('operations-next').value = next ? new Date(next.getTime() - next.getTimezoneOffset() * 60000).toISOString().slice(0,16) : '';
            document.getElementById('operations-ntp-server').value = ntp.config.server;
            this.renderOperationNTP(ntp.last_check);
            this.operationDevices = devices;
            const select = document.getElementById('operations-device');
            const selected = select.value;
            select.replaceChildren(...devices.map(device => new Option(`${device.name} · ${device.device_type} · #${device.id}`, String(device.id))));
            if (!devices.length) select.add(new Option('Chưa có thiết bị MQTT', ''));
            if (devices.some(device => String(device.id) === selected)) select.value = selected;
            this.selectOperationDevice();
            await this.loadOperationLogs();
            this.operationFeedback(`Cập nhật lúc ${new Date().toLocaleTimeString('vi-VN')}.`);
            const job = sessionStorage.getItem('operations-active-job');
            if (job) this.watchOperationJob(job);
        } catch (error) { this.operationFeedback(error.message, true); }
    }

    renderOperationBackups(rows) {
        const container = document.getElementById('operations-backups');
        container.replaceChildren();
        if (!rows.length) { container.textContent = 'Chưa có bản sao lưu. Chọn “Tạo bản sao lưu” để bắt đầu.'; return; }
        for (const row of rows) {
            const item = document.createElement('div');
            item.className = 'operations-backup-row';
            const info = document.createElement('div');
            const title = document.createElement('strong');
            title.textContent = new Date(row.created_at * 1000).toLocaleString('vi-VN');
            const size = document.createElement('small');
            size.textContent = `${(row.bytes / 1024 / 1024).toFixed(2)} MB · ${row.id.slice(0,8)}`;
            info.append(title, size);
            const download = document.createElement('button');
            download.className = 'btn btn-outline-primary'; download.textContent = 'Tải xuống';
            download.onclick = () => this.operationDownload(`/backups/${row.id}/download`, `landslide_${row.id}.zip`);
            const restore = document.createElement('button');
            restore.className = 'btn btn-outline-secondary'; restore.textContent = 'Phục hồi vào CSDL riêng';
            restore.onclick = () => this.operationAction(restore, 'restore', row.id);
            item.append(info, download, restore); container.append(item);
        }
    }

    renderOperationNTP(status) {
        document.getElementById('operations-ntp-status').textContent = status
            ? `Đo lúc ${new Date(status.checked_at * 1000).toLocaleString('vi-VN')}: lệch ${Number(status.offset_ms).toFixed(2)} ms · khứ hồi ${Number(status.round_trip_ms).toFixed(2)} ms · stratum ${status.stratum}.`
            : 'Chưa có phép đo. Chọn “Lưu & kiểm tra” để đo độ lệch.';
    }

    async operationAction(button, action, id) {
        if (button.disabled) return;
        if (action === 'restore' && !window.confirm('Phục hồi bản sao vào ba CSDL riêng để kiểm tra? Thu thập MQTT tiếp tục trên CSDL hiện tại.')) return;
        button.disabled = true;
        const label = button.textContent;
        button.textContent = 'Đang xử lý…';
        try {
            if (action === 'backup' || action === 'restore') {
                const result = await this.operationJSON(action === 'backup' ? '/backups' : `/backups/${id}/restore`, 'POST',
                    action === 'restore' ? { confirmation: 'RESTORE INTO ISOLATED DATABASES' } : {});
                sessionStorage.setItem('operations-active-job', result.job_id);
                this.watchOperationJob(result.job_id);
                this.operationFeedback('Đã nhận tác vụ. Bạn có thể theo dõi trạng thái tại mục sao lưu.');
            } else if (action === 'schedule') {
                const date = document.getElementById('operations-next').value;
                await this.operationJSON('/backup-schedule', 'PUT', {
                    frequency: document.getElementById('operations-frequency').value,
                    next_at: date ? Math.floor(new Date(date).getTime() / 1000) : 0,
                    retention_count: Number(document.getElementById('operations-retention').value || 30),
                });
                this.operationFeedback('Đã lưu lịch sao lưu.');
            } else if (action === 'ntp') {
                await this.operationJSON('/ntp', 'PUT', { server: document.getElementById('operations-ntp-server').value.trim() });
                this.renderOperationNTP(await this.operationJSON('/ntp/check', 'POST', {}));
                this.operationFeedback('Đã cập nhật phép đo NTP.');
            } else if (action === 'profile') {
                const device = document.getElementById('operations-device').value;
                if (!device) throw new Error('Chọn thiết bị MQTT trước khi lưu.');
                const protocol = document.getElementById('operations-protocol').value;
                const value = protocol === 'mqtt' ? { protocol, enabled: false }
                    : { ...JSON.parse(document.getElementById('operations-profile').value), protocol,
                        enabled: document.getElementById('operations-profile-enabled').checked };
                await this.operationJSON(`/devices/${device}/acquisition`, 'PUT', value);
                const row = this.operationDevices.find(item => String(item.id) === device);
                if (row) row.acquisition = value;
                this.operationFeedback(protocol === 'mqtt' ? 'Đã lưu nguồn MQTT hiện có.' : 'Đã lưu. Tải cấu hình và triển khai tại gateway để bắt đầu đọc thiết bị.');
            }
        } catch (error) { this.operationFeedback(error.message, true); }
        finally { button.disabled = false; button.textContent = label; }
    }

    watchOperationJob(id) {
        clearInterval(this.operationJobTimer);
        let busy = false;
        const poll = async () => {
            if (busy || this._disposed) return;
            busy = true;
            try {
                const result = await (await this.operationRequest(`/jobs/${id}`)).json();
                const labels = { pending: 'Đang chờ', running: 'Đang thực hiện', completed: 'Hoàn thành', error: 'Thất bại' };
                document.getElementById('operations-job').textContent = `${labels[result.status] || result.status}${result.error ? ': ' + result.error : ''}${result.recovered_databases ? ' · CSDL phục hồi: ' + Object.values(result.recovered_databases).join(', ') : ''}`;
                if (['completed', 'error'].includes(result.status)) {
                    clearInterval(this.operationJobTimer);
                    sessionStorage.removeItem('operations-active-job');
                    const backup = await (await this.operationRequest('/backups')).json();
                    this.renderOperationBackups(backup.backups);
                    if (result.status === 'error') this.operationFeedback(result.error, true);
                }
            } catch (error) {
                clearInterval(this.operationJobTimer);
                this.operationFeedback(error.message, true);
            } finally { busy = false; }
        };
        this.operationJobTimer = setInterval(poll, 2500);
        this._refreshIntervals.push(this.operationJobTimer);
        void poll();
    }

    async operationDownload(path, filename) {
        try {
            const blob = await (await this.operationRequest(path)).blob();
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob); link.download = filename; link.click();
            setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        } catch (error) { this.operationFeedback(error.message, true); }
    }

    async uploadOperationBackup(input) {
        const file = input.files[0];
        if (!file) return;
        input.disabled = true;
        this.operationFeedback('Đang tải và kiểm tra bản sao lưu…');
        try {
            const form = new FormData(); form.append('file', file);
            await this.operationRequest('/backups/upload', { method: 'POST', body: form });
            const backup = await (await this.operationRequest('/backups')).json();
            this.renderOperationBackups(backup.backups);
            this.operationFeedback('Đã xác minh và lưu bản sao lưu.');
        } catch (error) { this.operationFeedback(error.message, true); }
        finally { input.disabled = false; input.value = ''; }
    }

    async loadOperationLogs() {
        const offset = this.operationLogOffset || 0;
        const query = new URLSearchParams({ kind: document.getElementById('operations-log-kind').value,
            offset, limit: 25, username: document.getElementById('operations-log-user').value.trim() });
        for (const field of ['start','end']) {
            const value = document.getElementById(`operations-log-${field}`).value;
            if (value) query.set(field, Math.floor(new Date(value).getTime() / 1000));
        }
        try {
            const result = await (await this.operationRequest(`/logs?${query}`)).json();
            const body = document.getElementById('operations-logs'); body.replaceChildren();
            for (const row of result.rows) {
                const tr = document.createElement('tr');
                const values = [new Date(row.timestamp * 1000).toLocaleString('vi-VN'), `${row.username || 'Hệ thống'} / ${row.role || '—'}`, row.action, row.status ?? 'Đã ghi'];
                const labels = ['Thời gian', 'Tài khoản / Vai trò', 'Hành động', 'Kết quả'];
                for (const [index, value] of values.entries()) {
                    const cell = document.createElement('td'); cell.dataset.label = labels[index]; cell.textContent = value; tr.append(cell);
                }
                const cell = document.createElement('td'), details = document.createElement('details'), summary = document.createElement('summary'), pre = document.createElement('pre');
                cell.className = 'operations-log-detail';
                summary.textContent = 'Xem chi tiết'; pre.textContent = JSON.stringify({ ip: row.ip, object: row.object, ...row.details }, null, 2);
                details.append(summary, pre); cell.append(details); tr.append(cell); body.append(tr);
            }
            if (!result.rows.length) { const tr = body.insertRow(); const cell = tr.insertCell(); cell.colSpan = 5; cell.textContent = 'Không có nhật ký phù hợp.'; }
            document.getElementById('operations-log-count').textContent = `${result.total ? offset + 1 : 0}–${offset + result.rows.length} / ${result.total}`;
            document.getElementById('operations-log-prev').disabled = offset === 0;
            document.getElementById('operations-log-next').disabled = offset + 25 >= result.total;
        } catch (error) { this.operationFeedback(error.message, true); }
    }

    operationLogPage(direction) {
        this.operationLogOffset = Math.max(0, (this.operationLogOffset || 0) + direction * 25);
        void this.loadOperationLogs();
    }

    selectOperationDevice() {
        const id = document.getElementById('operations-device').value;
        const device = this.operationDevices?.find(item => String(item.id) === id);
        document.getElementById('operations-save-profile').disabled = !device;
        const profile = device?.acquisition || { protocol: 'mqtt', enabled: false };
        document.getElementById('operations-protocol').value = profile.protocol;
        document.getElementById('operations-profile').value = JSON.stringify(profile, null, 2);
        document.getElementById('operations-profile-enabled').checked = !!profile.enabled;
        document.getElementById('operations-profile-fields').hidden = profile.protocol === 'mqtt';
    }

    changeOperationProtocol() {
        const protocol = document.getElementById('operations-protocol').value;
        document.getElementById('operations-profile-fields').hidden = protocol === 'mqtt';
        const id = document.getElementById('operations-device').value;
        const device = this.operationDevices?.find(item => String(item.id) === id);
        const field = { water: 'water_level', rain: 'rainfall_mm', imu: 'roll' }[device?.device_type] || 'value';
        const profile = device?.acquisition?.protocol === protocol ? device.acquisition : {
            protocol, enabled: false, poll_seconds: 5,
            ...(protocol === 'modbus_tcp' ? { host: '', port: 502, unit_id: 1 } : {}),
            ...(protocol === 'modbus_rtu' ? { serial_port: '/dev/ttyUSB0', baudrate: 9600, parity: 'N', stopbits: 1, unit_id: 1 } : {}),
            ...(protocol === 'opcua' ? { endpoint: 'opc.tcp://gateway.local:4840', security: '' } : {}),
            points: [{ field, address: 0, node_id: protocol === 'opcua' ? 'ns=2;s=Measurement' : '', data_type: 'float32', scale: 1, offset: 0 }],
        };
        document.getElementById('operations-profile').value = JSON.stringify(profile, null, 2);
        document.getElementById('operations-profile-enabled').checked = !!profile.enabled;
    }

    downloadGatewayProfile() {
        const id = document.getElementById('operations-device').value;
        if (!id) { this.operationFeedback('Chọn thiết bị để tải cấu hình gateway.', true); return; }
        return this.operationDownload(`/gateway-config?device_id=${encodeURIComponent(id)}`, `gateway-device-${id}.json`);
    }

    async showIntegrationGuide() {
        try { document.getElementById('operations-guide-content').textContent = await (await this.operationRequest('/integration-guide')).text(); }
        catch (error) { this.operationFeedback(error.message, true); }
    }
}
window.applyAdminFeature(AdminOperationsFeature);
})();
