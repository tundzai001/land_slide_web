// =====================================================
// ADMIN MANAGER - COMPLETE WITH PROJECTS + WIZARD
// =====================================================

class AdminManager {
    constructor() {
        this.token = localStorage.getItem('token');
        
        // Navigation state
        this.currentView = 'projects'; // 'projects' | 'stations'
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
        this.tempClassificationData = [];
        
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
        
        const previous = this.navigationStack.pop();
        
        if (previous.view === 'projects') {
            this.resetNavigation();
            this.loadProjects();
        }
        
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
            // Save navigation state
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
                                        ${s.location}
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
        
        // Reset form
        document.getElementById('stationConfigForm').reset();
        document.getElementById('edit-station-id').value = '';
        document.getElementById('edit-project-id').value = this.currentProjectId;
        document.getElementById('modal-title').textContent = 'Thêm Trạm Mới';
        
        // Reset checkboxes
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
        this.isEditMode = true;
        this.currentStationId = stationId;
        this.currentStep = 1;
        
        // TODO: Load station data from API
        document.getElementById('edit-station-id').value = stationId;
        document.getElementById('edit-project-id').value = this.currentProjectId;
        document.getElementById('modal-title').textContent = 'Cấu hình Trạm';
        document.getElementById('btn-delete-station').style.display = 'inline-block';
        
        this.updateWizardStep();
        if (this.stationModal) this.stationModal.show();
    }

    updateWizardStep() {
        // Update wizard steps UI
        document.querySelectorAll('.wizard-step').forEach(step => {
            const stepNum = parseInt(step.dataset.step);
            if (stepNum === this.currentStep) {
                step.classList.add('active');
            } else {
                step.classList.remove('active');
            }
        });
        
        // Update wizard content
        document.querySelectorAll('.wizard-content').forEach(content => {
            const stepNum = parseInt(content.dataset.step);
            content.classList.toggle('active', stepNum === this.currentStep);
        });
        
        // Update buttons
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
        
        // Collect sensor data
        const sensors = {};
        ['gnss', 'rain', 'water', 'imu'].forEach(sensor => {
            const checkbox = document.getElementById(`edit-${sensor}`);
            if (checkbox && checkbox.checked) {
                const topic = document.getElementById(`topic-${sensor}`)?.value.trim();
                if (topic) {
                    sensors[sensor] = { topic };
                }
            }
        });
        
        // Collect thresholds
        const config = {
            water_warning: parseFloat(document.getElementById('cfg-water-warning').value),
            water_critical: parseFloat(document.getElementById('cfg-water-critical').value),
            rain_watch: parseFloat(document.getElementById('cfg-rain-watch').value),
            rain_warning: parseFloat(document.getElementById('cfg-rain-warning').value),
            rain_critical: parseFloat(document.getElementById('cfg-rain-critical').value),
            gnss_hdop: parseFloat(document.getElementById('cfg-gnss-hdop').value),
            gnss_steps: parseInt(document.getElementById('cfg-gnss-steps').value),
            gnss_streak: parseInt(document.getElementById('cfg-gnss-streak').value),
            gnss_timeout: parseInt(document.getElementById('cfg-gnss-timeout').value),
            imu_shock: parseFloat(document.getElementById('cfg-imu-shock').value)
        };
        
        try {
            const res = await fetch(`/api/admin/projects/${projectId}/stations`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    station_code: code,
                    name: name,
                    sensors: sensors,
                    config: config
                })
            });
            
            if (!res.ok) throw new Error('Failed to save station');
            
            window.toast?.success('✅ Lưu trạm thành công!');
            
            if (this.stationModal) this.stationModal.hide();
            this.loadStations(projectId);
            
        } catch (e) {
            console.error('Error saving station:', e);
            window.toast?.error('❌ Lỗi lưu trạm');
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
        // TODO: Load velocity classification data
        this.renderVelocityTable();
        if (this.velocityModal) this.velocityModal.show();
    }

    closeVelocityModal() {
        if (this.velocityModal) this.velocityModal.hide();
    }

    renderVelocityTable() {
        const tbody = document.getElementById('velocity-table-body');
        if (!tbody) return;
        
        // Default Cruden & Varnes classification
        const defaultData = [
            { name: 'Extremely Rapid', threshold: 5000, desc: '> 5 m/s' },
            { name: 'Very Rapid', threshold: 50, desc: '3 m/min to 5 m/s' },
            { name: 'Rapid', threshold: 0.5, desc: '1.8 m/h to 3 m/min' },
            { name: 'Moderate', threshold: 0.05, desc: '13 m/month to 1.8 m/h' },
            { name: 'Slow', threshold: 0.0005, desc: '1.6 m/year to 13 m/month' },
            { name: 'Very Slow', threshold: 0.00001, desc: '16 mm/year to 1.6 m/year' },
            { name: 'Extremely Slow', threshold: 0, desc: '< 16 mm/year' }
        ];
        
        tbody.innerHTML = defaultData.map(v => `
            <tr>
                <td><strong>${v.name}</strong></td>
                <td><code>${v.threshold}</code></td>
                <td class="text-muted">${v.desc}</td>
            </tr>
        `).join('');
    }

    applyVelocityConfig() {
        window.toast?.success('✅ Đã áp dụng cấu hình vận tốc');
        this.closeVelocityModal();
    }

    // =========================================================================
    // FETCH ORIGIN COORDINATES
    // =========================================================================
    
    async fetchLatestOrigin() {
        const topic = document.getElementById('topic-gnss')?.value.trim();
        if (!topic) {
            window.toast?.warning('Vui lòng nhập MQTT Topic trước');
            return;
        }
        
        const statusEl = document.getElementById('origin-status');
        const btnEl = document.getElementById('btn-fetch-origin');
        
        if (statusEl) statusEl.textContent = '⏳ Đang đợi dữ liệu GNSS...';
        if (btnEl) btnEl.disabled = true;
        
        // TODO: Implement MQTT subscription to get latest GNSS data
        // For now, simulate with timeout
        setTimeout(() => {
            // Simulate getting coordinates
            document.getElementById('origin-lat').value = '21.028511';
            document.getElementById('origin-lon').value = '105.804817';
            document.getElementById('origin-h').value = '15.234';
            
            if (statusEl) statusEl.textContent = '✅ Đã cập nhật tọa độ gốc';
            if (btnEl) btnEl.disabled = false;
            
            window.toast?.success('✅ Đã lấy tọa độ hiện tại');
        }, 2000);
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
            window.toast?.error('Không thể tải danh sách người dùng');
        }
    }

    renderUsers(users) {
        const tbody = document.getElementById('user-table-body');
        
        if (!tbody) return;

        if (users.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center py-4">
                        <i class="bi bi-inbox fs-1 text-muted"></i>
                        <p class="text-muted mt-2">Chưa có người dùng</p>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = users.map(u => `
            <tr>
                <td>${u.id}</td>
                <td><strong>${u.username}</strong></td>
                <td>${u.full_name || '--'}</td>
                <td>
                    <span class="badge bg-${u.role === 'admin' ? 'danger' : u.role === 'operator' ? 'warning' : 'info'}">
                        ${u.role.toUpperCase()}
                    </span>
                </td>
                <td>
                    <span class="badge bg-${u.is_active ? 'success' : 'secondary'}">
                        ${u.is_active ? 'Active' : 'Inactive'}
                    </span>
                </td>
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
            window.toast?.warning('Vui lòng nhập tài khoản và mật khẩu');
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
                    username,
                    password,
                    full_name: fullname,
                    role
                })
            });

            if (res.ok) {
                window.toast?.success('✅ Tạo tài khoản thành công!');
                
                const modal = bootstrap.Modal.getInstance(document.getElementById('addUserModal'));
                if (modal) modal.hide();
                
                document.getElementById('addUserForm').reset();
                this.loadUsers();
            } else {
                const error = await res.json();
                throw new Error(error.detail || 'Lỗi tạo tài khoản');
            }
        } catch (e) {
            console.error('Create user error:', e);
            window.toast?.error('❌ Lỗi: ' + e.message);
        }
    }

    async deleteUser(userId, username) {
        if (!confirm(`Bạn có chắc muốn xóa người dùng "${username}"?`)) return;

        try {
            const res = await fetch(`/api/admin/users/${userId}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (res.ok) {
                window.toast?.success('✅ Xóa thành công!');
                this.loadUsers();
            } else {
                throw new Error('Lỗi xóa người dùng');
            }
        } catch (e) {
            console.error('Delete user error:', e);
            window.toast?.error('❌ Lỗi: ' + e.message);
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
    console.log('✅ [ADMIN] DOM loaded, initializing AdminManager...');
    window.adminManager = new AdminManager();
    console.log('✅ [ADMIN] AdminManager initialized');
});