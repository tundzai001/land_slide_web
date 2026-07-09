// =====================================================
// DATABASE MANAGER - CSV/ZIP EXPORT & CLEANUP
// =====================================================

class DatabaseManager {
    constructor() {
        this.token = localStorage.getItem('token') || sessionStorage.getItem('token');
        this.allData = [];
        this.filteredData = [];
        this.currentEditModal = null;
        this.exportProjects = [];
        this.exportStations = [];
        this.exportStationRequestSeq = 0;

        if (!this.token) {
            window.SPA_SUPPRESS_AUTO_MAP_ON_LANDING = true;
            sessionStorage.setItem('loginReturnView', 'admin');
            sessionStorage.setItem('openLandingLogin', 'true');
            window.location.href = '/';
            return;
        }

        this.init();
    }

    init() {
        console.log('🗄️ [DB MANAGER] Initializing...');

        const editModalEl = document.getElementById('editRecordModal');
        if (editModalEl) {
            this.currentEditModal = new bootstrap.Modal(editModalEl);
        }

        // Support both Bootstrap tabs (old) and sidebar links (new)
        const dbTabBtn = document.querySelector('button[data-bs-target="#tab-database"]');
        if (dbTabBtn) {
            dbTabBtn.addEventListener('shown.bs.tab', () => {
                this.loadAllData();
            });
        }
        const dbSidebarLink = document.querySelector('[data-tab="tab-database"]');
        if (dbSidebarLink) {
            dbSidebarLink.addEventListener('click', () => {
                this.loadAllData();
            });
        }

        console.log('✅ [DB MANAGER] Initialized');
    }

    async loadAllData() {
        console.log('📡 [DB MANAGER] Loading all database records...');

        const tbody = document.getElementById('db-table-body');
        if (tbody) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="4" class="text-center py-4">
                        <div class="spinner-border text-primary"></div>
                        <p class="mt-2">Đang tải dữ liệu...</p>
                    </td>
                </tr>
            `;
        }

        try {
            // Tải dữ liệu song song
            const [stations, devices, sensorData, alerts] = await Promise.all([
                this.fetchTable('stations'),
                this.fetchTable('devices'),
                this.fetchTable('sensor-data'),
                this.fetchTable('alerts')
            ]);

            // Gộp dữ liệu và đánh dấu bảng nguồn (_table)
            this.allData = [
                ...stations.map(s => ({ ...s, _table: 'stations' })),
                ...devices.map(d => ({ ...d, _table: 'devices' })),
                ...sensorData.map(sd => ({ ...sd, _table: 'sensor_data' })),
                ...alerts.map(a => ({ ...a, _table: 'alerts' }))
            ];

            // Cập nhật số liệu thống kê từ server (nhanh, chính xác)
            this.fetchStats();

            this.applyFilter();

            console.log(`✅ [DB MANAGER] Loaded ${this.allData.length} records`);

        } catch (e) {
            console.error('❌ [DB MANAGER] Error loading data:', e);
            if (tbody) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="4" class="text-center py-4">
                            <i class="bi bi-exclamation-triangle text-danger fs-1"></i>
                            <p class="text-danger mt-2">Lỗi tải dữ liệu: ${e.message}</p>
                        </td>
                    </tr>
                `;
            }
            window.toast?.error('Không thể tải database');
        }
    }

    async fetchTable(endpoint) {
        try {
            const res = await fetch(`/api/admin/db/${endpoint}`, {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) {
                console.warn(`⚠️ Failed to load ${endpoint}: ${res.status}`);
                return [];
            }

            return await res.json();
        } catch (e) {
            console.error(`❌ Error fetching ${endpoint}:`, e);
            return [];
        }
    }

    applyFilter() {
        const tableFilter = document.getElementById('db-filter-table')?.value || 'all';
        const searchTerm = document.getElementById('db-search')?.value.toLowerCase() || '';
        const limit = parseInt(document.getElementById('db-limit')?.value || '100');

        let filtered = tableFilter === 'all'
            ? this.allData
            : this.allData.filter(item => item._table === tableFilter);

        if (searchTerm) {
            filtered = filtered.filter(item => {
                const searchable = JSON.stringify(item).toLowerCase();
                return searchable.includes(searchTerm);
            });
        }

        this.filteredData = filtered.slice(0, limit);
        this.renderTable();
    }

    renderTable() {
        const tbody = document.getElementById('db-table-body');
        if (!tbody) return;

        if (this.filteredData.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="4" class="text-center py-4">
                        <i class="bi bi-inbox fs-1 text-muted"></i>
                        <p class="text-muted mt-2 font-monospace">NO_DATA_FOUND</p>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = this.filteredData.map(item => {
            const badgeColor = this.getTableBadgeColor(item._table);
            const previewData = this.getPreviewData(item);

            return `
                <tr class="db-row font-monospace" style="font-size: 0.9rem;">
                    <td class="text-muted">#${item.id}</td>
                    <td><span class="badge ${badgeColor} bg-opacity-10 border border-${badgeColor.replace('bg-', '')} text-${badgeColor.replace('bg-', '')}">${item._table.toUpperCase()}</span></td>
                    <td>
                        <div class="terminal-text" style="max-width: 600px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary);">
                            <span class="text-muted me-2">>></span>${previewData}
                        </div>
                    </td>
                    <td>
                        <div class="btn-group btn-group-sm opacity-50 hover-opacity-100">
                            <button class="btn btn-outline-secondary border-0" onclick="window.dbManager.viewRecord('${item._table}', ${item.id})" title="VIEW">
                                <i class="bi bi-eye"></i>
                            </button>
                            <button class="btn btn-outline-secondary border-0" onclick="window.dbManager.editRecord('${item._table}', ${item.id})" title="EDIT">
                                <i class="bi bi-pencil"></i>
                            </button>
                            <button class="btn btn-outline-danger border-0" onclick="window.dbManager.deleteRecord('${item._table}', ${item.id})" title="DELETE">
                                <i class="bi bi-trash"></i>
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
    }

    getTableBadgeColor(table) {
        const colors = {
            'stations': 'bg-primary',
            'devices': 'bg-success',
            'sensor_data': 'bg-info',
            'alerts': 'bg-warning'
        };
        return colors[table] || 'bg-secondary';
    }

    getPreviewData(item) {
        if (item._table === 'stations') {
            return `${item.station_code} - ${item.name} (${item.status})`;
        }
        if (item._table === 'devices') {
            return `${item.device_code} - ${item.device_type} - Topic: ${item.mqtt_topic || 'N/A'}`;
        }
        if (item._table === 'sensor_data') {
            const timestamp = new Date(item.timestamp * 1000).toLocaleString('vi-VN');
            return `[${timestamp}] ${item.sensor_type}: ${JSON.stringify(item.data).substring(0, 100)}...`;
        }
        if (item._table === 'alerts') {
            return `[${item.level}] ${item.category}: ${item.message}`;
        }
        return JSON.stringify(item).substring(0, 100);
    }

    updateStats(stats) {
        document.getElementById('stat-stations').textContent = stats.stations;
        document.getElementById('stat-devices').textContent = stats.devices;
        document.getElementById('stat-data').textContent = stats.sensor_data;
        document.getElementById('stat-alerts').textContent = stats.alerts;
    }

    async fetchStats() {
        try {
            const res = await fetch('/api/admin/db/stats', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) {
                console.warn('⚠️ Failed to fetch DB stats:', res.status);
                return;
            }

            const stats = await res.json();
            this.updateStats(stats);
        } catch (e) {
            console.warn('❌ Error fetching DB stats:', e);
        }
    }

    viewRecord(table, id) {
        const record = this.allData.find(r => r._table === table && r.id === id);
        if (!record) return;

        const formatted = JSON.stringify(record, null, 2);
        alert(`Record từ bảng "${table}" (ID: ${id})\n\n${formatted}`);
    }

    editRecord(table, id) {
        const record = this.allData.find(r => r._table === table && r.id === id);
        if (!record) {
            window.toast?.error('Không tìm thấy record');
            return;
        }

        document.getElementById('edit-table').value = table;
        document.getElementById('edit-id').value = id;
        document.getElementById('edit-json').value = JSON.stringify(record, null, 2);

        this.currentEditModal.show();
    }

    async saveRecord() {
        try {
            const table = document.getElementById('edit-table').value;
            const id = document.getElementById('edit-id').value;
            const jsonText = document.getElementById('edit-json').value;

            let updatedData;
            try {
                updatedData = JSON.parse(jsonText);
            } catch (e) {
                window.toast?.error('JSON không hợp lệ: ' + e.message);
                return;
            }

            const res = await fetch(`/api/admin/db/${table}/${id}`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(updatedData)
            });

            if (!res.ok) throw new Error(`HTTP ${res.status}`);

            window.toast?.success('✅ Cập nhật thành công!');
            this.currentEditModal.hide();
            this.loadAllData();

        } catch (e) {
            console.error('❌ Error saving record:', e);
            window.toast?.error('Lỗi lưu: ' + e.message);
        }
    }

    async deleteRecord(table, id) {
        if (!confirm(`Bạn có chắc muốn XÓA record này?\n\nTable: ${table}\nID: ${id}`)) {
            return;
        }

        try {
            const res = await fetch(`/api/admin/db/${table}/${id}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) throw new Error(`HTTP ${res.status}`);

            window.toast?.success('✅ Đã xóa!');
            this.loadAllData();

        } catch (e) {
            console.error('❌ Error deleting record:', e);
            window.toast?.error('Lỗi xóa: ' + e.message);
        }
    }

    // =========================================================================
    // EXPORT EXCEL/CSV & ZIP LOGIC (ADVANCED FORM + PROGRESS BAR)
    // =========================================================================

    // Hiện Modal Chọn Bảng và nạp danh sách dự án
    async exportToExcel() {
        const modalEl = document.getElementById('exportExcelModal');
        if (!modalEl) return;

        const modal = new bootstrap.Modal(modalEl);
        
        // Reset UI
        document.getElementById('export-progress-container').style.display = 'none';
        document.getElementById('btn-export-start').disabled = false;
        document.getElementById('btn-export-cancel').disabled = false;
        
        // Nạp danh sách Project
        this.setExportSelectLoading('export-project-select', 'Dang tai danh sach du an...');
        this.setExportSelectLoading('export-station-select', 'Chon du an de tai tram...');
        
        modal.show();

        await this.populateExportProjects();
    }

    escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, (char) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[char]));
    }

    setExportSelectLoading(selectId, message) {
        const select = document.getElementById(selectId);
        if (!select) return;
        select.disabled = true;
        select.innerHTML = `<option value="all">${this.escapeHtml(message)}</option>`;
    }

    async fetchJson(url) {
        const res = await fetch(url, {
            headers: { 'Authorization': `Bearer ${this.token}` }
        });

        if (!res.ok) {
            const message = await res.text().catch(() => '');
            throw new Error(message || `HTTP ${res.status}`);
        }

        return await res.json();
    }

    populateExportProjectsLegacyUnused() {
        const select = document.getElementById('export-project-select');
        if (!select) return;
        
        // Giả sử window.adminManager.projects đã có dữ liệu
        const projects = window.adminManager?.projects || [];
        
        let html = '<option value="all">-- Tất cả Dự án --</option>';
        projects.forEach(p => {
            html += `<option value="${p.id}">${p.project_code} - ${p.name || ''}</option>`;
        });
        select.innerHTML = html;
        
        this.onExportProjectChange();
    }
    
    onExportProjectChangeLegacyUnused() {
        const pSelect = document.getElementById('export-project-select');
        const sSelect = document.getElementById('export-station-select');
        if (!pSelect || !sSelect) return;
        
        const projectId = pSelect.value;
        const stations = window.adminManager?.stations || [];
        
        let html = '<option value="all">-- Tất cả Trạm --</option>';
        stations.forEach(s => {
            if (projectId === 'all' || s.project_id == projectId) {
                html += `<option value="${s.id}">${s.station_code} - ${s.name || ''}</option>`;
            }
        });
        sSelect.innerHTML = html;
    }

    async populateExportProjects() {
        const select = document.getElementById('export-project-select');
        if (!select) return;

        try {
            const cachedProjects = window.adminManager?.projectsData;
            const projects = Array.isArray(cachedProjects)
                ? cachedProjects
                : await this.fetchJson('/api/admin/projects');
            this.exportProjects = Array.isArray(projects) ? projects : [];

            let html = '<option value="all">-- Tat ca Du an --</option>';
            this.exportProjects.forEach(p => {
                html += `<option value="${p.id}">${this.escapeHtml(p.project_code)} - ${this.escapeHtml(p.name || '')}</option>`;
            });
            select.innerHTML = html;
            select.disabled = false;

            await this.onExportProjectChange();
        } catch (e) {
            console.error('Error loading export projects:', e);
            select.innerHTML = '<option value="all">Khong tai duoc danh sach du an</option>';
            select.disabled = true;
            this.setExportSelectLoading('export-station-select', 'Khong tai duoc danh sach tram');
            window.toast?.error('Khong the tai danh sach du an/tram de export');
        }
    }

    async onExportProjectChange() {
        const pSelect = document.getElementById('export-project-select');
        const sSelect = document.getElementById('export-station-select');
        if (!pSelect || !sSelect) return;

        const projectId = pSelect.value;
        const requestSeq = ++this.exportStationRequestSeq;
        this.setExportSelectLoading('export-station-select', 'Dang tai danh sach tram...');

        try {
            const stations = projectId && projectId !== 'all'
                ? await this.fetchJson(`/api/admin/projects/${projectId}/stations`)
                : await this.fetchJson('/api/admin/db/stations');

            if (requestSeq !== this.exportStationRequestSeq) return;

            this.exportStations = Array.isArray(stations) ? stations : [];
            let html = '<option value="all">-- Tat ca Tram --</option>';
            this.exportStations.forEach(s => {
                html += `<option value="${s.id}">${this.escapeHtml(s.station_code)} - ${this.escapeHtml(s.name || s.station_name || '')}</option>`;
            });
            sSelect.innerHTML = html;
            sSelect.disabled = false;
        } catch (e) {
            console.error('Error loading export stations:', e);
            if (requestSeq !== this.exportStationRequestSeq) return;
            sSelect.innerHTML = '<option value="all">Khong tai duoc danh sach tram</option>';
            sSelect.disabled = true;
            window.toast?.error('Khong the tai danh sach tram cho export');
        }
    }

    async confirmExportExcel() {
        try {
            // Lấy các bảng được chọn
            const tables = [];
            if (document.getElementById('export-projects')?.checked) {
                tables.push('projects');
                tables.push('stations');
            }
            if (document.getElementById('export-stations')?.checked) tables.push('stations');
            if (document.getElementById('export-devices')?.checked) tables.push('devices');
            if (document.getElementById('export-sensor-data')?.checked) tables.push('sensor_data');
            if (document.getElementById('export-alerts')?.checked) tables.push('alerts');
            const uniqueTables = [...new Set(tables)];

            // Kiểm tra
            if (uniqueTables.length === 0) {
                window.toast?.warning('⚠️ Vui lòng chọn ít nhất 1 bảng dữ liệu!');
                return;
            }

            // Lấy các filters
            const projectId = document.getElementById('export-project-select')?.value;
            const stationId = document.getElementById('export-station-select')?.value;
            const startDate = document.getElementById('export-start-date')?.value;
            const endDate = document.getElementById('export-end-date')?.value;
            
            const projectIds = projectId && projectId !== 'all' ? [parseInt(projectId)] : null;
            const stationIds = stationId && stationId !== 'all' ? [parseInt(stationId)] : null;
            const selectedStation = stationIds
                ? this.exportStations.find(s => String(s.id) === String(stationIds[0]))
                : null;
            const effectiveProjectIds = projectIds
                || (selectedStation?.project_id ? [parseInt(selectedStation.project_id)] : null);
            
            // Lấy Sensor types nếu có chọn sensor_data
            let sensorTypes = null;
            if (document.getElementById('export-sensor-data')?.checked) {
                sensorTypes = [];
                if (document.getElementById('sensor-gnss')?.checked) sensorTypes.push('gnss');
                if (document.getElementById('sensor-imu')?.checked) sensorTypes.push('imu');
                if (document.getElementById('sensor-rain')?.checked) sensorTypes.push('rain');
                if (document.getElementById('sensor-water')?.checked) sensorTypes.push('water');
            }
            
            const payload = { 
                tables: uniqueTables,
                project_ids: effectiveProjectIds,
                station_ids: stationIds,
                sensor_types: sensorTypes,
                start_date: startDate || null,
                end_date: endDate || null
            };

            // Khóa UI
            document.getElementById('btn-export-start').disabled = true;
            document.getElementById('btn-export-cancel').disabled = true;
            const progressContainer = document.getElementById('export-progress-container');
            const progressBar = document.getElementById('export-progress-bar');
            const progressText = document.getElementById('export-status-text');
            const progressDetail = document.getElementById('export-progress-detail');
            
            progressContainer.style.display = 'block';
            progressBar.style.width = '5%';
            progressBar.innerText = '5%';
            progressText.innerText = 'Đang khởi tạo tác vụ...';
            progressDetail.innerText = 'Vui lòng không đóng cửa sổ này';

            // Gọi API /start
            const res = await fetch('/api/admin/db/export-excel/start', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Export start failed');
            }
            
            const data = await res.json();
            const taskId = data.task_id;
            
            // Start Polling
            const pollInterval = setInterval(async () => {
                try {
                    const statusRes = await fetch(`/api/admin/db/export-excel/${taskId}/progress`, {
                        headers: { 'Authorization': `Bearer ${this.token}` }
                    });
                    if (!statusRes.ok) throw new Error('Failed to check progress');
                    
                    const statusData = await statusRes.json();
                    
                    progressBar.style.width = `${statusData.percent}%`;
                    progressBar.innerText = `${statusData.percent}%`;
                    progressDetail.innerText = statusData.message || 'Đang xử lý...';
                    
                    if (statusData.status === 'completed') {
                        clearInterval(pollInterval);
                        progressText.innerText = '✅ Hoàn tất!';
                        progressBar.classList.remove('progress-bar-animated');
                        
                        // Tự động tải file
                        const downloadUrl = `/api/admin/db/export-excel/${taskId}/download`;
                        const downloadRes = await fetch(downloadUrl, {
                            headers: { 'Authorization': `Bearer ${this.token}` }
                        });
                        
                        if (downloadRes.ok) {
                            const blob = await downloadRes.blob();
                            const url = URL.createObjectURL(blob);
                            const link = document.createElement('a');
                            link.href = url;
                            link.download = statusData.filename || `landslide_backup_${Date.now()}.zip`;
                            document.body.appendChild(link);
                            link.click();
                            document.body.removeChild(link);
                            URL.revokeObjectURL(url);
                            
                            window.toast?.success('✅ Đã tải xuống file xuất dữ liệu!', 5000);
                        } else {
                            throw new Error('Không thể tải file zip');
                        }
                        
                        // Đóng modal
                        setTimeout(() => {
                            const modal = bootstrap.Modal.getInstance(document.getElementById('exportExcelModal'));
                            if (modal) modal.hide();
                            document.getElementById('btn-export-start').disabled = false;
                            document.getElementById('btn-export-cancel').disabled = false;
                        }, 1000);
                        
                    } else if (statusData.status === 'failed') {
                        clearInterval(pollInterval);
                        throw new Error(statusData.error || 'Task failed');
                    }
                    
                } catch (pollErr) {
                    clearInterval(pollInterval);
                    console.error('Polling error:', pollErr);
                    window.toast?.error('❌ Lỗi kiểm tra tiến trình: ' + pollErr.message);
                    document.getElementById('btn-export-start').disabled = false;
                    document.getElementById('btn-export-cancel').disabled = false;
                    progressText.innerText = '❌ Lỗi xuất dữ liệu';
                    progressText.classList.replace('text-primary', 'text-danger');
                    progressBar.classList.replace('bg-success', 'bg-danger');
                    progressBar.classList.remove('progress-bar-animated');
                }
            }, 1000);

        } catch (e) {
            console.error('❌ Export error:', e);
            window.toast?.error('❌ Lỗi export: ' + e.message);
            document.getElementById('btn-export-start').disabled = false;
            document.getElementById('btn-export-cancel').disabled = false;
        }
    }

    // =========================================================================
    // CLEAR DATABASE LOGIC
    // =========================================================================

    clearDatabase() {
        // Reset input and error UI if modal exists
        const input = document.getElementById('clear-db-confirm-input');
        const error = document.getElementById('clear-db-error');

        if (input) input.value = '';
        if (error) error.style.display = 'none';

        const modalEl = document.getElementById('clearDatabaseModal');
        if (modalEl) {
            const modal = new bootstrap.Modal(modalEl);
            modal.show();

            // focus input for convenience
            setTimeout(() => { if (input) input.focus(); }, 300);
            return;
        }

        // Fallback: simple confirm if no modal present
        if (confirm('⚠️ CẢNH BÁO: Bạn có chắc muốn xóa dữ liệu?')) {
            this.performClear();
        }
    }

    async confirmClearDatabase() {
        const input = document.getElementById('clear-db-confirm-input');
        const confirmText = input?.value.trim();

        let apiEndpoint = '';

        // 1. Xóa dữ liệu (Giữ trạm)
        if (confirmText === 'XOA DATA') {
            apiEndpoint = '/api/admin/db/clear-all';
        }
        // 2. Xóa TẤT CẢ (Về ID 1)
        else if (confirmText === 'FACTORY RESET') {
            apiEndpoint = '/api/admin/db/factory-reset';
        }
        else {
            window.toast?.warning('⚠️ Cú pháp sai! Nhập "XOA DATA" hoặc "FACTORY RESET"');
            return;
        }

        try {
            const modal = bootstrap.Modal.getInstance(document.getElementById('clearDatabaseModal'));
            if (modal) modal.hide();

            window.toast?.warning('⏳ Đang xử lý...', 0);

            const res = await fetch(apiEndpoint, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) throw new Error('Failed');

            const result = await res.json();
            window.toast?.success(`✅ ${result.message}`, 5000);

            this.loadAllData(); // Reload lại bảng

        } catch (e) {
            console.error(e);
            window.toast?.error('Lỗi: ' + e.message);
        }
    }

    async performClear() {
        try {
            window.toast?.warning('⏳ Đang xóa database...', 0);

            const res = await fetch('/api/admin/db/clear-all', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) throw new Error('Clear failed');

            const result = await res.json();
            window.toast?.success(`✅ ${result.message || 'Đã xóa dữ liệu'}`);
            this.loadAllData();

        } catch (e) {
            window.toast?.error('Lỗi: ' + e.message);
        }
    }

    // Alias
    loadStations() {
        this.loadAllData();
    }
}

// Initialization
function bootstrapDatabaseManager() {
    console.log('[DB MANAGER] Initializing...');
    if (!window.dbManager) {
        window.dbManager = new DatabaseManager();
    }
}

window.bootstrapDatabaseManager = bootstrapDatabaseManager;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapDatabaseManager, { once: true });
} else {
    bootstrapDatabaseManager();
}
