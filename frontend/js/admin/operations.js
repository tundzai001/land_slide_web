(() => {
class AdminOperationsFeature extends window.AdminManager {
    selectOperationView(view) {
        this.closeOperationInspector();
        this.operationView = view;
        const logs = ['audit_log', 'operation_log'].includes(view);
        document.querySelectorAll('[data-ops-tab]').forEach(button => {
            button.classList.toggle('is-active', button.dataset.opsTab === view);
            button.setAttribute('aria-pressed', String(button.dataset.opsTab === view));
        });
        document.querySelectorAll('[data-ops-view]').forEach(panel => {
            panel.hidden = panel.dataset.opsView !== (logs ? 'logs' : view);
        });
        if (logs) {
            document.getElementById('operations-log-kind').value = view;
            document.getElementById('audit-heading').textContent = view === 'audit_log' ? 'Audit log' : 'Nhật ký vận hành';
            document.getElementById('operations-log-description').textContent = view === 'audit_log'
                ? 'Ghi vết thao tác người dùng: tài khoản, hành động, đối tượng và dữ liệu trước/sau thay đổi.'
                : 'Sự kiện hệ thống: khởi động dịch vụ, sao lưu, phục hồi, kiểm tra NTP và lỗi tác vụ.';
            this.renderOperationLogFilters();
            this.operationLogOffset = 0;
            void this.loadOperationLogs();
        }
    }

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

    operationEventLabel(action) {
        return {
            'service.starting': 'Khởi động dịch vụ', 'service.stopped': 'Dừng dịch vụ',
            'backup.completed': 'Sao lưu hoàn tất', 'backup.failed': 'Sao lưu thất bại',
            'restore.completed': 'Phục hồi hoàn tất', 'restore.failed': 'Phục hồi thất bại',
            'backup.schedule': 'Thay đổi lịch sao lưu', 'ntp.checked': 'Kiểm tra NTP', 'ntp.failed': 'Kiểm tra NTP thất bại',
            'backup.retention_pruned': 'Dọn bản sao lưu cũ', 'operations.retention_pruned': 'Dọn nhật ký cũ',
        }[action] || action;
    }

    async loadOperations() {
        if (!this.canAccessTab('tab-operations')) return;
        this.operationFeedback('Đang tải thông tin vận hành…');
        try {
            const [backup, ntp, logOptions] = await Promise.all([
                this.operationRequest('/backups').then(r => r.json()),
                this.operationRequest('/ntp').then(r => r.json()),
                this.operationRequest('/log-options').then(r => r.json()),
            ]);
            if (this._disposed) return;
            this.operationLogOptions = logOptions;
            this.renderOperationLogFilters();
            this.renderOperationBackups(backup.backups);
            document.getElementById('operations-frequency').value = backup.schedule.frequency;
            document.getElementById('operations-retention').value = backup.schedule.retention_count || 30;
            document.getElementById('operations-schedule-label').textContent = { disabled: 'Đang tắt', daily: 'Hằng ngày', weekly: 'Hằng tuần' }[backup.schedule.frequency] || 'Đang tắt';
            const next = backup.schedule.next_at ? new Date(backup.schedule.next_at * 1000) : null;
            document.getElementById('operations-next').value = next ? new Date(next.getTime() - next.getTimezoneOffset() * 60000).toISOString().slice(0,16) : '';
            document.getElementById('operations-ntp-server').value = ntp.config.server;
            document.getElementById('operations-system-clock').textContent = ntp.system_clock?.output || 'Chưa đọc được trạng thái dịch vụ thời gian của hệ điều hành.';
            document.getElementById('operations-system-clock-label').textContent = ntp.system_clock?.service || 'Dịch vụ thời gian hệ điều hành';
            this.renderOperationNTP(ntp.last_check);
            await this.loadOperationLogs();
            this.operationFeedback(`Cập nhật ${new Date().toLocaleTimeString('vi-VN')}`);
            const job = sessionStorage.getItem('operations-active-job');
            if (job) this.watchOperationJob(job);
        } catch (error) { this.operationFeedback(error.message, true); }
    }

    renderOperationBackups(rows) {
        const container = document.getElementById('operations-backups');
        container.replaceChildren();
        document.getElementById('operations-backup-count').textContent = String(rows.length);
        document.getElementById('operations-backup-latest').textContent = rows.length
            ? new Date(Math.max(...rows.map(row => row.created_at)) * 1000).toLocaleString('vi-VN') : 'Chưa có bản sao lưu';
        if (!rows.length) {
            container.innerHTML = '<div class="operations-empty"><i class="bi bi-database" aria-hidden="true"></i><strong>Chưa có bản sao lưu</strong><p>Tạo bản sao đầu tiên để bảo vệ dữ liệu tài khoản, cấu hình và quan trắc.</p></div>';
            return;
        }
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
        const target = document.getElementById('operations-ntp-status');
        target.classList.remove('text-danger');
        target.setAttribute('role', 'status');
        target.textContent = status
            ? `Đo lúc ${new Date(status.checked_at * 1000).toLocaleString('vi-VN')}: lệch ${Number(status.offset_ms).toFixed(2)} ms · khứ hồi ${Number(status.round_trip_ms).toFixed(2)} ms · stratum ${status.stratum}.`
            : 'Chưa có phép đo. Chọn “Kiểm tra độ lệch” để bắt đầu.';
    }

    async operationAction(button, action, id) {
        if (button.disabled) return;
        if (action === 'restore' && !window.confirm('Phục hồi bản sao vào ba CSDL riêng để kiểm tra? Thu thập MQTT tiếp tục trên CSDL hiện tại.')) return;
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
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
                document.getElementById('operations-schedule-label').textContent = { disabled: 'Đang tắt', daily: 'Hằng ngày', weekly: 'Hằng tuần' }[document.getElementById('operations-frequency').value];
                this.operationFeedback('Đã lưu lịch sao lưu.');
            } else if (action === 'ntp') {
                this.renderOperationNTP(await this.operationJSON('/ntp/check', 'POST', {}));
            }
        } catch (error) {
            if (action === 'ntp') {
                const target = document.getElementById('operations-ntp-status');
                target.textContent = error.message;
                target.classList.add('text-danger');
                target.setAttribute('role', 'alert');
            } else this.operationFeedback(error.message, true);
        }
        finally { button.disabled = false; button.removeAttribute('aria-busy'); button.textContent = label; }
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

    async downloadGuide(button, kind) {
        const status = button.closest('.sidebar-guides').querySelector('[role="status"]');
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
        status.textContent = 'Đang tải tài liệu…';
        try {
            const name = kind === 'user' ? 'huong-dan-su-dung-web.pdf' : 'huong-dan-van-hanh-tich-hop.pdf';
            await this.operationDownload(`/${kind === 'user' ? 'user' : 'integration'}-guide/download`, name, true);
            status.textContent = 'Đã tải tài liệu.';
        } catch (error) { status.textContent = error.message; }
        finally { button.disabled = false; button.removeAttribute('aria-busy'); }
    }

    async operationDownload(path, filename, propagateError = false) {
        try {
            const blob = await (await this.operationRequest(path)).blob();
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob); link.download = filename; link.click();
            setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        } catch (error) {
            if (propagateError) throw error;
            this.operationFeedback(error.message, true);
        }
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

    renderOperationLogFilters() {
        const kind = document.getElementById('operations-log-kind').value;
        const options = this.operationLogOptions || {};
        const journal = options.journals?.[kind] || {};
        const accounts = new Map((options.accounts || []).map(user => [user.username,
            `${user.username}${user.full_name ? ' · ' + user.full_name : ''}${user.is_active ? '' : ' · Đã khóa'}`]));
        for (const username of journal.usernames || []) if (!accounts.has(username)) accounts.set(username, `${username} · Tài khoản cũ`);
        for (const [field, entries, all] of [
            ['user', Array.from(accounts), 'Tất cả tài khoản'],
            ['action', (journal.actions || []).map(action => [action, this.operationEventLabel(action)]), 'Tất cả hành động'],
        ]) {
            const select = document.getElementById(`operations-log-${field}`), previous = select.value;
            select.replaceChildren(new Option(all, ''), ...entries.map(([value, label]) => new Option(label, value)));
            select.value = entries.some(([value]) => value === previous) ? previous : '';
        }
        const method = document.getElementById('operations-log-method');
        method.disabled = kind !== 'audit_log';
        if (method.disabled) method.value = '';
    }

    async loadOperationLogs() {
        const request = this.operationLogRequest = (this.operationLogRequest || 0) + 1;
        const offset = this.operationLogOffset || 0;
        const query = new URLSearchParams({ kind: document.getElementById('operations-log-kind').value,
            offset, limit: 25, username: document.getElementById('operations-log-user').value,
            action: document.getElementById('operations-log-action').value,
            method: document.getElementById('operations-log-method').value });
        for (const field of ['start','end']) {
            const value = document.getElementById(`operations-log-${field}`).value;
            if (value) query.set(field, Math.floor(new Date(value).getTime() / 1000));
        }
        const table = document.querySelector('.operations-table-wrap');
        table.setAttribute('aria-busy', 'true');
        try {
            const result = await (await this.operationRequest(`/logs?${query}`)).json();
            if (request !== this.operationLogRequest || this._disposed) return;
            const body = document.getElementById('operations-logs'); body.replaceChildren();
            for (const row of result.rows) {
                const tr = document.createElement('tr');
                const resultLabel = row.status != null ? `${row.status < 400 ? 'Thành công' : 'Thất bại'} · ${row.status}`
                    : row.action.includes('failed') || row.action.includes('error') ? 'Thất bại' : 'Đã ghi nhận';
                const actor = row.username || (query.get('kind') === 'audit_log' ? 'Chưa xác định' : 'Hệ thống');
                const values = [new Date(row.timestamp * 1000).toLocaleString('vi-VN'), `${actor} / ${row.role || '—'}`, this.operationEventLabel(row.action), /^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) /.exec(row.action)?.[1] || '—', resultLabel];
                const labels = ['Thời gian', 'Tài khoản / Vai trò', 'Hành động', 'Method', 'Kết quả'];
                for (const [index, value] of values.entries()) {
                    const cell = document.createElement('td'); cell.dataset.label = labels[index]; cell.textContent = value; tr.append(cell);
                    if (index === 4) cell.className = resultLabel.startsWith('Thất bại') ? 'operations-result is-error' : 'operations-result';
                }
                const cell = document.createElement('td'), details = document.createElement('button');
                cell.className = 'operations-log-detail';
                details.className = 'btn btn-outline-secondary operations-detail-button';
                details.textContent = 'Xem chi tiết';
                details.onclick = () => this.openOperationInspector(row, details, query.get('kind'));
                cell.append(details); tr.append(cell); body.append(tr);
            }
            if (!result.rows.length) { const tr = body.insertRow(); const cell = tr.insertCell(); cell.colSpan = 6; cell.textContent = 'Không có nhật ký phù hợp.'; }
            document.getElementById('operations-log-count').textContent = `${result.total ? offset + 1 : 0}–${offset + result.rows.length} / ${result.total}`;
            document.getElementById('operations-log-prev').disabled = offset === 0;
            document.getElementById('operations-log-next').disabled = offset + 25 >= result.total;
        } catch (error) { this.operationFeedback(error.message, true); }
        finally { if (request === this.operationLogRequest) table.setAttribute('aria-busy', 'false'); }
    }

    operationLogPage(direction) {
        this.operationLogOffset = Math.max(0, (this.operationLogOffset || 0) + direction * 25);
        void this.loadOperationLogs();
    }

    openOperationInspector(row, trigger, kind) {
        this.operationInspectorAnimation?.cancel();
        this.operationInspectorAnimation = null;
        const drawer = document.getElementById('operations-inspector');
        const content = document.getElementById('operations-inspector-content');
        this.operationInspectorTrigger = trigger;
        document.getElementById('operations-inspector-kind').textContent = kind === 'audit_log' ? 'AUDIT LOG · THAO TÁC NGƯỜI DÙNG' : 'NHẬT KÝ VẬN HÀNH · SỰ KIỆN HỆ THỐNG';
        document.getElementById('operations-inspector-title').textContent = row.action;
        content.replaceChildren();
        const facts = document.createElement('dl');
        facts.className = 'drawer-facts';
        for (const [label, value] of [['Thời gian', new Date(row.timestamp * 1000).toLocaleString('vi-VN')], ['Tài khoản', row.username || (kind === 'audit_log' ? 'Chưa xác định' : 'Hệ thống')], ['Vai trò', row.role || '—'], ['Kết quả', row.status ?? 'Đã ghi nhận'], ['Địa chỉ IP', row.ip || '—'], ['Đối tượng', row.object || '—']]) {
            const item = document.createElement('div'), term = document.createElement('dt'), description = document.createElement('dd');
            term.textContent = label; description.textContent = String(value);
            item.append(term, description); facts.append(item);
        }
        content.append(facts);
        const changes = row.details?.changes;
        if (Array.isArray(changes)) {
            for (const change of changes) {
                const heading = document.createElement('h6');
                heading.textContent = `${change.table || 'Dữ liệu'} · ${change.operation || 'Thay đổi'}`;
                const compare = document.createElement('div'); compare.className = 'operations-change-grid';
                const before = change.changes ? Object.fromEntries(Object.entries(change.changes).map(([key, v]) => [key, v.old])) : change.old;
                const after = change.changes ? Object.fromEntries(Object.entries(change.changes).map(([key, v]) => [key, v.new])) : change.new;
                for (const [label, value] of [['Trước thay đổi', before], ['Sau thay đổi', after]]) {
                    const section = document.createElement('section'), title = document.createElement('strong'), pre = document.createElement('pre');
                    title.textContent = label; pre.textContent = JSON.stringify(value ?? null, null, 2);
                    section.append(title, pre); compare.append(section);
                }
                content.append(heading, compare);
            }
        }
        const raw = document.createElement('details'), summary = document.createElement('summary'), pre = document.createElement('pre');
        raw.className = 'operations-raw-detail'; summary.textContent = 'Dữ liệu sự kiện (JSON)';
        pre.textContent = JSON.stringify(row.details || {}, null, 2);
        raw.append(summary, pre); raw.open = !Array.isArray(changes) || !changes.length; content.append(raw);
        drawer.inert = false; drawer.classList.add('open'); drawer.setAttribute('aria-hidden', 'false');
        drawer.showModal();
        drawer.onkeydown = event => {
            if (event.key !== 'Tab') return;
            const controls = Array.from(drawer.querySelectorAll('button, summary')).filter(el => el.getClientRects().length);
            const first = controls[0], last = controls.at(-1);
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        };
        drawer.onclick = event => {
            if (event.target !== drawer) return;
            const bounds = drawer.getBoundingClientRect();
            if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) this.closeOperationInspector();
        };
    }

    async closeOperationInspector() {
        const drawer = document.getElementById('operations-inspector');
        if (!drawer?.classList.contains('open') || this.operationInspectorAnimation) return;
        if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            const animation = drawer.animate([{opacity:1, transform:'translate(0)'},
                {opacity:0, transform:window.matchMedia('(max-width:767px)').matches ? 'translateY(32px)' : 'translateX(32px)'}],
                {duration:180, easing:'ease-in', fill:'forwards'});
            this.operationInspectorAnimation = animation;
            await animation.finished.catch(() => {});
            if (this.operationInspectorAnimation !== animation) return;
            this.operationInspectorAnimation = null;
            animation.cancel();
        }
        drawer.classList.remove('open'); drawer.setAttribute('aria-hidden', 'true'); drawer.inert = true;
        drawer.close();
        this.operationInspectorTrigger?.focus();
    }
}
window.applyAdminFeature(AdminOperationsFeature);
})();
