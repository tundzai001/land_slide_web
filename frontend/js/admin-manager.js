// =====================================================
// ADMIN MANAGER - COMPLETE VERSION WITH ALL FEATURES
// =====================================================

class AdminManager {
    constructor() {
        this.token = localStorage.getItem('token') || sessionStorage.getItem('token');

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
        this.currentStationConfig = {};
        this.stationPresetConfirm = null;

        // Data cache
        this.projectsData = null;
        this.stationsData = null;

        // Velocity classification (Cruden & Varnes)
        this.velocityConfig = [
            { name: 'Extremely slow', threshold: 0, unit: 'mm/year', description: '< 16 mm/year', editable: true },
            { name: 'Very slow', threshold: 16, unit: 'mm/year', description: '16 mm/year to 1.6 m/year', editable: true },
            { name: 'Slow', threshold: 1.6, unit: 'm/year', description: '1.6 m/year to 13 mm/month', editable: true },
            { name: 'Moderate', threshold: 13, unit: 'm/month', description: '13 mm/month to 1.8 m/hour', editable: true },
            { name: 'Rapid', threshold: 1.8, unit: 'm/hr', description: '1.8 m/hour to 3 m/min', editable: true },
            { name: 'Very rapid', threshold: 3, unit: 'm/min', description: '3 m/min to 5 m/s', editable: true },
            { name: 'Extremely rapid', threshold: 5, unit: 'm/s', description: '> 5 m/s', editable: true }
        ];

        // ✅ Default offline thresholds (seconds)
        this.defaultOfflineThresholds = {
            gnss: 30,
            rain: 60,
            water: 60,
            imu: 2400
        };

        if (!this.token) {
            window.location.href = '/pages/login.html';
            return;
        }

        this.init();
    }

    /** Switch visible tab pane (called from sidebar icons) */
    switchTab(tabId, linkEl) {
        // Hide all tab panes
        document.querySelectorAll('#admin-tab-content > .tab-pane').forEach(p => {
            p.classList.remove('show', 'active');
        });
        // Show target pane
        const target = document.getElementById(tabId);
        if (target) {
            target.classList.add('show', 'active');
        }
        // Update sidebar active state
        document.querySelectorAll('.admin-sidebar .nav-link').forEach(l => l.classList.remove('active'));
        if (linkEl) linkEl.classList.add('active');

        // Trigger data loading for specific tabs
        if (tabId === 'tab-projects') {
            this.resetNavigation?.();
            this.loadProjects?.();
        } else if (tabId === 'tab-database') {
            window.dbManager?.loadAllData?.();
        } else if (tabId === 'tab-pi') {
            this.loadPiDevices?.();
        }
    }

    init() {
        console.log('[ADMIN] Initializing...');

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

        // Load projects first so project names are available for user rendering
        this.loadProjects().then(() => this.loadUsers());
        this.setupTabHandlers();
        this.setupLogout();
        this.setupOfflineThresholdListeners();

        // Load project list for Add User modal
        const addUserModal = document.getElementById('addUserModal');
        if (addUserModal) {
            addUserModal.addEventListener('show.bs.modal', () => {
                this.loadProjectsForModal();
            });
        }

        // Fetch current user role and apply restrictions
        this.fetchCurrentUserRole();

        // ✅ Auto-refresh Pi Devices tab every 15s to see online status quickly
        setInterval(() => {
            const piTab = document.getElementById('tab-pi');
            if (piTab && piTab.classList.contains('active')) {
                this.loadPiDevices(true);
            }
        }, 15000);

        console.log('✅ [ADMIN] Initialized successfully');
    }

    /** Fetch current user role from API and apply role-based restrictions */
    async fetchCurrentUserRole() {
        try {
            const res = await fetch('/api/auth/me', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) return;
            const user = await res.json();
            this.currentUserRole = user.role;
            this.currentUserAssignedProjects = user.assigned_projects || [];

            console.log(`[ADMIN] User role: ${user.role}, assigned projects: ${JSON.stringify(this.currentUserAssignedProjects)}`);

            if (user.role === 'viewer') {
                this.applyViewerRestrictions();
            } else if (user.role === 'operator') {
                this.applyOperatorRestrictions();
            }
        } catch (e) {
            console.error('Error fetching user role:', e);
        }
    }

    /** Apply operator restrictions — hide Users/DB/System tabs, but allow editing stations in assigned projects */
    applyOperatorRestrictions() {
        console.log('🔧 Applying operator restrictions');

        // Hide sidebar tabs: Users, Database, System (keep Projects and Pi Devices)
        document.querySelectorAll('.admin-sidebar .nav-item').forEach(item => {
            const link = item.querySelector('[data-tab]');
            if (link) {
                const tab = link.getAttribute('data-tab');
                if (['tab-users', 'tab-database', 'tab-system'].includes(tab)) {
                    item.style.display = 'none';
                }
            }
        });

        // Hide "Tạo Dự án" button (operator can't create new projects)
        const createProjBtn = document.querySelector('#action-buttons-container');
        if (createProjBtn) createProjBtn.style.display = 'none';

        // Hide Pi summary cards (admin-level info)
        const summaryCards = document.getElementById('pi-summary-cards');
        if (summaryCards) summaryCards.style.display = 'none';

        // Hide Chọn (select) toggle button
        const selectToggle = document.getElementById('pi-select-toggle');
        if (selectToggle) selectToggle.style.display = 'none';

        // Switch to projects tab by default
        const projLink = document.querySelector('[data-tab="tab-projects"]');
        if (projLink) this.switchTab('tab-projects', projLink);

        // Note: Operators CAN edit station config for their assigned projects
        // The backend already filters projects by assigned_projects
    }

    // ✅ THÊM HÀM MỚI: Setup listeners cho offline threshold inputs
    setupOfflineThresholdListeners() {
        const timeoutInputs = [
            { id: 'offline-gnss', display: 'offline-gnss-display' },
            { id: 'offline-rain', display: 'offline-rain-display' },
            { id: 'offline-water', display: 'offline-water-display' },
            { id: 'offline-imu', display: 'offline-imu-display' }
        ];

        timeoutInputs.forEach(({ id, display }) => {
            const input = document.getElementById(id);
            const displayEl = document.getElementById(display);

            if (input && displayEl) {
                input.addEventListener('input', function () {
                    const seconds = parseInt(this.value) || 0;
                    displayEl.textContent = window.adminManager.formatOfflineTime(seconds);
                });
            }
        });
    }

    // ✅ THÊM HÀM MỚI: Format thời gian offline
    formatOfflineTime(seconds) {
        if (seconds < 60) return `${seconds} giây`;
        if (seconds < 3600) {
            const minutes = Math.floor(seconds / 60);
            const secs = seconds % 60;
            return secs > 0 ? `${minutes} phút ${secs} giây` : `${minutes} phút`;
        }
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return minutes > 0 ? `${hours} giờ ${minutes} phút` : `${hours} giờ`;
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
                        <div class="card hover-lift project-card" style="cursor: pointer;" onclick="window.adminManager.loadStations(${p.id})">
                            <div class="card-body position-relative" style="z-index: 2;">
                                <div class="d-flex justify-content-between align-items-start mb-3">
                                    <div>
                                        <h5 class="card-title mb-1 neon-text">
                                            <i class="bi bi-folder-fill me-2"></i>
                                            ${p.name}
                                        </h5>
                                        <small class="text-muted font-monospace">${p.project_code}</small>
                                    </div>
                                    <span class="badge bg-primary bg-opacity-10 text-primary border border-primary">${p.station_count || 0} STATION</span>
                                </div>
                                ${p.description ? `<p class="text-muted small mb-0">${p.description}</p>` : ''}
                                ${p.location ? `<p class="text-muted small mb-0 mt-2"><i class="bi bi-geo-alt"></i> ${p.location}</p>` : ''}
                                
                            </div>
                            <div class="card-footer bg-transparent border-top-0 position-relative" style="z-index: 2;">
                                <div class="d-flex gap-2">
                                    <button class="btn btn-sm btn-outline-primary flex-1" onclick="event.stopPropagation(); window.adminManager.loadStations(${p.id})">
                                        <i class="bi bi-box-arrow-in-right me-1"></i> ACCESS
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
                        <div class="card hover-lift station-card">
                            <div class="card-body position-relative" style="z-index: 2;">
                                <div class="d-flex justify-content-between align-items-start mb-2">
                                    <div>
                                        <h6 class="mb-1 fw-bold neon-text" style="color: var(--accent-${s.status === 'online' ? 'success' : 'secondary'})">
                                            <i class="bi bi-broadcast-pin me-2"></i>
                                            ${s.name}
                                        </h6>
                                        <small class="text-muted font-monospace">${s.station_code}</small>
                                    </div>
                                    <div class="d-flex align-items-center gap-2">
                                        <span class="status-dot ${s.status === 'online' ? 'pulsing' : ''}" 
                                              style="background-color: var(--accent-${s.status === 'online' ? 'success' : 'secondary'})"></span>
                                        <span class="small font-monospace text-uppercase" style="color: var(--accent-${s.status === 'online' ? 'success' : 'secondary'})">
                                            ${s.status || 'OFFLINE'}
                                        </span>
                                    </div>
                                </div>
                                ${s.location ? `
                                    <div class="text-muted small mb-2 font-monospace">
                                        <i class="bi bi-geo-alt me-1"></i>
                                        LAT: ${s.location.lat?.toFixed(6)} | LON: ${s.location.lon?.toFixed(6)}
                                    </div>
                                ` : ''}
                                

                            </div>
                            <div class="card-footer bg-transparent border-top-0 position-relative" style="z-index: 2;">
                                <div class="d-flex gap-2">
                                    <button class="btn btn-sm btn-outline-primary flex-1" onclick="window.adminManager.editStation(${s.id})">
                                        <i class="bi bi-pencil me-1"></i> CONFIGURE
                                    </button>
                                    <button class="btn btn-sm btn-outline-danger" onclick="window.adminManager.deleteStation(${s.id})">
                                        <i class="bi bi-trash"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                `).join('')
            }
            </div >
    `;
    }

    // =========================================================================
    // STATION WIZARD
    // =========================================================================

    openAddStationModal() {
        this.isEditMode = false;
        this.currentStationId = null;
        this.currentStationConfig = {};
        this.stationPresetConfirm = null;
        this.currentStep = 1;

        document.getElementById('stationConfigForm').reset();
        document.getElementById('edit-station-id').value = '';
        document.getElementById('origin-lat').value = '';
        document.getElementById('origin-lon').value = '';
        document.getElementById('origin-h').value = '';
        document.getElementById('origin-status').textContent = 'Chưa có tọa độ gốc';

        // Reset sub-sensor coordinates
        ['rain', 'water', 'imu'].forEach(s => {
            const lat = document.getElementById(`origin-${s}-lat`);
            const lon = document.getElementById(`origin-${s}-lon`);
            const h = document.getElementById(`origin-${s}-h`);
            if (lat) lat.value = '';
            if (lon) lon.value = '';
            if (h) h.value = '';
        });
        document.getElementById('edit-project-id').value = this.currentProjectId;
        document.getElementById('modal-title').textContent = 'Thêm Trạm Mới';

        ['gnss', 'rain', 'water', 'imu'].forEach(sensor => {
            const checkbox = document.getElementById(`edit-${sensor}`);
            if (checkbox) checkbox.checked = false;
            const section = document.getElementById(`mqtt-${sensor}-section`);
            if (section) section.style.display = 'none';
        });

        // ✅ Reset offline thresholds về mặc định
        document.getElementById('offline-gnss').value = this.defaultOfflineThresholds.gnss;
        document.getElementById('offline-rain').value = this.defaultOfflineThresholds.rain;
        document.getElementById('offline-water').value = this.defaultOfflineThresholds.water;
        document.getElementById('offline-imu').value = this.defaultOfflineThresholds.imu;

        // ✅ Update displays
        document.getElementById('offline-gnss-display').textContent = this.formatOfflineTime(this.defaultOfflineThresholds.gnss);
        document.getElementById('offline-rain-display').textContent = this.formatOfflineTime(this.defaultOfflineThresholds.rain);
        document.getElementById('offline-water-display').textContent = this.formatOfflineTime(this.defaultOfflineThresholds.water);
        document.getElementById('offline-imu-display').textContent = this.formatOfflineTime(this.defaultOfflineThresholds.imu);

        // Reset confirm steps source indicators cho trạm mới
        const rainConfirmSrc = document.getElementById('cfg-rain-confirm-source');
        const waterConfirmSrc = document.getElementById('cfg-water-confirm-source');
        if (rainConfirmSrc) { rainConfirmSrc.textContent = '⚠ Sẽ dùng giá trị Hệ thống nếu không sửa'; rainConfirmSrc.className = 'text-warning small'; }
        if (waterConfirmSrc) { waterConfirmSrc.textContent = '⚠ Sẽ dùng giá trị Hệ thống nếu không sửa'; waterConfirmSrc.className = 'text-warning small'; }

        document.getElementById('mqtt-empty-state').style.display = 'block';
        document.getElementById('btn-delete-station').style.display = 'none';

        this.highlightPreset(null);
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

                    console.log(`📋 [EDIT] Device ${type}: is_active=${dev.is_active}, topic=${dev.mqtt_topic}`);

                    // Bật checkbox nếu device active (is_active !== false)
                    if (checkbox && dev.is_active !== false) {
                        checkbox.checked = true;
                        if (section) section.style.display = 'block';
                        if (input) input.value = dev.mqtt_topic || '';
                    } else if (checkbox) {
                        // Explicitly uncheck if inactive
                        checkbox.checked = false;
                        if (section) section.style.display = 'none';
                    }
                });

                // Show empty state if no active devices
                const anyChecked = ['gnss', 'rain', 'water', 'imu'].some(t => document.getElementById(`edit-${t}`)?.checked);
                const emptyState = document.getElementById('mqtt-empty-state');
                if (emptyState) emptyState.style.display = anyChecked ? 'none' : 'block';
            }

            // STEP 3: Thresholds
            const cfg = stationData.config || {};
            this.currentStationConfig = cfg;

            // ✅ ĐỌC OFFLINE THRESHOLDS
            const offlineThresholds = cfg.offline_thresholds || {};
            console.log('📋 [EDIT] Config from API:', JSON.stringify(cfg));
            console.log('📋 [EDIT] offline_thresholds:', JSON.stringify(offlineThresholds));

            const gnssThreshold = offlineThresholds.gnss ?? this.defaultOfflineThresholds.gnss;
            const rainThreshold = offlineThresholds.rain ?? this.defaultOfflineThresholds.rain;
            const waterThreshold = offlineThresholds.water ?? this.defaultOfflineThresholds.water;
            const imuThreshold = offlineThresholds.imu ?? this.defaultOfflineThresholds.imu;

            document.getElementById('offline-gnss').value = gnssThreshold;
            document.getElementById('offline-rain').value = rainThreshold;
            document.getElementById('offline-water').value = waterThreshold;
            document.getElementById('offline-imu').value = imuThreshold;

            // ✅ Update displays
            document.getElementById('offline-gnss-display').textContent = this.formatOfflineTime(gnssThreshold);
            document.getElementById('offline-rain-display').textContent = this.formatOfflineTime(rainThreshold);
            document.getElementById('offline-water-display').textContent = this.formatOfflineTime(waterThreshold);
            document.getElementById('offline-imu-display').textContent = this.formatOfflineTime(imuThreshold);

            if (cfg.velocity_classification && Array.isArray(cfg.velocity_classification)) {
                this.velocityConfig = cfg.velocity_classification;
            } else {
                this.velocityConfig = [
                    { name: 'Extremely slow', threshold: 0, unit: 'mm/year', description: '< 16 mm/year', editable: true },
                    { name: 'Very slow', threshold: 16, unit: 'mm/year', description: '16 mm/year to 1.6 m/year', editable: true },
                    { name: 'Slow', threshold: 1.6, unit: 'm/year', description: '1.6 m/year to 13 mm/month', editable: true },
                    { name: 'Moderate', threshold: 13, unit: 'm/month', description: '13 mm/month to 1.8 m/hour', editable: true },
                    { name: 'Rapid', threshold: 1.8, unit: 'm/hr', description: '1.8 m/hour to 3 m/min', editable: true },
                    { name: 'Very rapid', threshold: 3, unit: 'm/min', description: '3 m/min to 5 m/s', editable: true },
                    { name: 'Extremely rapid', threshold: 5, unit: 'm/s', description: '> 5 m/s', editable: true }
                ];
            }

            const waterCfg = cfg.Water || {};
            document.getElementById('cfg-water-warning').value = waterCfg.warning_threshold ?? 0.15;
            document.getElementById('cfg-water-critical').value = waterCfg.critical_threshold ?? 0.30;

        // Water confirm steps - hiển thị nguồn giá trị
        const waterConfirmEl = document.getElementById('cfg-water-confirm');
        const waterConfirmSrc = document.getElementById('cfg-water-confirm-source');
        if (waterConfirmEl) {
            const wcs = waterCfg.water_confirm_steps;
            waterConfirmEl.value = wcs ?? 3;
            if (waterConfirmSrc) {
                waterConfirmSrc.textContent = wcs != null ? '✅ Đã lưu riêng cho trạm' : '⚠ Sẽ dùng giá trị Hệ thống';
                waterConfirmSrc.className = wcs != null ? 'text-success small' : 'text-warning small';
            }
        }

        const rainCfg = cfg.RainAlerting || {};
        document.getElementById('cfg-rain-watch').value = rainCfg.rain_intensity_watch_threshold ?? 10.0;
        document.getElementById('cfg-rain-warning').value = rainCfg.rain_intensity_warning_threshold ?? 25.0;
        document.getElementById('cfg-rain-critical').value = rainCfg.rain_intensity_critical_threshold ?? 50.0;

        // Rain confirm steps - hiển thị nguồn giá trị
        const rainConfirmEl = document.getElementById('cfg-rain-confirm');
        const rainConfirmSrc = document.getElementById('cfg-rain-confirm-source');
        if (rainConfirmEl) {
            const rcs = rainCfg.rain_confirm_steps;
            rainConfirmEl.value = rcs ?? 2;
            if (rainConfirmSrc) {
                rainConfirmSrc.textContent = rcs != null ? '✅ Đã lưu riêng cho trạm' : '⚠ Sẽ dùng giá trị Hệ thống';
                rainConfirmSrc.className = rcs != null ? 'text-success small' : 'text-warning small';
            }
        }
            const gnssCfg = cfg.GnssAlerting || {};
            document.getElementById('cfg-gnss-streak').value = gnssCfg.gnss_safe_streak ?? 10;
            document.getElementById('cfg-gnss-timeout').value = gnssCfg.gnss_degraded_timeout ?? 300;

            const imuCfg = cfg.ImuAlerting || {};
            document.getElementById('cfg-imu-shock').value = imuCfg.shock_threshold_ms2 ?? 5.0;
            const tiltWarnEl = document.getElementById('cfg-imu-tilt-warn');
            if (tiltWarnEl) tiltWarnEl.value = imuCfg.tilt_warning_deg ?? 5.0;
            const tiltCritEl = document.getElementById('cfg-imu-tilt-crit');
            if (tiltCritEl) tiltCritEl.value = imuCfg.tilt_critical_deg ?? 15.0;
            const imuConfirmEl = document.getElementById('cfg-imu-confirm');
            if (imuConfirmEl) imuConfirmEl.value = imuCfg.imu_confirm_steps ?? 2;

            const imuBaseline = cfg.ImuBaseline || {};
            const baseRollEl = document.getElementById('cfg-imu-base-roll');
            if (baseRollEl) baseRollEl.value = imuBaseline.baseline_roll ?? 0;
            const basePitchEl = document.getElementById('cfg-imu-base-pitch');
            if (basePitchEl) basePitchEl.value = imuBaseline.baseline_pitch ?? 0;
            const baseYawEl = document.getElementById('cfg-imu-base-yaw');
            if (baseYawEl) baseYawEl.value = imuBaseline.baseline_yaw ?? 0;

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

            // Load extra sensor origins
            ['rain', 'water', 'imu'].forEach(s => {
                const sOrigin = cfg[`${s}_origin`] || {};
                const latEl = document.getElementById(`origin-${s}-lat`);
                const lonEl = document.getElementById(`origin-${s}-lon`);
                const hEl = document.getElementById(`origin-${s}-h`);
                if (latEl) latEl.value = sOrigin.lat !== undefined ? sOrigin.lat : '';
                if (lonEl) lonEl.value = sOrigin.lon !== undefined ? sOrigin.lon : '';
                if (hEl) hEl.value = sOrigin.h !== undefined ? sOrigin.h : '';
            });

            document.getElementById('modal-title').textContent = `Chỉnh sửa: ${stationData.name}`;
            document.getElementById('btn-delete-station').style.display = 'inline-block';

            this.highlightPreset(cfg.active_preset);
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

        // When reaching step 3, load pending devices for provisioning (only if editing existing station)
        const pendingSection = document.getElementById('pending-devices-section');
        if (this.currentStep === 3 && this.currentStationId) {
            if (pendingSection) pendingSection.style.display = 'block';
            this.loadPendingDevices();
        } else {
            if (pendingSection) pendingSection.style.display = 'none';
        }
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

    // =========================================================================
    // STATION PRESET SYSTEM
    // =========================================================================

    highlightPreset(presetName) {
        this.activePreset = presetName || null;

        if (!this.activePreset || this.activePreset === 'custom') {
            this.stationPresetConfirm = null;
        }

        // Reset all buttons visual styling to transparent/outlined
        const buttons = document.querySelectorAll('.preset-btn');
        buttons.forEach(btn => {
            btn.classList.remove('active');
            btn.style.opacity = '0.6';
            btn.style.transform = 'scale(0.95)';
            btn.style.boxShadow = 'none';
        });

        if (!this.activePreset || this.activePreset === 'custom') return;

        // Add visual flair to the active one
        const activeBtn = document.getElementById(`btn-preset-${this.activePreset}`);
        if (activeBtn) {
            activeBtn.classList.add('active');
            activeBtn.style.opacity = '1';
            activeBtn.style.transform = 'scale(1)';
            activeBtn.style.boxShadow = '0 0 15px currentColor';
        }
    }

    applyStationPreset(presetName) {
        this.highlightPreset(presetName);

        const presets = {
            conservative: {
                gnss_steps: 5,
                water_confirm: 5,
                rain_confirm: 3,
                gnss_hdop: 3.0,
                gnss_streak: 10,
                gnss_timeout: 600,
                water_warning: 0.20,
                water_critical: 0.40,
                rain_watch: 15.0,
                rain_warning: 35.0,
                rain_critical: 60.0,
                imu_tilt_warn: 10.0,
                imu_tilt_crit: 25.0,
                imu_shock: 8.0,
                imu_confirm: 2
            },
            balanced: {
                gnss_steps: 3,
                water_confirm: 3,
                rain_confirm: 2,
                gnss_hdop: 4.0,
                gnss_streak: 5,
                gnss_timeout: 300,
                water_warning: 0.15,
                water_critical: 0.30,
                rain_watch: 10.0,
                rain_warning: 25.0,
                rain_critical: 50.0,
                imu_tilt_warn: 5.0,
                imu_tilt_crit: 15.0,
                imu_shock: 5.0,
                imu_confirm: 1
            },
            sensitive: {
                gnss_steps: 1,
                water_confirm: 1,
                rain_confirm: 1,
                gnss_hdop: 5.0,
                gnss_streak: 3,
                gnss_timeout: 180,
                water_warning: 0.10,
                water_critical: 0.20,
                rain_watch: 5.0,
                rain_warning: 15.0,
                rain_critical: 30.0,
                imu_tilt_warn: 3.0,
                imu_tilt_crit: 8.0,
                imu_shock: 3.0,
                imu_confirm: 1
            }
        };

        const preset = presets[presetName];
        if (!preset) return;

        // ✅ ĐIỀN TỰ ĐỘNG CÁC GIÁ TRỊ VÀO FORM

        // Rain/Water confirm steps - giờ có input field riêng
        const rainConfirmEl = document.getElementById('cfg-rain-confirm');
        const waterConfirmEl = document.getElementById('cfg-water-confirm');
        if (rainConfirmEl) rainConfirmEl.value = preset.rain_confirm;
        if (waterConfirmEl) waterConfirmEl.value = preset.water_confirm;

        // Cập nhật source indicator
        const rainSrc = document.getElementById('cfg-rain-confirm-source');
        const waterSrc = document.getElementById('cfg-water-confirm-source');
        if (rainSrc) { rainSrc.textContent = '🔧 Từ preset: ' + presetName; rainSrc.className = 'text-info small'; }
        if (waterSrc) { waterSrc.textContent = '🔧 Từ preset: ' + presetName; waterSrc.className = 'text-info small'; }

        // GNSS Quality
        const gnssHdopEl = document.getElementById('cfg-gnss-hdop');
        const gnssStepsEl = document.getElementById('cfg-gnss-steps');
        const gnssStreakEl = document.getElementById('cfg-gnss-streak');
        const gnssTimeoutEl = document.getElementById('cfg-gnss-timeout');

        if (gnssHdopEl) gnssHdopEl.value = preset.gnss_hdop;
        if (gnssStepsEl) gnssStepsEl.value = preset.gnss_steps;
        if (gnssStreakEl) gnssStreakEl.value = preset.gnss_streak;
        if (gnssTimeoutEl) gnssTimeoutEl.value = preset.gnss_timeout;

        // Water
        const waterWarningEl = document.getElementById('cfg-water-warning');
        const waterCriticalEl = document.getElementById('cfg-water-critical');

        if (waterWarningEl) waterWarningEl.value = preset.water_warning;
        if (waterCriticalEl) waterCriticalEl.value = preset.water_critical;

        // Rain
        const rainWatchEl = document.getElementById('cfg-rain-watch');
        const rainWarningEl = document.getElementById('cfg-rain-warning');
        const rainCriticalEl = document.getElementById('cfg-rain-critical');

        if (rainWatchEl) rainWatchEl.value = preset.rain_watch;
        if (rainWarningEl) rainWarningEl.value = preset.rain_warning;
        if (rainCriticalEl) rainCriticalEl.value = preset.rain_critical;

        // IMU
        const imuTiltWarnEl = document.getElementById('cfg-imu-tilt-warn');
        const imuTiltCritEl = document.getElementById('cfg-imu-tilt-crit');
        const imuShockEl = document.getElementById('cfg-imu-shock');
        const imuConfirmEl = document.getElementById('cfg-imu-confirm');

        if (imuTiltWarnEl) imuTiltWarnEl.value = preset.imu_tilt_warn;
        if (imuTiltCritEl) imuTiltCritEl.value = preset.imu_tilt_crit;
        if (imuShockEl) imuShockEl.value = preset.imu_shock;
        if (imuConfirmEl) imuConfirmEl.value = preset.imu_confirm;

        // ✅ HIỆU ỨNG FLASH (để user biết đã áp dụng)
        const inputs = document.querySelectorAll('#stationConfigForm input[type="number"]');
        inputs.forEach(input => {
            input.style.transition = 'background 0.5s';
            input.style.background = 'rgba(14, 165, 233, 0.2)';
            setTimeout(() => {
                input.style.background = '';
            }, 500);
        });

        // ✅ THÔNG BÁO
        const presetLabels = {
            'conservative': 'Conservative - Ít cảnh báo sai',
            'balanced': 'Balanced - Cân bằng',
            'sensitive': 'Sensitive - Phát hiện nhanh'
        };

        window.toast?.success(`✅ Đã áp dụng preset: ${presetLabels[presetName]}`, 3000);
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
        const sensorTypes = ['gnss', 'rain', 'water', 'imu'];
        let hasError = false;

        sensorTypes.forEach(type => {
            const checkbox = document.getElementById(`edit-${type}`);
            if (checkbox && checkbox.checked) {
                const topicInput = document.getElementById(`topic-${type}`);
                const topic = topicInput?.value.trim();

                if (!topic) {
                    window.toast?.error(`Vui lòng nhập MQTT Topic cho ${type.toUpperCase()}`);
                    topicInput.focus();
                    hasError = true;
                    return;
                }

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
                } else if (['rain', 'water', 'imu'].includes(type)) {
                    const lat = document.getElementById(`origin-${type}-lat`)?.value;
                    const lon = document.getElementById(`origin-${type}-lon`)?.value;
                    const h = document.getElementById(`origin-${type}-h`)?.value;

                    if (lat && lon) {
                        sensors[type].lat = parseFloat(lat);
                        sensors[type].lon = parseFloat(lon);
                        sensors[type].h = parseFloat(h) || 0;
                    }
                }
            }
        });

        if (hasError) return;

        // Rain/Water confirm steps: đọc trực tiếp từ input (user đã thấy và có thể sửa)
        const finalRainConfirm = parseInt(document.getElementById('cfg-rain-confirm')?.value) || 2;
        const finalWaterConfirm = parseInt(document.getElementById('cfg-water-confirm')?.value) || 3;

        // ✅ THÊM OFFLINE THRESHOLDS VÀO CONFIG
        const config = {
            active_preset: this.activePreset || '',
            offline_thresholds: {
                gnss: parseInt(document.getElementById('offline-gnss').value) || this.defaultOfflineThresholds.gnss,
                rain: parseInt(document.getElementById('offline-rain').value) || this.defaultOfflineThresholds.rain,
                water: parseInt(document.getElementById('offline-water').value) || this.defaultOfflineThresholds.water,
                imu: parseInt(document.getElementById('offline-imu').value) || this.defaultOfflineThresholds.imu
            },
            Water: {
                warning_threshold: parseFloat(document.getElementById('cfg-water-warning').value),
                critical_threshold: parseFloat(document.getElementById('cfg-water-critical').value),
                water_confirm_steps: finalWaterConfirm
            },
            RainAlerting: {
                rain_intensity_watch_threshold: parseFloat(document.getElementById('cfg-rain-watch').value),
                rain_intensity_warning_threshold: parseFloat(document.getElementById('cfg-rain-warning').value),
                rain_intensity_critical_threshold: parseFloat(document.getElementById('cfg-rain-critical').value),
                rain_confirm_steps: finalRainConfirm
            },
            GnssAlerting: {
                gnss_max_hdop: parseFloat(document.getElementById('cfg-gnss-hdop').value) || 4.0,
                gnss_confirm_steps: parseInt(document.getElementById('cfg-gnss-steps').value) || 3,
                gnss_safe_streak: parseInt(document.getElementById('cfg-gnss-streak').value) || 10,
                gnss_degraded_timeout: parseInt(document.getElementById('cfg-gnss-timeout').value) || 300
            },
            ImuAlerting: {
                tilt_warning_deg: parseFloat(document.getElementById('cfg-imu-tilt-warn').value) || 5.0,
                tilt_critical_deg: parseFloat(document.getElementById('cfg-imu-tilt-crit').value) || 15.0,
                imu_confirm_steps: parseInt(document.getElementById('cfg-imu-confirm').value) || 2,
                shock_threshold_ms2: parseFloat(document.getElementById('cfg-imu-shock').value) || 5.0
            },
            ImuBaseline: {
                baseline_roll: parseFloat(document.getElementById('cfg-imu-base-roll')?.value) || 0.0,
                baseline_pitch: parseFloat(document.getElementById('cfg-imu-base-pitch')?.value) || 0.0,
                baseline_yaw: parseFloat(document.getElementById('cfg-imu-base-yaw')?.value) || 0.0
            },
            gnss_origin: {
                lat: document.getElementById('origin-lat').value,
                lon: document.getElementById('origin-lon').value,
                h: document.getElementById('origin-h').value
            },
            rain_origin: {
                lat: document.getElementById('origin-rain-lat')?.value !== '' ? document.getElementById('origin-rain-lat').value : undefined,
                lon: document.getElementById('origin-rain-lon')?.value !== '' ? document.getElementById('origin-rain-lon').value : undefined,
                h: document.getElementById('origin-rain-h')?.value !== '' ? document.getElementById('origin-rain-h').value : undefined
            },
            water_origin: {
                lat: document.getElementById('origin-water-lat')?.value !== '' ? document.getElementById('origin-water-lat').value : undefined,
                lon: document.getElementById('origin-water-lon')?.value !== '' ? document.getElementById('origin-water-lon').value : undefined,
                h: document.getElementById('origin-water-h')?.value !== '' ? document.getElementById('origin-water-h').value : undefined
            },
            imu_origin: {
                lat: document.getElementById('origin-imu-lat')?.value !== '' ? document.getElementById('origin-imu-lat').value : undefined,
                lon: document.getElementById('origin-imu-lon')?.value !== '' ? document.getElementById('origin-imu-lon').value : undefined,
                h: document.getElementById('origin-imu-h')?.value !== '' ? document.getElementById('origin-imu-h').value : undefined
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

        console.log('💾 [SAVE] isEditMode:', this.isEditMode, 'stationId:', this.currentStationId);
        console.log('💾 [SAVE] Payload:', JSON.stringify(payload, null, 2));

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
            { name: 'Extremely slow', threshold: 0, unit: 'mm/year', description: '< 16 mm/year', editable: true },
            { name: 'Very slow', threshold: 16, unit: 'mm/year', description: '16 mm/year to 1.6 m/year', editable: true },
            { name: 'Slow', threshold: 1.6, unit: 'm/year', description: '1.6 m/year to 13 mm/month', editable: true },
            { name: 'Moderate', threshold: 13, unit: 'm/month', description: '13 mm/month to 1.8 m/hour', editable: true },
            { name: 'Rapid', threshold: 1.8, unit: 'm/hr', description: '1.8 m/hour to 3 m/min', editable: true },
            { name: 'Very rapid', threshold: 3, unit: 'm/min', description: '3 m/min to 5 m/s', editable: true },
            { name: 'Extremely rapid', threshold: 5, unit: 'm/s', description: '> 5 m/s', editable: true }
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
    // PENDING DEVICES (ADMIN PROVISIONING)
    // =========================================================================

    async loadPendingDevices() {
        try {
            const res = await fetch('/api/admin/devices/pending', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) throw new Error('Không thể tải danh sách thiết bị chờ');

            const devices = await res.json();
            this.renderPendingDevices(devices);
        } catch (e) {
            console.error('Error loading pending devices:', e);
            window.toast?.error('Không lấy được danh sách Pi chờ');
        }
    }

    renderPendingDevices(devices) {
        const container = document.getElementById('pending-devices-list');
        if (!container) return;

        if (!devices || devices.length === 0) {
            container.innerHTML = `<div class="text-muted small p-3">Không có Pi chờ kích hoạt</div>`;
            return;
        }

        container.innerHTML = devices.map(d => `
            <div class="pending-device-card border rounded mb-2 p-3" id="pending-${d.device_code}">
                <div class="d-flex align-items-center justify-content-between mb-2">
                    <div>
                        <i class="bi bi-cpu me-2 text-warning"></i>
                        <strong>${d.name || d.device_code}</strong>
                        <small class="text-muted ms-2">(${d.device_type})</small>
                    </div>
                    <button class="btn btn-sm btn-outline-primary" onclick="window.adminManager.showDeviceDetail('${d.device_code}')">
                        <i class="bi bi-eye me-1"></i>Chi tiết
                    </button>
                </div>
                <div class="small text-muted">
                    Đăng ký: ${new Date((d.created_at || 0) * 1000).toLocaleString()}
                </div>
                <div id="detail-${d.device_code}" class="mt-2" style="display:none;">
                    <div class="bg-body-tertiary rounded p-3 mb-2">
                        <div class="mb-2">
                            <label class="form-label small fw-bold mb-1">Serial / Device Code:</label>
                            <div class="font-monospace bg-dark text-success p-2 rounded" style="font-size: 1.1rem; letter-spacing: 1px;">
                                ${d.device_code}
                            </div>
                        </div>
                        <div class="mb-2">
                            <label class="form-label small fw-bold mb-1">License:</label>
                            <div id="license-display-${d.device_code}" class="font-monospace text-muted small">
                                ${d.config?.license ? '<span class="text-success">✅ ' + d.config.license + '</span>' : '<span class="text-warning">⚠️ Chưa có license</span>'}
                            </div>
                        </div>
                    </div>
                    <div class="d-flex gap-2">
                        <button class="btn btn-sm btn-warning flex-fill" onclick="window.adminManager.generateAndProvision('${d.device_code}')">
                            <i class="bi bi-key me-1"></i>Tạo Key & Gán vào trạm
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" onclick="window.adminManager.generateLicense('${d.device_code}')">
                            <i class="bi bi-key me-1"></i>Chỉ tạo Key
                        </button>
                    </div>
                </div>
            </div>
        `).join('');
    }

    showDeviceDetail(device_code) {
        const detailEl = document.getElementById(`detail-${device_code}`);
        if (detailEl) {
            detailEl.style.display = detailEl.style.display === 'none' ? 'block' : 'none';
        }
    }

    async generateLicense(device_code) {
        try {
            const res = await fetch('/api/admin/devices/generate-license', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ device_code: device_code })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi tạo license');
            }

            const data = await res.json();

            // Update license display
            const licenseEl = document.getElementById(`license-display-${device_code}`);
            if (licenseEl) {
                licenseEl.innerHTML = `<span class="text-success">✅ ${data.license}</span>`;
                if (data.pushed) {
                    licenseEl.innerHTML += ` <span class="badge bg-info">Đã gửi qua MQTT</span>`;
                }
            }

            window.toast?.success(`✅ License tạo xong${data.pushed ? ' & đã gửi đến Pi' : ''}`);
            return data;
        } catch (e) {
            console.error('Generate license error:', e);
            window.toast?.error('❌ ' + e.message);
        }
    }

    async generateAndProvision(device_code) {
        if (!this.currentStationId) {
            window.toast?.warning('Lưu trạm trước khi gán thiết bị');
            return;
        }

        try {
            // Step 1: Generate license
            window.toast?.info('🔑 Đang tạo license...');
            const licenseData = await this.generateLicense(device_code);
            if (!licenseData) return;

            // Step 2: Provision (assign to station) with license
            window.toast?.info('📡 Đang gán thiết bị vào trạm...');
            const res = await fetch('/api/admin/devices/provision', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    device_code: device_code,
                    station_id: this.currentStationId,
                    license: licenseData.license
                })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi khi gán thiết bị');
            }

            window.toast?.success(`✅ Pi ${device_code} đã gán vào trạm & license đã gửi!`);

            // Refresh pending list (device should disappear)
            this.loadPendingDevices();
        } catch (e) {
            console.error('Generate & provision error:', e);
            window.toast?.error('❌ ' + e.message);
        }
    }

    async provisionDevice(device_code) {
        if (!this.currentStationId) {
            window.toast?.warning('Lưu trạm trước khi gán thiết bị');
            return;
        }

        const license = prompt('Nhập mã license/serial để lưu (hoặc để trống):');
        if (license === null) return; // cancelled

        try {
            const res = await fetch('/api/admin/devices/provision', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ device_code: device_code, station_id: this.currentStationId, license: license })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi khi gán thiết bị');
            }

            window.toast?.success('✅ Thiết bị đã được gán thành công');
            // refresh lists
            this.loadPendingDevices();
            // reload station devices view if open
            this.editStation(this.currentStationId);
        } catch (e) {
            console.error('Provision error:', e);
            window.toast?.error('❌ ' + e.message);
        }
    }


    // =========================================================================
    // USER MANAGEMENT
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
        }
    }

    renderUsers(users) {
        const tbody = document.getElementById('user-table-body');
        if (!tbody) return;

        if (!users || users.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">Chưa có người dùng</td></tr>`;
            return;
        }

        const roleBadge = (role) => {
            const colors = { admin: 'danger', operator: 'info', viewer: 'secondary' };
            const labels = { admin: 'Admin', operator: 'Operator', viewer: 'Viewer' };
            const c = colors[role] || 'secondary';
            const l = labels[role] || role;
            return `<span class="badge bg-${c} bg-opacity-10 border border-${c} text-${c}">${l}</span>`;
        };

        tbody.innerHTML = users.map(u => {
            // Show assigned projects for operators (by name)
            let projectBadges = '';
            if (u.role === 'operator' && u.assigned_projects && u.assigned_projects.length > 0) {
                projectBadges = `<br><small class="text-muted">Dự án: ${u.assigned_projects.map(
                    pid => `<span class="badge bg-dark text-info border border-info" style="font-size:.65rem">${this.getProjectName(pid)}</span>`
                ).join(' ')}</small>`;
            }

            return `
            <tr class="glass-row">
                <td class="font-monospace text-muted">#${u.id}</td>
                <td><strong class="text-primary">${u.username}</strong></td>
                <td class="text-white">${u.full_name || '--'}</td>
                <td>${roleBadge(u.role)}${projectBadges}</td>
                <td>
                    <div class="d-flex align-items-center gap-2">
                        <span class="status-dot ${u.is_active ? 'pulsing' : ''}" 
                              style="background-color: var(--accent-${u.is_active ? 'success' : 'secondary'})"></span>
                        <span class="small font-monospace" style="color: var(--accent-${u.is_active ? 'success' : 'secondary'})">
                            ${u.is_active ? 'ACTIVE' : 'LOCKED'}
                        </span>
                    </div>
                </td>
                <td>
                    <div class="btn-group btn-group-sm">
                        ${u.role === 'operator' ? `<button class="btn btn-outline-info" onclick="window.adminManager.showAssignProjectsModal(${u.id}, '${u.username}')" title="Gán dự án"><i class="bi bi-folder-plus"></i></button>` : ''}
                        ${u.username === 'admin' ? '' : `
                        <button class="btn btn-outline-${u.is_active ? 'warning' : 'success'}" onclick="window.adminManager.toggleUserStatus(${u.id}, '${u.username}', ${!u.is_active})" title="${u.is_active ? 'Khóa tài khoản' : 'Mở khóa'}">
                            <i class="bi bi-${u.is_active ? 'lock' : 'unlock'}"></i>
                        </button>
                        <button class="btn btn-outline-danger" onclick="window.adminManager.deleteUser(${u.id}, '${u.username}')" title="Xóa tài khoản">
                            <i class="bi bi-trash"></i>
                        </button>
                        `}
                    </div>
                </td>
            </tr>
        `}).join('');
    }

    async createUser() {
        const username = document.getElementById('new-username').value.trim();
        const password = document.getElementById('new-password').value;
        const fullname = document.getElementById('new-fullname').value.trim();
        const role = document.getElementById('new-role').value;

        // Collect assigned projects (checkboxes)
        const assignedProjects = [];
        document.querySelectorAll('#project-checkbox-list input[type="checkbox"]:checked').forEach(cb => {
            assignedProjects.push(parseInt(cb.value));
        });

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
                body: JSON.stringify({
                    username, password, full_name: fullname, role,
                    assigned_projects: role === 'operator' ? assignedProjects : []
                })
            });

            if (res.ok) {
                window.toast?.success('✅ Tạo tài khoản thành công');
                bootstrap.Modal.getInstance(document.getElementById('addUserModal'))?.hide();
                document.getElementById('addUserForm').reset();
                document.getElementById('project-assign-group').style.display = 'none';
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
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi xóa');
            }
        } catch (e) {
            window.toast?.error(e.message);
        }
    }

    async toggleUserStatus(userId, username, isActive) {
        const action = isActive ? 'mở khóa' : 'khóa';
        if (!confirm(`Bạn có chắc muốn ${action} người dùng ${username}?`)) return;
        try {
            const res = await fetch(`/api/admin/users/${userId}/status`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ is_active: isActive })
            });

            if (res.ok) {
                window.toast?.success(`Đã ${action} người dùng ${username}`);
                this.loadUsers();
            } else {
                const err = await res.json();
                throw new Error(err.detail || `Lỗi ${action} tài khoản`);
            }
        } catch (e) {
            window.toast?.error(e.message);
        }
    }

    /** Load project list into the Add User modal checkboxes */
    async loadProjectsForModal() {
        try {
            const res = await fetch('/api/admin/projects', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) return;
            const projects = await res.json();

            const container = document.getElementById('project-checkbox-list');
            if (!container) return;

            if (projects.length === 0) {
                container.innerHTML = '<small class="text-muted">Chưa có dự án nào</small>';
                return;
            }

            container.innerHTML = projects.map(p => `
                <div class="form-check mb-1">
                    <input class="form-check-input" type="checkbox" value="${p.id}" id="assign-proj-${p.id}">
                    <label class="form-check-label small" for="assign-proj-${p.id}">${p.name} <span class="text-muted">(#${p.id})</span></label>
                </div>
            `).join('');
        } catch (e) {
            console.error('Error loading projects for modal:', e);
        }
    }

    /** Show prompt to assign projects to an operator */
    async showAssignProjectsModal(userId, username) {
        try {
            // Fetch current user data
            const userRes = await fetch('/api/admin/users', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            const users = await userRes.json();
            const user = users.find(u => u.id === userId);
            const currentAssigned = user?.assigned_projects || [];

            // Fetch all projects
            const projRes = await fetch('/api/admin/projects', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            const projects = await projRes.json();

            // Build HTML
            const checkboxes = projects.map(p => {
                const checked = currentAssigned.includes(p.id) ? 'checked' : '';
                return `<div class="form-check mb-1">
                    <input class="form-check-input assign-proj-cb" type="checkbox" value="${p.id}" ${checked}>
                    <label class="form-check-label small">${p.name} (#${p.id})</label>
                </div>`;
            }).join('');

            // Use a simple confirm dialog approach
            const modal = document.createElement('div');
            modal.innerHTML = `
                <div class="modal fade" id="assignProjectModal" tabindex="-1">
                    <div class="modal-dialog">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">Gán dự án cho ${username}</h5>
                                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                            </div>
                            <div class="modal-body">
                                <div style="max-height:300px;overflow-y:auto">${checkboxes || '<p class="text-muted">Chưa có dự án</p>'}</div>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                                <button type="button" class="btn btn-gradient" id="save-assign-btn">Lưu</button>
                            </div>
                        </div>
                    </div>
                </div>`;
            document.body.appendChild(modal);

            const bsModal = new bootstrap.Modal(modal.querySelector('.modal'));
            bsModal.show();

            modal.querySelector('#save-assign-btn').addEventListener('click', async () => {
                const selected = [];
                modal.querySelectorAll('.assign-proj-cb:checked').forEach(cb => {
                    selected.push(parseInt(cb.value));
                });

                const res = await fetch(`/api/admin/users/${userId}/projects`, {
                    method: 'PUT',
                    headers: {
                        'Authorization': `Bearer ${this.token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ assigned_projects: selected })
                });

                if (res.ok) {
                    window.toast?.success(`✅ Đã gán ${selected.length} dự án cho ${username}`);
                    bsModal.hide();
                    this.loadUsers();
                } else {
                    window.toast?.error('❌ Lỗi gán dự án');
                }
            });

            modal.querySelector('.modal').addEventListener('hidden.bs.modal', () => {
                modal.remove();
            });
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

    /** Apply viewer restrictions — hide all edit/create/delete UI elements */
    applyViewerRestrictions() {
        console.log('🔒 Applying viewer restrictions');

        // Hide sidebar tabs: Users, Database, System, Pi Devices (only show Projects)
        document.querySelectorAll('.admin-sidebar .nav-item').forEach(item => {
            const link = item.querySelector('[data-tab]');
            if (link) {
                const tab = link.getAttribute('data-tab');
                if (tab !== 'tab-projects') {
                    item.style.display = 'none';
                }
            }
        });

        // Hide all create/edit/delete buttons in Projects tab
        document.querySelectorAll('#action-buttons-container, #btn-back-nav').forEach(el => {
            // Keep back button but hide create buttons
        });
        const createProjBtn = document.querySelector('#action-buttons-container');
        if (createProjBtn) createProjBtn.style.display = 'none';

        // Hide "Thêm user" button
        const addUserBtn = document.querySelector('[data-bs-target="#addUserModal"]');
        if (addUserBtn) addUserBtn.style.display = 'none';

        // Switch to projects tab by default
        const projLink = document.querySelector('[data-tab="tab-projects"]');
        if (projLink) this.switchTab('tab-projects', projLink);
    }

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
            let statusBadge = `<span class="badge" style="background:${color};color:#000;font-size:.72rem">● ${statusLabels[c.status] || c.status}</span>`;
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
                    const pLastPingText = p.last_seen ? this._formatTimeAgo(p.last_seen, pIsOnline) : '—';
                    return `
                    <div style="margin-top: 6px; padding: 4px 8px; background-color: rgba(255, 193, 7, 0.15); border-left: 3px solid #ffc107; border-radius: 4px; font-size: 0.75rem; display: inline-block;">
                        <span class="badge bg-warning text-dark me-1" style="font-size:.6rem">Pi Hiện trường</span>
                        <strong style="color:var(--text-color)">${p.name}</strong> 
                        <code class="text-muted mx-1">${p.serial}</code>
                        <span class="mx-1" style="font-size: 0.7rem; color: ${pIsOnline ? '#10b981' : '#ef4444'}">● ${pLastPingText}</span>
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
            const lastPingText = c.last_seen ? this._formatTimeAgo(c.last_seen, isOnline) : '—';

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
            <td><span class="${isOnline ? 'ping-online' : 'ping-offline'} me-1">●</span><small>${lastPingText}</small></td>
        </tr>`;
        });

        // Những điểm (pi points) chưa được gán pi_center_id sẽ nằm riêng ở cuối
        // unassignedPoints đã được khai báo ở đầu hàm (line 1827)
        unassignedPoints.forEach(p => {
            const pColor = statusColors[p.status] || '#6b7280';
            let pStatusBadge = `<span class="badge" style="background:${pColor};color:#000;font-size:.72rem">● ${statusLabels[p.status] || p.status}</span>`;
            if (p.is_locked) {
                pStatusBadge += ` <span class="badge bg-danger" style="font-size:.65rem" title="Thiết bị bị khóa">🔒</span>`;
            }

            const nameLabel = `<strong>${p.name}</strong><br><small class="text-muted"><span class="badge bg-warning text-dark me-1" style="font-size:.6rem">Pi Hiện trường</span><span style="font-size:.6rem">(Chưa Gắn)</span></small>`;
            const pIsOnline = p.last_seen && (Date.now() / 1000 - p.last_seen) < 120;
            const pLastPingText = p.last_seen ? this._formatTimeAgo(p.last_seen, pIsOnline) : '—';

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
                <td><span class="${pIsOnline ? 'ping-online' : 'ping-offline'} me-1">●</span><small>${pLastPingText}</small></td>
            </tr>`;
        });

        tbody.innerHTML = html;
        if (infoEl) infoEl.textContent = `Showing 1 to ${devices.length} of ${devices.length} entries`;
    }

    /** Format epoch timestamp to human-readable time ago */
    _formatTimeAgo(epoch, isOnline) {
        if (!epoch) return '—';
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

    // =========================================================================
    // FIELD STATION GẮN LIỀN VỚI PI CENTER
    // =========================================================================

    /** Assign selected pi_point(s) from the action bar to a Pi Center */
    async assignSelectedPointToCenter() {
        const checked = document.querySelectorAll('.pi-checkbox:checked');
        const pointIds = [];
        checked.forEach(cb => {
            const row = cb.closest('.pi-grid-row') || cb.closest('tr');
            if (row && row.dataset.piType === 'pi_point') {
                pointIds.push(parseInt(cb.dataset.piId));
            }
        });
        if (pointIds.length === 0) {
            window.toast?.warning('Không có Pi Hiện trường nào được chọn');
            return;
        }

        // Fetch available Pi Centers (activated or assigned, not pi_point)
        try {
            const res = await fetch('/api/field/pi-devices', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) throw new Error('Failed to load devices');
            const devices = await res.json();
            const centers = devices.filter(d =>
                d.device_type !== 'pi_point' &&
                (d.status === 'activated' || d.status === 'assigned')
            );

            if (centers.length === 0) {
                window.toast?.warning('Không có Pi Trung tâm nào khả dụng. Hãy kích hoạt Pi Trung tâm trước.');
                return;
            }

            // Build a quick modal to pick center
            const existing = document.getElementById('pickCenterModal');
            if (existing) existing.remove();

            const modal = document.createElement('div');
            modal.innerHTML = `
                <div class="modal fade" id="pickCenterModal" tabindex="-1">
                    <div class="modal-dialog modal-dialog-centered">
                        <div class="modal-content">
                            <div class="modal-header" style="background:linear-gradient(135deg,#0ea5e9,#6366f1);color:#fff">
                                <h5 class="modal-title"><i class="bi bi-link-45deg me-2"></i>Gán ${pointIds.length} Pi Hiện trường vào Pi Trung tâm</h5>
                                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                            </div>
                            <div class="modal-body">
                                <p class="text-muted small mb-3">Chọn Pi Trung tâm để gán:</p>
                                <div class="list-group list-group-flush" id="center-pick-list">
                                    ${centers.map(c => `
                                        <label class="list-group-item list-group-item-action d-flex gap-3 align-items-center"
                                               style="cursor:pointer; background:transparent; border-color:var(--border-color)">
                                            <input type="radio" name="center-pick" value="${c.id}" class="form-check-input">
                                            <div>
                                                <strong>${c.name}</strong>
                                                <small class="d-block text-muted font-monospace">${c.serial}</small>
                                                ${c.station_name ? `<small class="text-info">📍 ${c.station_name}</small>` : ''}
                                            </div>
                                            <span class="badge ${c.status === 'assigned' ? 'bg-primary' : 'bg-success'} ms-auto">${c.status === 'assigned' ? '📍 Assigned' : '✅ Activated'}</span>
                                        </label>
                                    `).join('')}
                                </div>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                                <button type="button" class="btn btn-primary" id="btn-confirm-center-pick">
                                    <i class="bi bi-check-lg me-1"></i>Gán
                                </button>
                            </div>
                        </div>
                    </div>
                </div>`;
            document.body.appendChild(modal);

            const bsModal = new bootstrap.Modal(document.getElementById('pickCenterModal'));
            bsModal.show();

            document.getElementById('btn-confirm-center-pick').addEventListener('click', async () => {
                const selected = document.querySelector('input[name="center-pick"]:checked');
                if (!selected) {
                    window.toast?.warning('Vui lòng chọn Pi Trung tâm');
                    return;
                }
                const centerId = parseInt(selected.value);

                let ok = 0, fail = 0;
                for (const pointId of pointIds) {
                    try {
                        const r = await fetch(`/api/field/pi-devices/${pointId}/assign-to-center`, {
                            method: 'PUT',
                            headers: {
                                'Authorization': `Bearer ${this.token}`,
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify({ pi_center_id: centerId })
                        });
                        if (r.ok) ok++; else fail++;
                    } catch { fail++; }
                }

                bsModal.hide();
                if (ok > 0) window.toast?.success(`✅ Đã gán ${ok} Pi Hiện trường thành công!`);
                if (fail > 0) window.toast?.error(`❌ ${fail} thất bại`);

                // Exit select mode and reload
                this._piSelectMode = false;
                const toggleBtn = document.getElementById('pi-select-toggle');
                if (toggleBtn) { toggleBtn.classList.replace('btn-primary', 'btn-outline-secondary'); toggleBtn.innerHTML = '<i class="bi bi-check2-square me-1"></i>Chọn'; }
                const bar = document.getElementById('pi-action-bar');
                if (bar) bar.style.bottom = '-80px';
                setTimeout(() => this.loadPiDevices(), 500);
            });

            document.getElementById('pickCenterModal').addEventListener('hidden.bs.modal', () => {
                modal.remove();
            });

        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

    /** Open popup to assign an activated Pi Point to a Center */
    async openAssignPiPointModal(centerId) {
        document.getElementById('assign-center-id').value = centerId;
        const select = document.getElementById('point-device-select');
        select.innerHTML = '<option value="">-- Đang tải ... --</option>';

        const modal = new bootstrap.Modal(document.getElementById('assignPiPointModal'));
        modal.show();

        try {
            // Load ALL devices again
            const res = await fetch('/api/field/pi-devices', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) throw new Error('Failed to load devices');
            const devices = await res.json();

            // Filter ones that are pi_point, activated, and have no pi_center_id
            const pointsToAssign = devices.filter(d =>
                d.device_type === 'pi_point' &&
                d.status === 'activated' &&
                !d.pi_center_id
            );

            if (pointsToAssign.length === 0) {
                select.innerHTML = '<option value="">(Không có Pi Hiện trường nào đang rảnh và đã Activated)</option>';
            } else {
                select.innerHTML = '<option value="">-- Chọn 1 Pi Hiện Trường --</option>' +
                    pointsToAssign.map(p => `<option value="${p.id}">${p.name} (${p.serial})</option>`).join('');
            }
        } catch (e) {
            console.error(e);
            select.innerHTML = '<option value="">(Lỗi tải danh sách)</option>';
        }
    }

    /** Call the PUT /assign-to-center endpoint */
    async confirmAssignPiPoint() {
        const centerId = document.getElementById('assign-center-id').value;
        const select = document.getElementById('point-device-select');
        const pointId = select.value;

        if (!pointId) {
            window.toast?.warning("Vui lòng chọn 1 Pi Hiện Trường");
            return;
        }

        try {
            const res = await fetch(`/api/field/pi-devices/${pointId}/assign-to-center`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ pi_center_id: parseInt(centerId) })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi gắn thiết bị');
            }

            window.toast?.success("✅ Đã gắn Pi Hiện Trường thành công!");
            bootstrap.Modal.getInstance(document.getElementById('assignPiPointModal'))?.hide();
            this.loadPiDevices();
        } catch (e) {
            window.toast?.error("❌ " + e.message);
        }
    }

    // ---- Wizard: Pi section (step 3) ----

    /** Called by updateWizardStep() when step 3 is opened in station wizard */
    async loadPendingDevices() {
        const listEl = document.getElementById('pending-devices-list');
        const btnRow = document.getElementById('pi-assign-btn-row');
        const currentPiInfo = document.getElementById('current-pi-info');

        if (!listEl) return;

        listEl.innerHTML = `<div class="text-center py-3">
                    <div class="spinner-border spinner-border-sm text-primary"></div>
                    <small class="ms-2 text-muted">Đang tải...</small>
                </div>`;

        try {
            // 1. Check if this station already has an assigned Pi
            const allRes = await fetch('/api/field/pi-devices', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            const allDevices = await allRes.json();
            const assignedPi = allDevices.find(d => d.station_id === this.currentStationId && d.status === 'assigned' && d.device_type !== 'pi_point');

            if (assignedPi && currentPiInfo) {
                currentPiInfo.style.display = 'flex';
                currentPiInfo.style.alignItems = 'center';
                const piNameEl = document.getElementById('current-pi-name');
                if (piNameEl) piNameEl.textContent = `${assignedPi.name} (${assignedPi.serial})`;
                this._assignedPiId = assignedPi.id;
            } else if (currentPiInfo) {
                currentPiInfo.style.display = 'none';
                this._assignedPiId = null;
            }

            // 2. Load available Pi (activated, not assigned)
            const available = allDevices.filter(d => d.status === 'activated' && d.device_type !== 'pi_point');

            if (available.length === 0) {
                listEl.innerHTML = `<p class="text-muted small">
                Không có Pi nào đã kích hoạt và chưa được gán. 
                <a href="#" onclick="event.preventDefault(); bootstrap.Tab.getOrCreateInstance(document.querySelector('[data-bs-target=&apos;#tab-pi&apos;]')).show(); window.adminManager.loadPiDevices();">
                    Đến tab Pi Devices để kích hoạt
                </a>
            </p>`;
                if (btnRow) btnRow.style.display = 'none';
                return;
            }

            listEl.innerHTML = `
                <div class="list-group list-group-flush">
                    ${available.map(d => `
                    <label class="list-group-item list-group-item-action d-flex gap-3 align-items-center"
                           style="cursor:pointer; background:transparent; border-color:var(--border-color)">
                        <input type="radio" name="pi-select" value="${d.id}" class="form-check-input">
                        <div>
                            <strong class="font-monospace">${d.name}</strong>
                            <small class="d-block text-muted font-monospace">${d.serial}</small>
                        </div>
                        <span class="badge bg-success ms-auto">✅ Sẵn sàng</span>
                    </label>
                `).join('')}
                </div>`;

            if (btnRow) btnRow.style.display = 'block';

            // Show assign button row only when a radio is selected
            listEl.querySelectorAll('input[name="pi-select"]').forEach(r => {
                r.addEventListener('change', () => {
                    if (btnRow) btnRow.style.display = 'block';
                });
            });

        } catch (e) {
            listEl.innerHTML = '<p class="text-danger small">Lỗi tải danh sách Pi</p>';
            console.error(e);
        }
    }

    /** Assign the selected Pi (from wizard radio) to the current station */
    async assignSelectedPiToStation() {
        const selected = document.querySelector('input[name="pi-select"]:checked');
        if (!selected) {
            window.toast?.warning('Vui lòng chọn một Pi');
            return;
        }
        const piId = parseInt(selected.value);
        try {
            const res = await fetch(`/api/field/pi-devices/${piId}/assign`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ station_id: this.currentStationId })
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi gán trạm');
            }
            const data = await res.json();
            window.toast?.success(`✅ Đã gán Pi vào trạm "${data.station_name}"`);
            // Reload the wizard Pi section
            this.loadPendingDevices();
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

    /** Unassign the currently-assigned Pi from the current station (wizard) */
    async unassignPiFromStation() {
        if (!this._assignedPiId) return;
        try {
            const res = await fetch(`/api/field/pi-devices/${this._assignedPiId}/unassign`, {
                method: 'PUT',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) throw new Error('Lỗi');
            window.toast?.success('✅ Đã bỏ gán Pi');
            this._assignedPiId = null;
            this.loadPendingDevices();
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
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
    if (document.getElementById('projects-content-area')) {
        window.adminManager = new AdminManager();
    } else {
        console.error('❌ Admin Dashboard DOM element missing');
    }
});

// Update UI: set username and reveal System tab for admins (moved from inline HTML)
document.addEventListener('DOMContentLoaded', async () => {
    const token = localStorage.getItem('token') || sessionStorage.getItem('token');
    if (!token) return;

    // Prefer using authManager if available
    try {
        let user = window.authManager?.getUserInfo() || window.authManager?.user;

        if (!user) {
            const res = await fetch('/api/auth/me', { headers: { 'Authorization': `Bearer ${token}` } });
            if (res.ok) user = await res.json();
        }

        if (user) {
            const usernameEl = document.querySelector('.user-profile span');
            if (usernameEl) usernameEl.textContent = user.full_name || user.username;

            if (user.role === 'admin') {
                const systemTab = document.getElementById('system-tab');
                if (systemTab) {
                    systemTab.style.display = 'block';
                    console.log('✅ System tab enabled (admin)');
                }
            }
        }
    } catch (e) {
        console.error('Error updating admin UI:', e);
    }
});