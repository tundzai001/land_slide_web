// =====================================================
// ADMIN MANAGER - COMPLETE VERSION WITH ALL FEATURES
// =====================================================

class AdminManager {
    constructor() {
        this.token = localStorage.getItem('token');
        
        // Navigation state
        this.currentView = 'projects';
        this.currentProjectId = null;
        this.navigationStack = [];
        
        // Wizard state
        this.currentStep = 1;
        this.totalSteps = 3;
        this.stationModal = null;
        this.velocityModal = null;
        this.isEditMode = false;
        this.currentStationId = null;
        
        // Data cache
        this.projectsData = null;
        this.stationsData = null;
        
        // Velocity classification (Cruden & Varnes)
        this.velocityConfig = [
            { name: 'Extremely slow', threshold: 0.00001, unit: 'mm/s', description: '< 16 mm/year', editable: true },
            { name: 'Very slow', threshold: 0.0005, unit: 'mm/s', description: '16 mm/year to 1.6 m/year', editable: true },
            { name: 'Slow', threshold: 0.05, unit: 'mm/s', description: '1.6 m/year to 13 mm/month', editable: true },
            { name: 'Moderate', threshold: 0.5, unit: 'mm/s', description: '13 mm/month to 1.8 m/hour', editable: true },
            { name: 'Rapid', threshold: 50, unit: 'mm/s', description: '1.8 m/hour to 3 m/min', editable: true },
            { name: 'Very rapid', threshold: 833, unit: 'mm/s', description: '3 m/min to 5 m/s', editable: true },
            { name: 'Extremely rapid', threshold: 5000, unit: 'mm/s', description: '> 5 m/s', editable: true }
        ];

        if (!this.token) {
            window.location.href = '/pages/login.html';
            return;
        }

        this.init();
    }

    init() {
        console.log('🚀 [ADMIN] Initializing...');
        
        // Initialize modals
        const stationModalEl = document.getElementById('stationConfigModal');
        if (stationModalEl) {
            this.stationModal = new bootstrap.Modal(stationModalEl);
        }
        
        const velocityModalEl = document.getElementById('velocityConfigModal');
        if (velocityModalEl) {
            this.velocityModal = new bootstrap.Modal(velocityModalEl);
        }

        // Setup sensor checkboxes
        ['gnss', 'rain', 'water', 'imu'].forEach(type => {
            const cb = document.getElementById(`edit-${type}`);
            if (cb) {
                cb.addEventListener('change', (e) => {
                    const section = document.getElementById(`mqtt-${type}-section`);
                    if (section) section.style.display = e.target.checked ? 'block' : 'none';
                    
                    const anyChecked = ['gnss', 'rain', 'water', 'imu'].some(t => 
                        document.getElementById(`edit-${t}`)?.checked
                    );
                    const emptyState = document.getElementById('mqtt-empty-state');
                    if (emptyState) emptyState.style.display = anyChecked ? 'none' : 'block';
                });
            }
        });
        
        this.loadUsers();
        this.setupTabHandlers();
        this.setupLogout();

        console.log('✅ [ADMIN] Initialized successfully');
    }

    setupTabHandlers() {
        const tabButtons = document.querySelectorAll('#mainTabs button[data-bs-toggle="tab"]');
        tabButtons.forEach(btn => {
            btn.addEventListener('shown.bs.tab', (e) => {
                const targetId = e.target.getAttribute('data-bs-target');
                if (targetId === '#tab-projects') {
                    this.resetNavigation();
                    this.loadProjects();
                }
            });
        });
    }

    setupLogout() {
        const logoutBtn = document.getElementById('logout-btn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this.logout();
            });
        }
    }

    // =========================================================================
    // NAVIGATION SYSTEM
    // =========================================================================
    
    resetNavigation() {
        this.currentView = 'projects';
        this.currentProjectId = null;
        this.navigationStack = [];
        this.updateBreadcrumb();
        this.updateBackButton();
    }

    navigateBack() {
        if (this.navigationStack.length === 0) return;
        
        this.navigationStack.pop();
        
        this.resetNavigation();
        this.loadProjects();
        
        this.updateBreadcrumb();
        this.updateBackButton();
    }

    updateBreadcrumb() {
        const breadcrumb = document.getElementById('project-breadcrumb');
        if (!breadcrumb) return;

        let html = '<li class="breadcrumb-item"><a href="#" onclick="window.adminManager.resetNavigation(); window.adminManager.loadProjects();">Dự án</a></li>';
        
        if (this.currentView === 'stations') {
            const projectName = this.getProjectName(this.currentProjectId);
            html += `<li class="breadcrumb-item active">${projectName}</li>`;
        }
        
        breadcrumb.innerHTML = html;
    }

    updateBackButton() {
        const backBtn = document.getElementById('btn-back-nav');
        if (backBtn) {
            backBtn.style.display = this.navigationStack.length > 0 ? 'inline-block' : 'none';
        }
    }

    getProjectName(projectId) {
        const project = this.projectsData?.find(p => p.id === projectId);
        return project?.name || 'Dự án';
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
                this.logout();
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
        
        if (title) title.textContent = 'Danh sách Dự án';
        if (actionButtons) {
            actionButtons.innerHTML = `
                <button class="btn btn-gradient" onclick="window.adminManager.openCreateProjectModal()">
                    <i class="bi bi-plus-circle me-2"></i>Tạo Dự án
                </button>
            `;
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

        container.innerHTML = `
            <div class="row g-3">
                ${this.projectsData.map(p => `
                    <div class="col-md-6 col-xl-4">
                        <div class="card hover-lift" style="cursor: pointer;" onclick="window.adminManager.loadStations(${p.id})">
                            <div class="card-body">
                                <div class="d-flex justify-content-between align-items-start mb-3">
                                    <div>
                                        <h5 class="card-title mb-1">
                                            <i class="bi bi-folder-fill text-primary me-2"></i>
                                            ${p.name}
                                        </h5>
                                        <small class="text-muted">${p.project_code}</small>
                                    </div>
                                    <span class="badge bg-primary">${p.station_count || 0} trạm</span>
                                </div>
                                ${p.description ? `<p class="text-muted small mb-0">${p.description}</p>` : ''}
                                ${p.location ? `<p class="text-muted small mb-0 mt-2"><i class="bi bi-geo-alt"></i> ${p.location}</p>` : ''}
                            </div>
                            <div class="card-footer bg-transparent border-top-0">
                                <div class="d-flex gap-2">
                                    <button class="btn btn-sm btn-outline-primary flex-1" onclick="event.stopPropagation(); window.adminManager.loadStations(${p.id})">
                                        <i class="bi bi-box-arrow-in-right me-1"></i> Xem trạm
                                    </button>
                                    <button class="btn btn-sm btn-outline-danger" onclick="event.stopPropagation(); window.adminManager.deleteProject(${p.id})">
                                        <i class="bi bi-trash"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    }

    openCreateProjectModal() {
        const modal = new bootstrap.Modal(document.getElementById('createProjectModal'));
        modal.show();
    }

    async createProject() {
        const code = document.getElementById('project-code').value.trim();
        const name = document.getElementById('project-name').value.trim();
        const desc = document.getElementById('project-desc').value.trim();
        const location = document.getElementById('project-location').value.trim();
        
        if (!code || !name) {
            window.toast?.warning('Vui lòng nhập đầy đủ thông tin');
            return;
        }
        
        try {
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
                    location: location
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
            this.loadProjects();
            
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
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
            this.loadProjects();
            
        } catch (e) {
            window.toast?.error('❌ Lỗi xóa dự án');
        }
    }

    // =========================================================================
    // STATIONS MANAGEMENT
    // =========================================================================
    
    async loadStations(projectId) {
        try {
            if (this.currentView === 'projects') {
                this.navigationStack.push({ view: 'projects' });
            }
            
            this.currentView = 'stations';
            this.currentProjectId = projectId;
            
            const res = await fetch(`/api/admin/projects/${projectId}/stations`, {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) throw new Error('Failed to load stations');

            this.stationsData = await res.json();
            this.renderStations();
            this.updateBreadcrumb();
            this.updateBackButton();
            
        } catch (e) {
            console.error('Error loading stations:', e);
            window.toast?.error('Không thể tải danh sách trạm');
        }
    }

    renderStations() {
        const container = document.getElementById('projects-content-area');
        const title = document.getElementById('current-view-title');
        const actionButtons = document.getElementById('action-buttons-container');
        
        const projectName = this.getProjectName(this.currentProjectId);
        
        if (title) title.textContent = `Trạm trong "${projectName}"`;
        if (actionButtons) {
            actionButtons.innerHTML = `
                <button class="btn btn-gradient" onclick="window.adminManager.openAddStationModal()">
                    <i class="bi bi-plus-circle me-2"></i>Thêm Trạm
                </button>
            `;
        }

        if (!this.stationsData || this.stationsData.length === 0) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="bi bi-hdd-network fs-1 text-muted"></i>
                    <p class="text-muted mt-2">Chưa có trạm nào</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="row g-3">
                ${this.stationsData.map(s => `
                    <div class="col-md-6">
                        <div class="card hover-lift">
                            <div class="card-body">
                                <div class="d-flex justify-content-between align-items-start mb-2">
                                    <div>
                                        <h6 class="mb-1">
                                            <i class="bi bi-broadcast-pin text-success me-2"></i>
                                            ${s.name}
                                        </h6>
                                        <small class="text-muted">${s.station_code}</small>
                                    </div>
                                    <span class="badge bg-${s.status === 'online' ? 'success' : 'secondary'}">
                                        ${s.status || 'offline'}
                                    </span>
                                </div>
                                ${s.location ? `
                                    <div class="text-muted small mb-2">
                                        <i class="bi bi-geo-alt me-1"></i>
                                        Lat: ${s.location.lat?.toFixed(6)}, Lon: ${s.location.lon?.toFixed(6)}
                                    </div>
                                ` : ''}
                            </div>
                            <div class="card-footer bg-transparent border-top-0">
                                <div class="d-flex gap-2">
                                    <button class="btn btn-sm btn-outline-primary flex-1" onclick="window.adminManager.editStation(${s.id})">
                                        <i class="bi bi-pencil me-1"></i> Cấu hình
                                    </button>
                                    <button class="btn btn-sm btn-outline-danger" onclick="window.adminManager.deleteStation(${s.id})">
                                        <i class="bi bi-trash"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    }

    // =========================================================================
    // STATION WIZARD
    // =========================================================================
    
    openAddStationModal() {
        this.isEditMode = false;
        this.currentStationId = null;
        this.currentStep = 1;
        
        document.getElementById('stationConfigForm').reset();
        document.getElementById('edit-station-id').value = '';
        document.getElementById('origin-lat').value = '';
        document.getElementById('origin-lon').value = '';
        document.getElementById('origin-h').value = '';
        document.getElementById('origin-status').textContent = 'Chưa có tọa độ gốc';
        document.getElementById('edit-project-id').value = this.currentProjectId;
        document.getElementById('modal-title').textContent = 'Thêm Trạm Mới';
        
        ['gnss', 'rain', 'water', 'imu'].forEach(sensor => {
            const checkbox = document.getElementById(`edit-${sensor}`);
            if (checkbox) checkbox.checked = false;
            const section = document.getElementById(`mqtt-${sensor}-section`);
            if (section) section.style.display = 'none';
        });
        
        document.getElementById('mqtt-empty-state').style.display = 'block';
        document.getElementById('btn-delete-station').style.display = 'none';
        
        this.updateWizardStep();
        if (this.stationModal) this.stationModal.show();
    }

    async editStation(stationId) {
        try {
            this.isEditMode = true;
            this.currentStationId = stationId;
            this.currentStep = 1;

            window.toast?.info('Đang tải dữ liệu trạm...');

            const [resConfig, resDevices] = await Promise.all([
                fetch(`/api/admin/stations/${stationId}/config`, {
                    headers: { 'Authorization': `Bearer ${this.token}` }
                }),
                fetch(`/api/admin/stations/${stationId}/devices`, {
                    headers: { 'Authorization': `Bearer ${this.token}` }
                })
            ]);

            if (!resConfig.ok || !resDevices.ok) throw new Error('Không thể tải dữ liệu');

            const stationData = await resConfig.json();
            const devices = await resDevices.json();

            // STEP 1: Basic info
            document.getElementById('edit-station-id').value = stationId;
            document.getElementById('edit-project-id').value = this.currentProjectId;
            document.getElementById('edit-code').value = stationData.station_code || '';
            document.getElementById('edit-name').value = stationData.name || '';

            // STEP 2: Sensors & MQTT
            const sensorTypes = ['gnss', 'rain', 'water', 'imu'];
            sensorTypes.forEach(type => {
                const checkbox = document.getElementById(`edit-${type}`);
                const section = document.getElementById(`mqtt-${type}-section`);
                const input = document.getElementById(`topic-${type}`);
                
                if (checkbox) checkbox.checked = false;
                if (section) section.style.display = 'none';
                if (input) input.value = '';
            });

            if (Array.isArray(devices)) {
                devices.forEach(dev => {
                    const type = dev.device_type;
                    const checkbox = document.getElementById(`edit-${type}`);
                    const section = document.getElementById(`mqtt-${type}-section`);
                    const input = document.getElementById(`topic-${type}`);

                    if (checkbox) {
                        checkbox.checked = true;
                        if (section) section.style.display = 'block';
                        if (input) input.value = dev.mqtt_topic || '';
                    }
                });
                
                const emptyState = document.getElementById('mqtt-empty-state');
                if (emptyState) emptyState.style.display = devices.length > 0 ? 'none' : 'block';
            }

            // STEP 3: Thresholds
            const cfg = stationData.config || {};
            
            const waterCfg = cfg.Water || {};
            document.getElementById('cfg-water-warning').value = waterCfg.warning_threshold ?? 0.15;
            document.getElementById('cfg-water-critical').value = waterCfg.critical_threshold ?? 0.30;

            const rainCfg = cfg.RainAlerting || {};
            document.getElementById('cfg-rain-watch').value = rainCfg.rain_intensity_watch_threshold ?? 10.0;
            document.getElementById('cfg-rain-warning').value = rainCfg.rain_intensity_warning_threshold ?? 25.0;
            document.getElementById('cfg-rain-critical').value = rainCfg.rain_intensity_critical_threshold ?? 50.0;

            const gnssCfg = cfg.GnssAlerting || {};
            document.getElementById('cfg-gnss-hdop').value = gnssCfg.gnss_max_hdop ?? 4.0;
            document.getElementById('cfg-gnss-steps').value = gnssCfg.gnss_confirm_steps ?? 3;
            document.getElementById('cfg-gnss-streak').value = gnssCfg.gnss_safe_streak ?? 10;
            document.getElementById('cfg-gnss-timeout').value = gnssCfg.gnss_degraded_timeout ?? 300;

            const imuCfg = cfg.ImuAlerting || {};
            document.getElementById('cfg-imu-shock').value = imuCfg.shock_threshold_ms2 ?? 5.0;

            const gnssOrigin = cfg.gnss_origin || {};
            if (gnssOrigin.lat) {
                document.getElementById('origin-lat').value = gnssOrigin.lat;
                document.getElementById('origin-lon').value = gnssOrigin.lon;
                document.getElementById('origin-h').value = gnssOrigin.h || 0;
                document.getElementById('origin-status').innerHTML = '<span class="text-success">✅ Đã có tọa độ gốc</span>';
            } else {
                document.getElementById('origin-lat').value = '';
                document.getElementById('origin-lon').value = '';
                document.getElementById('origin-h').value = '';
                document.getElementById('origin-status').textContent = 'Chưa thiết lập';
            }

            document.getElementById('modal-title').textContent = `Chỉnh sửa: ${stationData.name}`;
            document.getElementById('btn-delete-station').style.display = 'inline-block';
            
            this.updateWizardStep();
            if (this.stationModal) this.stationModal.show();

        } catch (e) {
            console.error('❌ Error in editStation:', e);
            window.toast?.error('Lỗi: ' + e.message);
        }
    }

    updateWizardStep() {
        document.querySelectorAll('.wizard-step').forEach(step => {
            const stepNum = parseInt(step.dataset.step);
            step.classList.toggle('active', stepNum === this.currentStep);
        });
        
        document.querySelectorAll('.wizard-content').forEach(content => {
            const stepNum = parseInt(content.dataset.step);
            content.classList.toggle('active', stepNum === this.currentStep);
        });
        
        const btnBack = document.getElementById('btn-wizard-back');
        const btnNext = document.getElementById('btn-wizard-next');
        const btnSave = document.getElementById('btn-wizard-save');
        
        if (btnBack) btnBack.style.display = this.currentStep > 1 ? 'inline-block' : 'none';
        if (btnNext) btnNext.style.display = this.currentStep < this.totalSteps ? 'inline-block' : 'none';
        if (btnSave) btnSave.style.display = this.currentStep === this.totalSteps ? 'inline-block' : 'none';
    }

    wizardNext() {
        if (this.currentStep < this.totalSteps) {
            this.currentStep++;
            this.updateWizardStep();
        }
    }

    wizardPrev() {
        if (this.currentStep > 1) {
            this.currentStep--;
            this.updateWizardStep();
        }
    }

    async saveStation() {
        const code = document.getElementById('edit-code').value.trim();
        const name = document.getElementById('edit-name').value.trim();
        const projectId = document.getElementById('edit-project-id').value;
        
        if (!code || !name) {
            window.toast?.warning('Vui lòng nhập mã trạm và tên trạm');
            return;
        }
        
        const sensors = {};
        ['gnss', 'rain', 'water', 'imu'].forEach(type => {
            const checkbox = document.getElementById(`edit-${type}`);
            if (checkbox && checkbox.checked) {
                const topic = document.getElementById(`topic-${type}`)?.value.trim();
                if (topic) {
                    sensors[type] = { topic: topic };
                    
                    if (type === 'gnss') {
                        const lat = document.getElementById('origin-lat').value;
                        const lon = document.getElementById('origin-lon').value;
                        const h = document.getElementById('origin-h').value;
                        
                        if (lat && lon) {
                            sensors[type].lat = parseFloat(lat);
                            sensors[type].lon = parseFloat(lon);
                            sensors[type].h = parseFloat(h) || 0;
                        }
                    }
                }
            }
        });

        const config = {
            Water: {
                warning_threshold: parseFloat(document.getElementById('cfg-water-warning').value),
                critical_threshold: parseFloat(document.getElementById('cfg-water-critical').value)
            },
            RainAlerting: {
                rain_intensity_watch_threshold: parseFloat(document.getElementById('cfg-rain-watch').value),
                rain_intensity_warning_threshold: parseFloat(document.getElementById('cfg-rain-warning').value),
                rain_intensity_critical_threshold: parseFloat(document.getElementById('cfg-rain-critical').value)
            },
            GnssAlerting: {
                gnss_max_hdop: parseFloat(document.getElementById('cfg-gnss-hdop').value) || 4.0,
                gnss_confirm_steps: parseInt(document.getElementById('cfg-gnss-steps').value) || 3,
                gnss_safe_streak: parseInt(document.getElementById('cfg-gnss-streak').value) || 10,
                gnss_degraded_timeout: parseInt(document.getElementById('cfg-gnss-timeout').value) || 300
            },
            ImuAlerting: {
                shock_threshold_ms2: parseFloat(document.getElementById('cfg-imu-shock').value) || 5.0
            },
            gnss_origin: {
                lat: document.getElementById('origin-lat').value,
                lon: document.getElementById('origin-lon').value,
                h: document.getElementById('origin-h').value
            },
            velocity_classification: this.velocityConfig
        };

        const payload = {
            station_code: code,
            name: name,
            sensors: sensors,
            config: config,
            location: null
        };

        try {
            let url = this.isEditMode 
                ? `/api/admin/stations/${this.currentStationId}/config`
                : `/api/admin/projects/${projectId}/stations`;
            
            let method = this.isEditMode ? 'PUT' : 'POST';

            const res = await fetch(url, {
                method: method,
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (!res.ok) throw new Error('Lỗi lưu trạm');

            window.toast?.success('✅ Lưu thành công!');
            this.stationModal.hide();
            this.loadStations(projectId);
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

    async deleteStation(stationId) {
        if (!confirm('Bạn có chắc muốn xóa trạm này?')) return;
        
        try {
            const res = await fetch(`/api/admin/stations/${stationId}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            
            if (!res.ok) throw new Error('Failed');
            
            window.toast?.success('✅ Xóa trạm thành công!');
            
            if (this.stationModal) this.stationModal.hide();
            this.loadStations(this.currentProjectId);
            
        } catch (e) {
            window.toast?.error('❌ Lỗi xóa trạm');
        }
    }

    // =========================================================================
    // VELOCITY CONFIG MODAL
    // =========================================================================
    
    openVelocityModal() {
        console.log('📊 [VELOCITY] Opening modal...');
        this.renderVelocityTable();
        if (this.velocityModal) this.velocityModal.show();
    }

    closeVelocityModal() {
        if (this.velocityModal) this.velocityModal.hide();
    }

    renderVelocityTable() {
        const tbody = document.getElementById('velocity-table-body');
        if (!tbody) return;

        tbody.innerHTML = this.velocityConfig.map((vel, index) => `
            <tr>
                <td><strong>${vel.name}</strong></td>
                <td>
                    ${vel.editable ? `
                        <div class="input-group input-group-sm">
                            <input type="number" 
                                   class="form-control" 
                                   value="${vel.threshold}" 
                                   step="0.00001"
                                   data-index="${index}"
                                   onchange="window.adminManager.updateVelocityThreshold(${index}, this.value)">
                            <span class="input-group-text">${vel.unit}</span>
                        </div>
                    ` : `<code>${vel.threshold} ${vel.unit}</code>`}
                </td>
                <td class="text-muted small">${vel.description}</td>
            </tr>
        `).join('');
    }

    updateVelocityThreshold(index, newValue) {
        const value = parseFloat(newValue);
        if (!isNaN(value)) {
            this.velocityConfig[index].threshold = value;
        }
    }

    applyVelocityConfig() {
        
        console.log('✅ [VELOCITY] Applied config:', this.velocityConfig);
        
        // Thông báo cho người dùng biết
        window.toast?.success('✅ Đã áp dụng bảng vận tốc. Hãy bấm "Lưu cấu hình" để lưu trạm.');
        
        // Đóng modal
        this.closeVelocityModal();
    }

    resetVelocityConfig() {
        // Khôi phục về mặc định Cruden & Varnes nếu cần
        this.velocityConfig = [
            { name: 'Extremely slow', threshold: 0.00001, unit: 'mm/s', description: '< 16 mm/year', editable: true },
            { name: 'Very slow', threshold: 0.0005, unit: 'mm/s', description: '16 mm/year to 1.6 m/year', editable: true },
            { name: 'Slow', threshold: 0.05, unit: 'mm/s', description: '1.6 m/year to 13 mm/month', editable: true },
            { name: 'Moderate', threshold: 0.5, unit: 'mm/s', description: '13 mm/month to 1.8 m/hour', editable: true },
            { name: 'Rapid', threshold: 50, unit: 'mm/s', description: '1.8 m/hour to 3 m/min', editable: true },
            { name: 'Very rapid', threshold: 833, unit: 'mm/s', description: '3 m/min to 5 m/s', editable: true },
            { name: 'Extremely rapid', threshold: 5000, unit: 'mm/s', description: '> 5 m/s', editable: true }
        ];
        this.renderVelocityTable();
        window.toast?.info('Đã khôi phục cấu hình vận tốc mặc định');
    }


    // =========================================================================
    // FETCH ORIGIN COORDINATES (LIVE FROM DEVICE)
    // =========================================================================
    
    async fetchLatestOrigin() {
        const topic = document.getElementById('topic-gnss')?.value.trim();
        if (!topic) {
            window.toast?.warning('Vui lòng nhập MQTT Topic của GNSS trước');
            return;
        }
        
        const statusEl = document.getElementById('origin-status');
        const btnEl = document.getElementById('btn-fetch-origin');
        
        statusEl.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Đang kết nối thiết bị...';
        if (btnEl) btnEl.disabled = true;
        
        try {
            // Gọi API backend để subscribe tạm thời vào topic và lấy message mới nhất
            const res = await fetch('/api/admin/gnss/fetch-live-origin', {
                method: 'POST',
                headers: { 
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json' 
                },
                body: JSON.stringify({ topic: topic })
            });
            
            const result = await res.json();
            
            if (res.ok) {
                // Điền tọa độ nhận được vào form
                document.getElementById('origin-lat').value = result.lat;
                document.getElementById('origin-lon').value = result.lon;
                document.getElementById('origin-h').value = result.h;
                
                statusEl.innerHTML = `<span class="text-success">✅ Đã nhận: Sats ${result.num_sats}, Fix ${result.fix_quality}</span>`;
                window.toast?.success('Đã lấy tọa độ thực từ thiết bị!');
            } else {
                throw new Error(result.detail || 'Timeout hoặc thiết bị offline');
            }
        } catch (e) {
            console.error(e);
            statusEl.innerHTML = `<span class="text-danger">❌ Lỗi: ${e.message}</span>`;
            window.toast?.error('Không lấy được tọa độ. Kiểm tra lại Topic hoặc thiết bị.');
        } finally {
            if (btnEl) btnEl.disabled = false;
        }
    }

    // =========================================================================
    // USER MANAGEMENT (MISSING IN YOUR EDIT)
    // =========================================================================
    
    async loadUsers() {
        try {
            const res = await fetch('/api/admin/users', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (res.status === 401) {
                this.logout();
                return;
            }

            if (!res.ok) throw new Error('Failed to load users');

            const users = await res.json();
            this.renderUsers(users);
        } catch (e) {
            console.error('Error loading users:', e);
            // Silent fail or toast
        }
    }

    renderUsers(users) {
        const tbody = document.getElementById('user-table-body');
        if (!tbody) return;

        if (!users || users.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">Chưa có người dùng</td></tr>`;
            return;
        }

        tbody.innerHTML = users.map(u => `
            <tr>
                <td>${u.id}</td>
                <td><strong>${u.username}</strong></td>
                <td>${u.full_name || '--'}</td>
                <td><span class="badge bg-${u.role === 'admin' ? 'danger' : 'info'}">${u.role}</span></td>
                <td><span class="badge bg-${u.is_active ? 'success' : 'secondary'}">${u.is_active ? 'Active' : 'Locked'}</span></td>
                <td>
                    <button class="btn btn-sm btn-outline-danger" onclick="window.adminManager.deleteUser(${u.id}, '${u.username}')">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>
        `).join('');
    }

    async createUser() {
        const username = document.getElementById('new-username').value.trim();
        const password = document.getElementById('new-password').value;
        const fullname = document.getElementById('new-fullname').value.trim();
        const role = document.getElementById('new-role').value;

        if (!username || !password) {
            window.toast?.warning('Thiếu tài khoản hoặc mật khẩu');
            return;
        }

        try {
            const res = await fetch('/api/admin/users', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ username, password, full_name: fullname, role })
            });

            if (res.ok) {
                window.toast?.success('✅ Tạo tài khoản thành công');
                bootstrap.Modal.getInstance(document.getElementById('addUserModal'))?.hide();
                document.getElementById('addUserForm').reset();
                this.loadUsers();
            } else {
                throw new Error((await res.json()).detail || 'Lỗi tạo user');
            }
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

    async deleteUser(userId, username) {
        if (!confirm(`Xóa người dùng ${username}?`)) return;
        try {
            const res = await fetch(`/api/admin/users/${userId}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (res.ok) {
                window.toast?.success('Đã xóa người dùng');
                this.loadUsers();
            } else {
                throw new Error('Lỗi xóa');
            }
        } catch (e) {
            window.toast?.error(e.message);
        }
    }

    logout() {
        localStorage.removeItem('token');
        window.location.href = '/';
    }
}

// =========================================================================
// INITIALIZATION
// =========================================================================
document.addEventListener('DOMContentLoaded', () => {
    // Đảm bảo các modal và components đã load xong
    if(document.getElementById('projects-content-area')) {
        window.adminManager = new AdminManager();
    } else {
        console.error('❌ Admin Dashboard DOM element missing');
    }
});