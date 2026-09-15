// =====================================================
// DATABASE MANAGER - CSV/ZIP EXPORT & CLEANUP
// =====================================================

class DatabaseManager {
    constructor() {
        this.token = window.authSession?.getToken() || null;
        this.allData = [];
        this.filteredData = [];
        this.currentDataset = 'stations';
        this.offset = 0;
        this.limit = 100;
        this.total = 0;
        this.hasMore = false;
        this.hasExactTotal = true;
        this.sort = '-id';
        this.searchTimer = null;
        this.selectedRecord = null;
        this.filters = {};
        this.filterOptions = { projects: [], stations: [] };
        this.filterOptionsLoaded = false;
        this.filterOptionsPromise = null;
        this.currentEditModal = null;
        this.exportProjects = [];
        this.exportStations = [];
        this.exportStationRequestSeq = 0;
        this.exportTaskId = localStorage.getItem('activeDatabaseExportTaskId');
        this.exportTaskState = null;
        this.exportPollTimer = null;
        this.exportDownloadStarted = false;
        this.datasetLoadSequence = 0;
        this.datasetRequestController = null;
        this.datasetPrefetchController = null;
        this.datasetPageCache = new Map();
        this.statsTimer = null;
        this.statsPromise = null;
        this.statsLoaded = false;

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
        if (dbSidebarLink && !window.adminManager?.switchTab) {
            dbSidebarLink.addEventListener('click', () => {
                this.loadAllData();
            });
        }

        console.log('✅ [DB MANAGER] Initialized');
        this.renderContextFilters();
        if (this.exportTaskId) this.startExportPolling(this.exportTaskId);
        if (document.getElementById('tab-database')?.classList.contains('active')) {
            void this.loadAllData();
        }
    }

    async loadFilterOptions() {
        if (this.filterOptionsLoaded) return;
        if (this.filterOptionsPromise) return this.filterOptionsPromise;
        this.filterOptionsPromise = (async () => {
        try {
            const headers = { 'Authorization': `Bearer ${this.token}` };
            const [projectsRes, stationsRes] = await Promise.all([
                fetch('/api/admin/projects', { headers }),
                fetch('/api/admin/db/stations?summary_only=true&sort=station_code', { headers }),
            ]);
            this.filterOptions.projects = projectsRes.ok ? await projectsRes.json() : [];
            this.filterOptions.stations = stationsRes.ok ? await stationsRes.json() : [];
            this.filterOptionsLoaded = projectsRes.ok && stationsRes.ok;
            this.renderContextFilters();
        } catch (error) {
            console.warn('[DB MANAGER] filter options unavailable:', error);
        } finally {
            this.filterOptionsPromise = null;
        }
        })();
        return this.filterOptionsPromise;
    }

    async loadAllData() {
        const tbody = document.getElementById('db-table-body');
        if (!tbody) return;
        const loadSequence = ++this.datasetLoadSequence;
        this.datasetRequestController?.abort();
        this.datasetRequestController = new AbortController();
        tbody.innerHTML = '<tr><td colspan="5"><div class="ops-loading"><span class="spinner-border spinner-border-sm" role="status"></span><span>Đang tải dataset…</span></div></td></tr>';
        document.getElementById('db-current-meta').textContent = 'Đang đồng bộ dữ liệu…';
        try {
            await this.fetchCurrentDataset(this.datasetRequestController.signal);
            if (loadSequence === this.datasetLoadSequence) {
                this.scheduleStats();
                void this.loadFilterOptions();
            }
        } catch (e) {
            if (e.name === 'AbortError' || loadSequence !== this.datasetLoadSequence) return;
            console.error('[DB MANAGER] load error:', e);
            tbody.innerHTML = `<tr><td colspan="5"><div class="ops-empty is-error"><i class="bi bi-exclamation-circle"></i><strong>Không tải được dữ liệu</strong><p>${this.escapeHtml(e.message)}</p><button class="btn btn-outline-primary" onclick="window.dbManager.loadAllData()">Thử lại</button></div></td></tr>`;
        }
    }

    datasetConfig(dataset = this.currentDataset) {
        return {
            stations: { endpoint: 'stations', title: 'Trạm', icon: 'bi-broadcast-pin' },
            devices: { endpoint: 'devices', title: 'Thiết bị', icon: 'bi-cpu' },
            sensor_data: { endpoint: 'sensor-data', title: 'Dữ liệu cảm biến', icon: 'bi-activity' },
            gnss_adjustments: { endpoint: 'sensor-data', title: 'Kết quả bình sai GNSS', icon: 'bi-crosshair2' },
            alerts: { endpoint: 'alerts', title: 'Cảnh báo', icon: 'bi-bell' }
        }[dataset];
    }

    buildDatasetRequest(offset = this.offset) {
        const dataset = this.currentDataset;
        const config = this.datasetConfig(dataset);
        const sort = ['sensor_data', 'gnss_adjustments'].includes(this.currentDataset)
            ? (this.sort === 'id' ? 'timestamp' : '-timestamp')
            : this.sort;
        const query = new URLSearchParams({ offset: String(offset), limit: String(this.limit), sort });
        const search = document.getElementById('db-search')?.value.trim() || '';
        if (search && ['stations', 'devices'].includes(dataset)) query.set('q', search);
        Object.entries(this.filters).forEach(([key, value]) => {
            if (value !== '' && value != null) query.set(key, value);
        });
        if (dataset === 'gnss_adjustments') {
            query.set('sensor_type', 'gnss_adjusted');
            query.set('include_internal', 'true');
        }
        if (['sensor_data', 'gnss_adjustments'].includes(dataset)) {
            query.set('include_total', 'false');
            query.set('include_data', 'false');
        }
        return { dataset, offset, search, url: `/api/admin/db/${config.endpoint}?${query}` };
    }

    async requestDatasetPage(request, signal) {
        const res = await fetch(request.url, { headers: { 'Authorization': `Bearer ${this.token}` }, signal });
        if (!res.ok) {
            const errorBody = await res.json().catch(() => null);
            throw new Error(errorBody?.detail || `HTTP ${res.status}`);
        }
        const rows = await res.json();
        const totalHeader = res.headers.get('X-Total-Count');
        const hasExactTotal = totalHeader !== null;
        const hasMore = hasExactTotal
            ? request.offset + rows.length < Number(totalHeader || 0)
            : res.headers.get('X-Has-More') === 'true';
        return { ...request, rows, hasExactTotal, hasMore, total: hasExactTotal ? Number(totalHeader || 0) : request.offset + rows.length + (hasMore ? 1 : 0) };
    }

    applyDatasetPage(page) {
        this.hasExactTotal = page.hasExactTotal;
        this.hasMore = page.hasMore;
        this.total = page.total;
        this.allData = page.rows.map(row => ({ ...row, _table: page.dataset }));
        this.filteredData = page.search && !['stations', 'devices'].includes(page.dataset)
            ? this.allData.filter(row => JSON.stringify(row).toLowerCase().includes(page.search.toLowerCase()))
            : this.allData;
        this.renderTable();
    }

    async fetchCurrentDataset(signal) {
        const request = this.buildDatasetRequest();
        let page = this.datasetPageCache.get(request.url);
        if (page) this.datasetPageCache.delete(request.url);
        else page = await this.requestDatasetPage(request, signal);
        this.applyDatasetPage(page);
        void this.prefetchNextDatasetPage();
    }

    async prefetchNextDatasetPage() {
        const hasNext = this.hasExactTotal
            ? this.offset + this.limit < this.total
            : this.hasMore;
        if (!hasNext) return;
        const request = this.buildDatasetRequest(this.offset + this.limit);
        if (this.datasetPageCache.has(request.url)) return;
        this.datasetPrefetchController?.abort();
        const controller = new AbortController();
        this.datasetPrefetchController = controller;
        try {
            const page = await this.requestDatasetPage(request, controller.signal);
            this.datasetPageCache.set(request.url, page);
        } catch (error) {
            if (error.name !== 'AbortError') console.debug('[DB MANAGER] next page prefetch skipped:', error.message);
        } finally {
            if (this.datasetPrefetchController === controller) this.datasetPrefetchController = null;
        }
    }

    clearDatasetPageCache() {
        this.datasetPrefetchController?.abort();
        this.datasetPrefetchController = null;
        this.datasetPageCache.clear();
    }

    applyFilter() {
        clearTimeout(this.searchTimer);
        this.searchTimer = setTimeout(() => {
            this.clearDatasetPageCache();
            this.offset = 0;
            this.loadAllData();
        }, 250);
    }

    selectDataset(dataset, button) {
        if (!this.datasetConfig(dataset)) return;
        this.clearDatasetPageCache();
        this.currentDataset = dataset;
        this.offset = 0;
        this.filters = {};
        document.querySelectorAll('.db-dataset').forEach(el => el.classList.toggle('active', el === button));
        const config = this.datasetConfig();
        document.getElementById('db-current-title').textContent = config.title;
        document.getElementById('db-current-icon').innerHTML = `<i class="bi ${config.icon}"></i>`;
        document.getElementById('db-search').value = '';
        document.getElementById('db-search').placeholder = ['stations', 'devices'].includes(dataset)
            ? 'Tìm trong toàn bộ dataset…'
            : 'Lọc các bản ghi trên trang này…';
        this.renderContextFilters();
        this.closeInspector();
        this.loadAllData();
    }

    filterSelect(label, key, options) {
        const value = this.filters[key] ?? '';
        return `<label class="db-filter-field"><span>${this.escapeHtml(label)}</span><select class="form-select" onchange="window.dbManager.setContextFilter('${key}', this.value)">${options.map(option => `<option value="${this.escapeHtml(option.value)}" ${String(option.value) === String(value) ? 'selected' : ''}>${this.escapeHtml(option.label)}</option>`).join('')}</select></label>`;
    }

    renderContextFilters() {
        const container = document.getElementById('db-context-filters');
        if (!container) return;
        const projectOptions = [{ value: '', label: 'Tất cả dự án' }, ...this.filterOptions.projects.map(project => ({ value: project.id, label: project.name || project.project_code }))];
        const stationOptions = [{ value: '', label: 'Tất cả trạm' }, ...this.filterOptions.stations.map(station => ({ value: station.id, label: station.station_code || station.name }))];
        const clusterOptions = [
            { value: '', label: 'Tất cả cụm' },
            ...this.filterOptions.projects.flatMap(project => {
                const projectLabel = project.project_code || project.name || `Dự án #${project.id}`;
                const clusters = Array.isArray(project.gnss_clusters) ? project.gnss_clusters : [];
                return clusters.map((cluster, index) => ({
                    value: `${project.id}:${index}`,
                    label: `${projectLabel} · ${cluster?.name || `Cụm ${index + 1}`}`,
                }));
            }),
        ];
        const filters = {
            stations: [
                this.filterSelect('Dự án', 'project_id', projectOptions),
                this.filterSelect('Kết nối', 'status', [{ value: '', label: 'Mọi trạng thái' }, { value: 'online', label: 'Online' }, { value: 'offline', label: 'Offline' }]),
            ],
            devices: [
                this.filterSelect('Trạm', 'station_id', stationOptions),
                this.filterSelect('Kết nối', 'connection_status', [{ value: '', label: 'Mọi kết nối' }, { value: 'online', label: 'Online' }, { value: 'offline', label: 'Offline' }]),
                this.filterSelect('Cấu hình', 'is_active', [{ value: '', label: 'Bật và tắt' }, { value: 'true', label: 'Đang bật' }, { value: 'false', label: 'Đã tắt' }]),
            ],
            sensor_data: [
                this.filterSelect('Trạm', 'station_id', stationOptions),
                this.filterSelect('Loại cảm biến', 'sensor_type', [
                    { value: '', label: 'Tất cả sensor' },
                    { value: 'gnss', label: 'GNSS' },
                    { value: 'imu', label: 'IMU' },
                    { value: 'rain', label: 'Mưa' },
                    { value: 'water', label: 'Mực nước' },
                ]),
            ],
            gnss_adjustments: [
                this.filterSelect('Cụm', 'cluster_key', clusterOptions),
            ],
            alerts: [
                this.filterSelect('Trạm', 'station_id', stationOptions),
                this.filterSelect('Mức độ', 'level', [{ value: '', label: 'Mọi mức độ' }, ...['INFO', 'WARNING', 'CRITICAL'].map(value => ({ value, label: value }))]),
                this.filterSelect('Xử lý', 'is_resolved', [{ value: '', label: 'Tất cả cảnh báo' }, { value: 'false', label: 'Đang mở' }, { value: 'true', label: 'Đã xử lý' }]),
            ],
        };
        container.innerHTML = (filters[this.currentDataset] || []).join('');
    }

    setContextFilter(key, value) {
        this.clearDatasetPageCache();
        if (value === '') delete this.filters[key];
        else this.filters[key] = value;
        this.offset = 0;
        this.loadAllData();
    }

    changeSort(value) {
        this.clearDatasetPageCache();
        this.sort = value === 'id' ? 'id' : '-id';
        this.offset = 0;
        this.loadAllData();
    }

    changePageSize(value) {
        this.clearDatasetPageCache();
        this.limit = Math.max(25, Math.min(100, Number(value) || 50));
        this.offset = 0;
        this.loadAllData();
    }

    changePage(direction) {
        const nextOffset = this.offset + direction * this.limit;
        if (nextOffset < 0 || (direction > 0 && !this.hasMore && !this.hasExactTotal)) return;
        if (this.hasExactTotal && nextOffset >= this.total) return;
        this.offset = nextOffset;
        this.loadAllData();
    }

    renderTable() {
        const tbody = document.getElementById('db-table-body');
        if (!tbody) return;

        if (!this.filteredData.length) tbody.innerHTML = '<tr><td colspan="5"><div class="ops-empty"><i class="bi bi-inbox"></i><strong>Không có bản ghi phù hợp</strong><p>Thử đổi từ khóa hoặc dataset.</p></div></td></tr>';
        else tbody.innerHTML = this.filteredData.map(item => {
            const status = this.getRecordStatus(item);
            return `<tr class="db-row" tabindex="0" onclick="window.dbManager.viewRecord('${item._table}', ${item.id})" onkeydown="if(event.key==='Enter') window.dbManager.viewRecord('${item._table}', ${item.id})">
                <td><span class="db-id">#${item.id}</span></td>
                <td><strong class="db-primary">${this.escapeHtml(this.getPreviewData(item))}</strong><small>${this.escapeHtml(this.getRecordSecondary(item))}</small></td>
                <td><span class="management-status ${status.className}"><i class="bi bi-circle-fill"></i>${this.escapeHtml(status.label)}</span></td>
                <td><span class="db-time">${this.escapeHtml(this.getRecordTime(item))}</span></td>
                <td><div class="d-flex gap-1 justify-content-end"><button class="management-icon-btn btn btn-outline-danger" onclick="event.stopPropagation();window.dbManager.deleteRecord('${item._table}', ${item.id})" aria-label="Xóa bản ghi #${item.id}"><i class="bi bi-trash3"></i></button><button class="management-icon-btn btn btn-outline-secondary" onclick="event.stopPropagation();window.dbManager.viewRecord('${item._table}', ${item.id})" aria-label="Xem bản ghi #${item.id}"><i class="bi bi-chevron-right"></i></button></div></td>
            </tr>`;
        }).join('');
        const itemLabel = this.currentDataset === 'gnss_adjustments' ? 'cụm' : 'bản ghi';
        const start = this.total ? this.offset + 1 : 0;
        const end = this.offset + this.allData.length;
        document.getElementById('db-current-meta').textContent = this.hasExactTotal
            ? `${this.total.toLocaleString('vi-VN')} ${itemLabel}`
            : `${this.allData.length} ${itemLabel} mới nhất · tải nhanh`;
        document.getElementById('db-page-summary').textContent = this.hasExactTotal
            ? `Hiển thị ${start}–${Math.min(end, this.total)} / ${this.total.toLocaleString('vi-VN')} ${itemLabel}`
            : `Hiển thị ${start}–${end}${this.hasMore ? ' · còn dữ liệu' : ''}`;
        document.getElementById('db-page-number').textContent = `Trang ${Math.floor(this.offset / this.limit) + 1}`;
        document.getElementById('db-page-prev').disabled = this.offset === 0;
        document.getElementById('db-page-next').disabled = this.hasExactTotal
            ? this.offset + this.limit >= this.total
            : !this.hasMore;
    }

    getTableBadgeColor(table) {
        const colors = {
            'stations': 'bg-primary',
            'devices': 'bg-success',
            'sensor_data': 'bg-info',
            'gnss_adjustments': 'bg-info',
            'alerts': 'bg-warning'
            ,'simulations': 'bg-info'
        };
        return colors[table] || 'bg-secondary';
    }

    getPreviewData(item) {
        if (item._table === 'stations') {
            return `${item.station_code || '--'} · ${item.name || 'Trạm chưa đặt tên'}`;
        }
        if (item._table === 'devices') {
            return `${item.device_code || '--'} · ${item.name || item.device_type || 'Thiết bị'}`;
        }
        if (item._table === 'gnss_adjustments') {
            const project = item.data?.project_code || item.project_code || (item.data?.project_id || item.project_id ? `Dự án #${item.data?.project_id || item.project_id}` : 'GNSS');
            const index = item.data?.cluster_index ?? item.cluster_index;
            const cluster = item.data?.cluster_name || item.cluster_name || (index != null ? `Cụm ${Number(index) + 1}` : 'Cụm GNSS');
            return `${project} · ${cluster}`;
        }
        if (item._table === 'sensor_data') {
            const cluster = item.data?.cluster_name || item.data?.project_code;
            return `${String(item.sensor_type || 'sensor').toUpperCase()} · ${cluster ? `${cluster} · ` : ''}Trạm #${item.station_id ?? '--'}`;
        }
        if (item._table === 'alerts') {
            return `${item.category || 'Cảnh báo'} · ${item.message || '--'}`;
        }
        if (item._table === 'simulations') return item.display_name || `Mô phỏng #${item.id}`;
        return `Bản ghi #${item.id}`;
    }

    getRecordSecondary(item) {
        if (item._table === 'devices') return item.mqtt_topic || item.device_type || 'Không có MQTT topic';
        if (item._table === 'gnss_adjustments') {
            return item.data_preview || 'Mở để xem toàn bộ kết quả cụm';
        }
        if (item._table === 'sensor_data') {
            return item.data_preview || (item.data ? this.compactJsonPreview(item.data) : 'Mở để xem chi tiết');
        }
        if (item._table === 'alerts') return `Trạm #${item.station_id ?? '--'} · ${item.level || '--'}`;
        if (item._table === 'simulations') return `${item.station_code || item.project_code || 'Kịch bản thủ công'} · ${item.summary?.classification || item.mode}`;
        const location = item.location && typeof item.location === 'object'
            ? item.location.name || item.location.address || ([item.location.lat, item.location.lon].every(Number.isFinite) ? `${item.location.lat}, ${item.location.lon}` : 'Chưa có vị trí')
            : item.location || 'Chưa có vị trí';
        return `Dự án #${item.project_id ?? '--'} · ${location}`;
    }

    getRecordStatus(item) {
        if (item._table === 'alerts') return item.is_resolved ? { label: 'Đã xử lý', className: 'is-success' } : { label: item.level || 'Đang mở', className: 'is-warning' };
        if (item._table === 'simulations') return { label: item.status, className: item.status === 'completed' ? 'is-success' : ['failed', 'interrupted'].includes(item.status) ? 'is-offline' : 'is-warning' };
        if (item._table === 'devices') {
            if (!item.is_active) return { label: 'Đã tắt', className: 'is-secondary' };
            return item.effective_status === 'online' ? { label: 'Online', className: 'is-success' } : { label: 'Offline', className: 'is-offline' };
        }
        if (item._table === 'stations') return String(item.status).toLowerCase() === 'online' ? { label: 'Online', className: 'is-success' } : { label: 'Offline', className: 'is-offline' };
        return { label: 'Đã nhận', className: 'is-active' };
    }

    getRecordTime(item) {
        const timestamp = item.timestamp || item.last_data_time || item.last_update || item.updated_at || item.created_at;
        if (!timestamp) return '--';
        const millis = Number(timestamp) > 1e12 ? Number(timestamp) : Number(timestamp) * 1000;
        return new Date(millis).toLocaleString('vi-VN');
    }

    updateStats(stats) {
        const mapping = { stations: ['stat-stations', 'db-count-stations'], devices: ['stat-devices', 'db-count-devices'], sensor_data: ['stat-data', 'db-count-sensor_data'], gnss_adjustments: ['db-count-gnss_adjustments'], alerts: ['stat-alerts', 'db-count-alerts'] };
        Object.entries(mapping).forEach(([key, ids]) => {
            const value = Number(stats[key] || 0).toLocaleString('vi-VN');
            ids.forEach(id => { const el = document.getElementById(id); if (el) el.textContent = value; });
        });
    }

    scheduleStats() {
        if (this.statsLoaded) return;
        clearTimeout(this.statsTimer);
        this.statsTimer = setTimeout(() => this.fetchStats(), 50);
    }

    async fetchStats() {
        if (this.statsLoaded) return;
        if (this.statsPromise) return this.statsPromise;
        this.statsPromise = (async () => {
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
            this.statsLoaded = true;
        } catch (e) {
            console.warn('❌ Error fetching DB stats:', e);
        } finally {
            this.statsPromise = null;
        }
        })();
        return this.statsPromise;
    }

    compactJsonPreview(data) {
        if (!data || typeof data !== 'object') return String(data ?? '{}');
        const entries = Object.entries(data).slice(0, 4).map(([key, value]) => {
            if (value && typeof value === 'object') {
                const size = Array.isArray(value) ? value.length : Object.keys(value).length;
                return `"${key}":${Array.isArray(value) ? `[${size} mục]` : `{${size} trường}`}`;
            }
            const text = typeof value === 'string' ? `"${value.slice(0, 42)}"` : String(value);
            return `"${key}":${text}`;
        });
        return `{${entries.join(', ')}${Object.keys(data).length > entries.length ? ', …' : ''}}`;
    }

    openInspector() {
        document.getElementById('db-inspector').classList.add('open');
        document.getElementById('db-inspector').setAttribute('aria-hidden', 'false');
        document.getElementById('db-inspector-backdrop').classList.add('show');
        document.querySelector('#db-inspector > header button')?.focus();
    }

    async viewRecord(table, id) {
        const record = this.allData.find(r => r._table === table && r.id === id);
        if (!record) return;
        this.selectedRecord = record;
        document.getElementById('db-inspector-title').textContent = `${this.datasetConfig(table)?.title || table} #${id}`;
        if (['sensor_data', 'gnss_adjustments'].includes(table) && !record.data) {
            document.getElementById('db-inspector-content').innerHTML = '<div class="ops-loading"><span class="spinner-border spinner-border-sm" role="status"></span><span>Đang tải chi tiết bản ghi…</span></div>';
            document.getElementById('db-inspector-actions').innerHTML = '';
            this.openInspector();
            try {
                const response = await fetch(`/api/admin/db/sensor-data/${id}`, { headers: { 'Authorization': `Bearer ${this.token}` } });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                Object.assign(record, await response.json(), { _table: table });
                if (this.selectedRecord !== record) return;
            } catch (error) {
                document.getElementById('db-inspector-content').innerHTML = `<div class="ops-empty is-error"><i class="bi bi-exclamation-circle"></i><strong>Không tải được chi tiết</strong><p>${this.escapeHtml(error.message)}</p><button class="btn btn-outline-primary" onclick="window.dbManager.viewRecord('${table}', ${id})">Thử lại</button></div>`;
                return;
            }
        }
        this.renderInspector(record);
        this.openInspector();
    }

    renderInspector(record) {
        const status = this.getRecordStatus(record);
        const isAdjustment = record._table === 'gnss_adjustments';
        const points = isAdjustment && record.data?.points && typeof record.data.points === 'object'
            ? Object.entries(record.data.points)
            : [];
        const number = value => Number.isFinite(Number(value)) ? Number(value).toFixed(4) : '--';
        const pointRows = points.map(([name, point]) => `<tr><th scope="row">${this.escapeHtml(name)}</th><td>${this.escapeHtml(point.station_id ?? '--')}</td><td>${number(point.adjusted_x ?? point.adjusted_n)}</td><td>${number(point.adjusted_y ?? point.adjusted_e)}</td><td>${number(point.adjusted_z ?? point.adjusted_u)}</td><td>${number(point.dx ?? point.correction_n)}</td><td>${number(point.dy ?? point.correction_e)}</td><td>${number(point.dz ?? point.correction_u)}</td></tr>`).join('');
        const dataRows = Object.entries(record.data || {}).map(([key, value]) => `<tr><th scope="row">${this.escapeHtml(key)}</th><td>${this.escapeHtml(value && typeof value === 'object' ? (Array.isArray(value) ? `[${value.length} phần tử]` : `{${Object.keys(value).length} trường}`) : value)}</td></tr>`).join('');
        const resultTable = isAdjustment && pointRows
            ? `<div class="drawer-section-title"><span>TỌA ĐỘ SAU BÌNH SAI</span><span>${points.length} điểm</span></div><div class="adjustment-table-wrap"><table class="adjustment-result-table"><thead><tr><th>Điểm</th><th>Trạm</th><th>X (m)</th><th>Y (m)</th><th>Z (m)</th><th>ΔX</th><th>ΔY</th><th>ΔZ</th></tr></thead><tbody>${pointRows}</tbody></table></div>`
            : `<div class="drawer-section-title"><span>DỮ LIỆU DẠNG BẢNG</span></div><table class="record-detail-table"><tbody>${dataRows || '<tr><td>Không có dữ liệu</td></tr>'}</tbody></table>`;
        document.getElementById('db-inspector-content').innerHTML = `<section class="drawer-summary"><span class="management-status ${status.className}">${this.escapeHtml(status.label)}</span><h6>${this.escapeHtml(this.getPreviewData(record))}</h6><p>${this.escapeHtml(isAdjustment ? `${record.data?.project_code || 'Dự án'} · ${record.data?.cluster_name || 'Cụm GNSS'} · ${this.getRecordTime(record)}` : this.getRecordSecondary(record))}</p></section>${resultTable}<details class="raw-json-details" ontoggle="if(this.open) window.dbManager.renderRawJson()"><summary><span><i class="bi bi-braces" aria-hidden="true"></i> JSON thô</span><small>Chỉ tạo khi mở để giữ giao diện mượt</small></summary><div id="db-raw-json"></div></details>`;
        const editButton = ['stations', 'devices'].includes(record._table)
            ? `<button class="btn btn-primary" onclick="window.dbManager.editRecord('${record._table}', ${record.id})"><i class="bi bi-pencil me-1"></i>Chỉnh sửa</button>`
            : '';
        const simulationButton = record._table === 'simulations' ? `<button class="btn btn-primary" onclick="window.dbManager.downloadSimulation(${record.id})"><i class="bi bi-download me-1"></i>Tải báo cáo</button>` : '';
        const adjustmentButtons = isAdjustment
            ? `${record.data?.audit_json_url ? '<button class="btn btn-outline-primary" onclick="window.dbManager.downloadAdjustmentArtifact(\'json\')"><i class="bi bi-filetype-json me-1"></i>Tải JSON</button>' : ''}${record.data?.excel_report_url || record.data?.report_file_url ? '<button class="btn btn-primary" onclick="window.dbManager.downloadAdjustmentArtifact(\'xlsx\')"><i class="bi bi-file-earmark-spreadsheet me-1"></i>Tải XLSX</button>' : ''}`
            : '';
        document.getElementById('db-inspector-actions').innerHTML = `${adjustmentButtons}${simulationButton}<button class="btn btn-outline-danger" onclick="window.dbManager.deleteRecord('${record._table}', ${record.id})"><i class="bi bi-trash3 me-1"></i>Xóa</button>${editButton}`;
    }

    renderRawJson() {
        const container = document.getElementById('db-raw-json');
        if (!container || container.childElementCount || !this.selectedRecord) return;
        container.innerHTML = '<div class="ops-loading"><span class="spinner-border spinner-border-sm"></span><span>Đang dựng JSON…</span></div>';
        setTimeout(() => {
            if (!container.isConnected) return;
            container.innerHTML = `<div class="drawer-section-title"><span>RAW JSON</span><button class="btn btn-sm btn-outline-secondary" onclick="window.dbManager.copyCurrentRecord()"><i class="bi bi-copy me-1"></i>Sao chép</button></div><pre class="json-inspector">${this.escapeHtml(JSON.stringify(this.selectedRecord, null, 2))}</pre>`;
        }, 0);
    }

    async downloadAdjustmentArtifact(format) {
        const data = this.selectedRecord?.data || {};
        const url = String(format === 'json' ? data.audit_json_url : (data.excel_report_url || data.report_file_url) || '');
        if (!url) {
            console.warn(`[DB Manager] Bản ghi #${this.selectedRecord?.id} không có URL cho file ${format.toUpperCase()}:`, data);
            window.toast?.warning?.(`Bản ghi này chưa có liên kết tải file ${format.toUpperCase()}.`);
            return;
        }
        const button = document.activeElement;
        const original = button?.innerHTML;
        // Normalize legacy /static/adjustments/ URLs to the authenticated API path.
        let downloadUrl = url;
        const legacyPrefix = '/static/adjustments/';
        if (downloadUrl.startsWith(legacyPrefix)) {
            const filename = downloadUrl.slice(legacyPrefix.length);
            const idMatch = filename.match(/^gnss_(?:binh_sai|adjustment)_(\d+)_/);
            if (idMatch) {
                downloadUrl = `/api/admin/gnss/adjustment/reports/${idMatch[1]}/${filename}`;
                console.info(`[DB Manager] Chuyển URL cũ → ${downloadUrl}`);
            }
        }
        try {
            if (button instanceof HTMLButtonElement) {
                button.disabled = true;
                button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Đang tải…';
            }
            await window.downloadAuthenticatedFile(downloadUrl, downloadUrl.split('/').pop());
        } catch (error) {
            console.error(`[DB Manager] Lỗi khi tải file ${format.toUpperCase()} (${url}):`, error);
            const reason = error?.message ? `: ${error.message}` : '';
            window.toast?.error?.(`Không tải được file ${format.toUpperCase()}${reason}`);
        } finally {
            if (button instanceof HTMLButtonElement) {
                button.disabled = false;
                button.innerHTML = original;
            }
        }
    }

    closeInspector() {
        document.getElementById('db-inspector')?.classList.remove('open');
        document.getElementById('db-inspector')?.setAttribute('aria-hidden', 'true');
        document.getElementById('db-inspector-backdrop')?.classList.remove('show');
    }

    async downloadSimulation(id) {
        try {
            const response = await fetch(`/api/simulations/runs/${id}/bundle`, { headers: { 'Authorization': `Bearer ${this.token}` } });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const href = URL.createObjectURL(await response.blob());
            const link = document.createElement('a');
            link.href = href;
            link.download = `simulation_${id}.zip`;
            link.click();
            setTimeout(() => URL.revokeObjectURL(href), 1000);
        } catch (error) {
            window.toast?.error('Không thể tải báo cáo mô phỏng');
        }
    }

    async copyCurrentRecord() {
        if (!this.selectedRecord) return;
        await navigator.clipboard.writeText(JSON.stringify(this.selectedRecord, null, 2));
        window.toast?.success('Đã sao chép JSON');
    }

    editRecord(table, id) {
        if (!['stations', 'devices'].includes(table)) return;
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
            this.closeInspector();
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
            const apiTable = table === 'gnss_adjustments' ? 'sensor-data' : table;
            const res = await fetch(`/api/admin/db/${apiTable}/${id}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) throw new Error(`HTTP ${res.status}`);

            window.toast?.success('✅ Đã xóa!');
            this.closeInspector();
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

        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        if (!modalEl.dataset.exportLifecycleBound) {
            modalEl.dataset.exportLifecycleBound = 'true';
            modalEl.addEventListener('shown.bs.modal', () => this.renderExportTaskState());
            modalEl.addEventListener('hidden.bs.modal', () => this.renderExportTaskState());
        }

        if (this.exportTaskId) {
            modal.show();
            this.renderExportTaskState();
            this.startExportPolling(this.exportTaskId);
            return;
        }

        const progressContainer = document.getElementById('export-progress-container');
        if (progressContainer) progressContainer.style.display = 'none';
        const startButton = document.getElementById('btn-export-start');
        const closeButton = document.getElementById('btn-export-cancel');
        if (startButton) startButton.disabled = false;
        if (closeButton) closeButton.disabled = false;
        
        // Nạp danh sách Project
        this.setExportSelectLoading('export-project-select', 'Đang tải danh sách dự án...');
        this.setExportSelectLoading('export-station-select', 'Chọn dự án để tải trạm...');
        
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

            let html = '<option value="all">-- Tất cả Dự án --</option>';
            this.exportProjects.forEach(p => {
                html += `<option value="${p.id}">${this.escapeHtml(p.project_code)} - ${this.escapeHtml(p.name || '')}</option>`;
            });
            select.innerHTML = html;
            select.disabled = false;

            await this.onExportProjectChange();
        } catch (e) {
            console.error('Error loading export projects:', e);
            select.innerHTML = '<option value="all">Không tải được danh sách dự án</option>';
            select.disabled = true;
            this.setExportSelectLoading('export-station-select', 'Không tải được danh sách trạm');
            this.setExportSelectLoading('export-cluster-select', 'Không tải được danh sách cụm');
            window.toast?.error('Không thể tải danh sách dự án/trạm để xuất dữ liệu');
        }
    }

    async onExportProjectChange() {
        const pSelect = document.getElementById('export-project-select');
        const sSelect = document.getElementById('export-station-select');
        const cSelect = document.getElementById('export-cluster-select');
        if (!pSelect || !sSelect || !cSelect) return;

        const projectId = pSelect.value;
        const requestSeq = ++this.exportStationRequestSeq;
        this.setExportSelectLoading('export-station-select', 'Đang tải danh sách trạm...');
        const project = this.exportProjects.find(p => String(p.id) === String(projectId));
        const clusters = Array.isArray(project?.gnss_clusters) ? project.gnss_clusters : [];
        cSelect.innerHTML = '<option value="all">-- Tất cả Cụm --</option>' + clusters.map((cluster, index) =>
            `<option value="${index}">${this.escapeHtml(cluster?.name || `Cụm ${index + 1}`)}</option>`
        ).join('');
        cSelect.disabled = !projectId || projectId === 'all' || clusters.length === 0;

        try {
            const stations = projectId && projectId !== 'all'
                ? await this.fetchJson(`/api/admin/projects/${projectId}/stations`)
                : await this.fetchJson('/api/admin/db/stations');

            if (requestSeq !== this.exportStationRequestSeq) return;

            this.exportStations = Array.isArray(stations) ? stations : [];
            let html = '<option value="all">-- Tất cả Trạm --</option>';
            this.exportStations.forEach(s => {
                html += `<option value="${s.id}">${this.escapeHtml(s.station_code)} - ${this.escapeHtml(s.name || s.station_name || '')}</option>`;
            });
            sSelect.innerHTML = html;
            sSelect.disabled = false;
        } catch (e) {
            console.error('Error loading export stations:', e);
            if (requestSeq !== this.exportStationRequestSeq) return;
            sSelect.innerHTML = '<option value="all">Không tải được danh sách trạm</option>';
            sSelect.disabled = true;
            window.toast?.error('Không thể tải danh sách trạm để xuất dữ liệu');
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
            if (document.getElementById('export-gnss-adjustments')?.checked) tables.push('gnss_adjustments');
            if (document.getElementById('export-alerts')?.checked) tables.push('alerts');
            if (document.getElementById('export-simulations')?.checked) tables.push('simulations');
            const uniqueTables = [...new Set(tables)];

            // Kiểm tra
            if (uniqueTables.length === 0) {
                window.toast?.warning('⚠️ Vui lòng chọn ít nhất 1 bảng dữ liệu!');
                return;
            }

            // Lấy các filters
            const projectId = document.getElementById('export-project-select')?.value;
            const stationId = document.getElementById('export-station-select')?.value;
            const clusterIndex = document.getElementById('export-cluster-select')?.value;
            const startDate = document.getElementById('export-start-date')?.value;
            const endDate = document.getElementById('export-end-date')?.value;
            
            const projectIds = projectId && projectId !== 'all' ? [parseInt(projectId)] : null;
            const stationIds = stationId && stationId !== 'all' ? [parseInt(stationId)] : null;
            const clusterIndices = clusterIndex && clusterIndex !== 'all' ? [parseInt(clusterIndex)] : null;
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
                cluster_indices: clusterIndices,
                sensor_types: sensorTypes,
                start_date: startDate || null,
                end_date: endDate || null
            };

            // Khóa UI
            document.getElementById('btn-export-start').disabled = true;
            document.getElementById('btn-export-cancel').disabled = false;
            const progressContainer = document.getElementById('export-progress-container');
            const progressBar = document.getElementById('export-progress-bar');
            const progressText = document.getElementById('export-status-text');
            const progressDetail = document.getElementById('export-progress-detail');
            
            progressContainer.style.display = 'block';
            progressBar.style.width = '5%';
            progressText.innerText = 'Đang khởi tạo tác vụ...';
            progressDetail.innerText = 'Có thể thu nhỏ cửa sổ; tác vụ vẫn chạy trên server.';

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
            this.exportTaskId = taskId;
            this.exportTaskState = { status: 'pending', percent: 5, message: 'Đang khởi tạo tác vụ...' };
            this.exportDownloadStarted = false;
            localStorage.setItem('activeDatabaseExportTaskId', taskId);
            this.renderExportTaskState();
            this.startExportPolling(taskId);

        } catch (e) {
            console.error('❌ Export error:', e);
            window.toast?.error('❌ Lỗi export: ' + e.message);
            const startButton = document.getElementById('btn-export-start');
            const closeButton = document.getElementById('btn-export-cancel');
            if (startButton) startButton.disabled = false;
            if (closeButton) closeButton.disabled = false;
        }
    }

    ensureExportTaskPill() {
        let pill = document.getElementById('database-export-task-pill');
        if (pill) return pill;
        pill = document.createElement('button');
        pill.id = 'database-export-task-pill';
        pill.type = 'button';
        pill.style.cssText = [
            'position:fixed', 'right:22px', 'bottom:76px', 'z-index:var(--z-popover)',
            'display:none', 'align-items:center', 'gap:10px', 'min-width:245px',
            'padding:11px 14px', 'border:1px solid rgba(66,201,155,.58)',
            'border-radius:13px', 'background:linear-gradient(135deg,#0b3028,#0d5b46)',
            'color:#effff9', 'box-shadow:0 16px 38px rgba(9,52,40,.32)',
            'font:600 12px monospace', 'cursor:pointer', 'text-align:left'
        ].join(';');
        pill.innerHTML = '<span class="export-pill-spinner" style="width:17px;height:17px;border:2px solid rgba(255,255,255,.28);border-top-color:#6ee7b7;border-radius:50%;animation:export-pill-spin .8s linear infinite"></span><span><strong class="export-pill-title" style="display:block">Đang export database</strong><small class="export-pill-detail" style="display:block;opacity:.72;margin-top:2px">Mở chi tiết</small></span>';
        if (!document.getElementById('database-export-pill-style')) {
            const style = document.createElement('style');
            style.id = 'database-export-pill-style';
            style.textContent = '@keyframes export-pill-spin{to{transform:rotate(360deg)}}';
            document.head.appendChild(style);
        }
        pill.addEventListener('click', () => this.exportToExcel());
        document.body.appendChild(pill);
        return pill;
    }

    renderExportTaskState() {
        const state = this.exportTaskState;
        const active = Boolean(this.exportTaskId && state);
        const modalEl = document.getElementById('exportExcelModal');
        const modalVisible = Boolean(modalEl?.classList.contains('show'));
        const pill = this.ensureExportTaskPill();
        pill.style.display = active && !modalVisible ? 'flex' : 'none';
        if (!active) return;

        const percent = Math.max(0, Math.min(100, Number(state.percent || 0)));
        const progressContainer = document.getElementById('export-progress-container');
        const progressBar = document.getElementById('export-progress-bar');
        const progressPercent = document.getElementById('export-progress-percent');
        const progressText = document.getElementById('export-status-text');
        const progressDetail = document.getElementById('export-progress-detail');
        const startButton = document.getElementById('btn-export-start');
        const failed = state.status === 'error' || state.status === 'failed';
        const completed = state.status === 'completed';
        const downloading = state.status === 'downloading';
        if (progressContainer) progressContainer.style.display = 'block';
        if (progressBar) {
            progressBar.style.width = `${percent}%`;
            progressBar.classList.toggle('progress-bar-animated', !failed && !completed);
            progressBar.style.background = failed ? '#dc5a5a' : '';
        }
        if (progressPercent) progressPercent.textContent = `${percent}%`;
        if (progressText) progressText.textContent = failed ? 'Export thất bại' : downloading ? 'Đang chuẩn bị tải xuống' : completed ? 'Export hoàn tất' : 'Đang export dữ liệu';
        if (progressDetail) progressDetail.textContent = state.error || state.message || 'Đang xử lý...';
        if (startButton) startButton.disabled = !failed && !completed;
        const pillTitle = pill.querySelector('.export-pill-title');
        const pillDetail = pill.querySelector('.export-pill-detail');
        const spinner = pill.querySelector('.export-pill-spinner');
        if (pillTitle) pillTitle.textContent = failed ? 'Export gặp lỗi' : downloading ? 'Đang chuẩn bị tải xuống' : completed ? 'Export hoàn tất' : `Đang export · ${percent}%`;
        if (pillDetail) pillDetail.textContent = state.error || state.message || 'Nhấn để mở chi tiết';
        if (spinner) spinner.style.animationPlayState = failed || completed ? 'paused' : 'running';
    }

    startExportPolling(taskId) {
        if (!taskId) return;
        if (this.exportPollTimer) clearInterval(this.exportPollTimer);
        const poll = async () => {
            try {
                const response = await fetch(`/api/admin/db/export-excel/${taskId}/progress`, {
                    headers: { 'Authorization': `Bearer ${this.token}` }
                });
                if (!response.ok) throw new Error(`Không đọc được tiến trình (HTTP ${response.status})`);
                this.exportTaskState = await response.json();
                this.renderExportTaskState();
                if (this.exportTaskState.status === 'completed') {
                    clearInterval(this.exportPollTimer);
                    this.exportPollTimer = null;
                    this.exportTaskState = {
                        ...this.exportTaskState,
                        status: 'downloading',
                        message: 'File đã tạo xong, đang chuẩn bị tải xuống...'
                    };
                    this.renderExportTaskState();
                    await this.downloadCompletedExport(taskId, this.exportTaskState);
                } else if (['error', 'failed'].includes(this.exportTaskState.status)) {
                    clearInterval(this.exportPollTimer);
                    this.exportPollTimer = null;
                    window.toast?.error('Export thất bại: ' + (this.exportTaskState.error || 'Không rõ lỗi'));
                }
            } catch (error) {
                console.error('Export polling error:', error);
                this.exportTaskState = { status: 'error', percent: 0, error: error.message };
                this.renderExportTaskState();
                clearInterval(this.exportPollTimer);
                this.exportPollTimer = null;
            }
        };
        poll();
        this.exportPollTimer = setInterval(poll, 1000);
    }

    async downloadCompletedExport(taskId, state) {
        if (this.exportDownloadStarted) return;
        this.exportDownloadStarted = true;
        try {
            const response = await fetch(`/api/admin/db/export-excel/${taskId}/download`, {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!response.ok) throw new Error('Không thể tải file ZIP');
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = state.filename || `landslide_backup_${Date.now()}.zip`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
            window.toast?.success('Đã hoàn tất và tải file export.', 5000);
            this.exportTaskId = null;
            this.exportTaskState = null;
            localStorage.removeItem('activeDatabaseExportTaskId');
            this.renderExportTaskState();
            const startButton = document.getElementById('btn-export-start');
            if (startButton) startButton.disabled = false;
        } catch (error) {
            this.exportDownloadStarted = false;
            this.exportTaskState = { ...state, status: 'error', error: error.message };
            this.renderExportTaskState();
            window.toast?.error(error.message);
        }
    }

    // =========================================================================
    // CLEAR DATABASE LOGIC
    // =========================================================================

    clearDatabase() {
        // Reset input and error UI if modal exists
        const input = document.getElementById('clear-db-confirm-input');
        const error = document.getElementById('clear-db-error');
        const submit = document.getElementById('clear-db-submit');

        if (input) input.value = '';
        if (error) error.style.display = 'none';
        if (submit) submit.disabled = true;
        document.querySelectorAll('#clearDatabaseModal .clear-db-option').forEach(option => option.classList.remove('is-selected'));

        if (input && input.dataset.validationBound !== 'true') {
            input.dataset.validationBound = 'true';
            input.addEventListener('input', () => this.syncClearDatabaseConfirmation());
        }

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

    syncClearDatabaseConfirmation() {
        const input = document.getElementById('clear-db-confirm-input');
        const submit = document.getElementById('clear-db-submit');
        const error = document.getElementById('clear-db-error');
        const value = input?.value.trim() || '';
        const valid = value === 'XOA DATA' || value === 'FACTORY RESET';
        if (submit) submit.disabled = !valid;
        if (error) error.style.display = 'none';
        input?.classList.toggle('is-valid', valid);
        input?.classList.toggle('is-invalid', value.length > 0 && !valid);
        document.querySelector('#clearDatabaseModal .is-data-only')?.classList.toggle('is-selected', value === 'XOA DATA');
        document.querySelector('#clearDatabaseModal .is-factory-reset')?.classList.toggle('is-selected', value === 'FACTORY RESET');
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
            const error = document.getElementById('clear-db-error');
            if (error) error.style.display = 'flex';
            input?.classList.add('is-invalid');
            input?.focus();
            return;
        }

        try {
            const submit = document.getElementById('clear-db-submit');
            if (submit) {
                submit.disabled = true;
                submit.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Đang xử lý';
            }
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
        } finally {
            const submit = document.getElementById('clear-db-submit');
            if (submit) submit.innerHTML = '<i class="bi bi-trash3 me-1" aria-hidden="true"></i> Xác nhận xóa';
            this.syncClearDatabaseConfirmation();
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
    const user = window.authManager?.getUserInfo?.() || window.authManager?.user;
    if (!user) {
        // Embedded/runtime contract tests and legacy shells may provide the
        // already-authenticated session adapter without loading auth.js. Keep
        // that compatibility path; the production shell always exposes
        // authManager and therefore remains capability-gated above.
        if (!window.authManager && window.authSession?.getToken?.()) {
            if (!window.dbManager) window.dbManager = new DatabaseManager();
            return;
        }
        window.addEventListener('auth:ready', bootstrapDatabaseManager, { once: true });
        return;
    }
    const permissions = user.permissions || [];
    if (user.role !== 'admin' && !permissions.includes('MANAGE_DATABASE')) {
        // Keep the destination locked but never instantiate a manager that
        // would issue forbidden filter/stats requests.
        return;
    }
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
