// =====================================================
// DATABASE MANAGER - THÊM EXPORT EXCEL & XÓA DB
// =====================================================

class DatabaseManager {
    constructor() {
        this.token = localStorage.getItem('token');
        this.allData = [];
        this.filteredData = [];
        this.currentEditModal = null;
        
        if (!this.token) {
            window.location.href = '/pages/login.html';
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
        
        const dbTabBtn = document.querySelector('button[data-bs-target="#tab-database"]');
        if (dbTabBtn) {
            dbTabBtn.addEventListener('shown.bs.tab', () => {
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
            const [stations, devices, sensorData, alerts] = await Promise.all([
                this.fetchTable('stations'),
                this.fetchTable('devices'),
                this.fetchTable('sensor-data'),
                this.fetchTable('alerts')
            ]);

            this.allData = [
                ...stations.map(s => ({ ...s, _table: 'stations' })),
                ...devices.map(d => ({ ...d, _table: 'devices' })),
                ...sensorData.map(sd => ({ ...sd, _table: 'sensor_data' })),
                ...alerts.map(a => ({ ...a, _table: 'alerts' }))
            ];

            this.updateStats({
                stations: stations.length,
                devices: devices.length,
                sensor_data: sensorData.length,
                alerts: alerts.filter(a => !a.is_resolved).length
            });

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
                        <p class="text-muted mt-2">Không có dữ liệu</p>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = this.filteredData.map(item => {
            const badgeColor = this.getTableBadgeColor(item._table);
            const previewData = this.getPreviewData(item);
            
            return `
                <tr>
                    <td><code>${item.id}</code></td>
                    <td><span class="badge ${badgeColor}">${item._table}</span></td>
                    <td>
                        <div style="max-width: 600px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            <small class="text-muted">${previewData}</small>
                        </div>
                    </td>
                    <td>
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-outline-primary" onclick="window.dbManager.viewRecord('${item._table}', ${item.id})" title="Xem chi tiết">
                                <i class="bi bi-eye"></i>
                            </button>
                            <button class="btn btn-outline-warning" onclick="window.dbManager.editRecord('${item._table}', ${item.id})" title="Chỉnh sửa">
                                <i class="bi bi-pencil"></i>
                            </button>
                            <button class="btn btn-outline-danger" onclick="window.dbManager.deleteRecord('${item._table}', ${item.id})" title="Xóa">
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

    // ✅ EXPORT RA EXCEL - BƯỚC 1: Hiện Modal Chọn Bảng
    exportToExcel() {
        const modal = new bootstrap.Modal(document.getElementById('exportExcelModal'));
        modal.show();
    }
    
    // ✅ QUICK SELECT FUNCTIONS
    selectAllExport() {
        ['projects', 'stations', 'devices', 'sensor-data', 'alerts'].forEach(table => {
            const checkbox = document.getElementById(`export-${table}`);
            if (checkbox) checkbox.checked = true;
        });
    }
    
    deselectAllExport() {
        ['projects', 'stations', 'devices', 'sensor-data', 'alerts'].forEach(table => {
            const checkbox = document.getElementById(`export-${table}`);
            if (checkbox) checkbox.checked = false;
        });
    }
    
    selectOnlyData() {
        // Bỏ chọn tất cả
        this.deselectAllExport();
        // Chỉ chọn Sensor Data và Alerts
        document.getElementById('export-sensor-data').checked = true;
        document.getElementById('export-alerts').checked = true;
    }
    
    // ✅ EXPORT RA EXCEL - BƯỚC 2: Xử Lý Export
    async confirmExportExcel() {
        try {
            // Lấy các bảng được chọn
            const selectedTables = [];
            
            if (document.getElementById('export-projects')?.checked) selectedTables.push('projects');
            if (document.getElementById('export-stations')?.checked) selectedTables.push('stations');
            if (document.getElementById('export-devices')?.checked) selectedTables.push('devices');
            if (document.getElementById('export-sensor-data')?.checked) selectedTables.push('sensor_data');
            if (document.getElementById('export-alerts')?.checked) selectedTables.push('alerts');
            
            // Kiểm tra có chọn bảng nào không
            if (selectedTables.length === 0) {
                window.toast?.warning('⚠️ Vui lòng chọn ít nhất 1 bảng để export!');
                return;
            }
            
            // Đóng modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('exportExcelModal'));
            if (modal) modal.hide();
            
            // Hiển thị toast đang xử lý
            window.toast?.info('⏳ Đang tạo file Excel... Vui lòng chờ!', 0);
            
            // Gọi API với danh sách bảng được chọn
            const res = await fetch('/api/admin/db/export-excel', {
                method: 'POST',
                headers: { 
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ tables: selectedTables })
            });
            
            if (!res.ok) throw new Error('Export failed');
            
            // Download file
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `landslide_db_${Date.now()}.xlsx`;
            link.click();
            
            URL.revokeObjectURL(url);
            
            window.toast?.success(`✅ Export thành công ${selectedTables.length} bảng!`, 3000);
            
        } catch (e) {
            console.error('❌ Export error:', e);
            window.toast?.error('❌ Lỗi export: ' + e.message);
        }
    }

    // ✅ XÓA SẠCH DATABASE - BƯỚC 1: Hiện Modal
    clearDatabase() {
        // Reset input và error
        const input = document.getElementById('clear-db-confirm-input');
        const error = document.getElementById('clear-db-error');
        
        if (input) input.value = '';
        if (error) error.style.display = 'none';
        
        // Hiện modal
        const modal = new bootstrap.Modal(document.getElementById('clearDatabaseModal'));
        modal.show();
        
        // Focus vào input
        setTimeout(() => {
            if (input) input.focus();
        }, 500);
    }
    
    // ✅ XÓA SẠCH DATABASE - BƯỚC 2: Xác nhận
    async confirmClearDatabase() {
        const input = document.getElementById('clear-db-confirm-input');
        const error = document.getElementById('clear-db-error');
        const errorMsg = document.getElementById('clear-db-error-message');
        
        const confirmText = input?.value.trim();
        
        // Kiểm tra cú pháp
        if (confirmText !== 'XOA TAT CA') {
            if (error && errorMsg) {
                errorMsg.textContent = `Sai cú pháp! Bạn gõ: "${confirmText}" - Cần gõ chính xác: XOA TAT CA`;
                error.style.display = 'block';
            }
            
            // Shake animation cho input
            if (input) {
                input.style.animation = 'shake 0.5s';
                setTimeout(() => input.style.animation = '', 500);
            }
            
            window.toast?.warning('⚠️ Cú pháp không đúng!');
            return;
        }
        
        try {
            // Đóng modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('clearDatabaseModal'));
            if (modal) modal.hide();
            
            // Hiển thị toast đang xử lý
            window.toast?.warning('⏳ Đang xóa database... Vui lòng chờ!', 0);
            
            const res = await fetch('/api/admin/db/clear-all', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            
            if (!res.ok) throw new Error('Clear failed');
            
            const result = await res.json();
            
            // Thành công
            window.toast?.success(`✅ Đã xóa ${result.deleted_count.toLocaleString()} records!`, 5000);
            
            // Reload data
            this.loadAllData();
            
        } catch (e) {
            console.error('❌ Clear error:', e);
            window.toast?.error('❌ Lỗi xóa database: ' + e.message);
        }
    }

    // Alias
    loadStations() {
        this.loadAllData();
    }
}

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    console.log('✅ [DB MANAGER] DOM loaded, initializing...');
    window.dbManager = new DatabaseManager();
});