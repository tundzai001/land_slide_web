// =====================================================
// ADMIN MANAGER ( frontend/js/admin-manager.js )
// =====================================================

class AdminManager {
    constructor() {
        this.token = localStorage.getItem('token');
        this.stationModal = null;
        this.currentStationId = null;
        this.isEditMode = false;
        this.currentStep = 1;
        this.totalSteps = 3;
        this.velocityModal = null; // Instance của modal phụ
        this.tempClassificationData = []; // Biến tạm lưu dữ liệu bảng
        
        if (!this.token) {
            window.location.href = '/pages/login.html';
            return;
        }

        this.init();
    }

    init() {
        const modalEl = document.getElementById('stationConfigModal');
        if (modalEl) {
            this.stationModal = new bootstrap.Modal(modalEl);
        }

        this.loadUsers();
        this.loadStations();

        const vModalEl = document.getElementById('velocityConfigModal');
        if (vModalEl) {
            this.velocityModal = new bootstrap.Modal(vModalEl);
        }

        const logoutBtn = document.getElementById('logout-btn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this.logout();
            });
        }

        this.setupTabHandlers();
        this.setupWizardControls();
        this.setupSensorListeners();
    }

    setupTabHandlers() {
        const tabButtons = document.querySelectorAll('#mainTabs button[data-bs-toggle="tab"]');
        tabButtons.forEach(btn => {
            btn.addEventListener('shown.bs.tab', (e) => {
                const targetId = e.target.getAttribute('data-bs-target');
                if (targetId === '#tab-devices') {
                    this.loadStations();
                }
            });
        });
    }

    setupWizardControls() {
        const btnNext = document.getElementById('btn-wizard-next');
        const btnBack = document.getElementById('btn-wizard-back');

        if (btnNext) {
            btnNext.addEventListener('click', () => this.nextStep());
        }

        if (btnBack) {
            btnBack.addEventListener('click', () => this.previousStep());
        }
    }

    setupSensorListeners() {
        const sensors = ['gnss', 'rain', 'water', 'imu'];
        
        sensors.forEach(type => {
            const checkbox = document.getElementById(`edit-${type}`);
            if (checkbox) {
                checkbox.addEventListener('change', () => {
                    this.toggleSensorSections();
                });
            }
        });
    }

    toggleSensorSections() {
        const sensors = ['gnss', 'rain', 'water', 'imu'];
        let hasAnySensor = false;

        sensors.forEach(type => {
            const enabled = document.getElementById(`edit-${type}`).checked;
            const section = document.getElementById(`mqtt-${type}-section`);
            
            if (section) {
                if (enabled) {
                    section.style.display = 'block';
                    setTimeout(() => {
                        section.style.animation = 'slideDown 0.3s ease-out';
                    }, 10);
                } else {
                    section.style.display = 'none';
                }
            }

            if (enabled) hasAnySensor = true;
        });

        const emptyState = document.getElementById('mqtt-empty-state');
        if (emptyState) {
            emptyState.style.display = hasAnySensor ? 'none' : 'block';
        }
    }

    nextStep() {
        // Validation
        if (this.currentStep === 1) {
            const code = document.getElementById('edit-code').value.trim();
            const name = document.getElementById('edit-name').value.trim();
            
            if (!code || !name) {
                window.toast?.warning('⚠️ Vui lòng nhập đầy đủ mã trạm và tên trạm!');
                return;
            }
        }
        
        if (this.currentStep < this.totalSteps) {
            this.currentStep++;
            this.updateWizardUI();
        }
    }

    previousStep() {
        if (this.currentStep > 1) {
            this.currentStep--;
            this.updateWizardUI();
        }
    }

    updateWizardUI() {
        document.querySelectorAll('.wizard-step').forEach((step, idx) => {
            const stepNum = idx + 1;
            step.classList.remove('active', 'completed');
            
            if (stepNum < this.currentStep) {
                step.classList.add('completed');
            } else if (stepNum === this.currentStep) {
                step.classList.add('active');
            }
        });

        document.querySelectorAll('.wizard-content').forEach(content => {
            const stepNum = parseInt(content.getAttribute('data-step'));
            content.classList.toggle('active', stepNum === this.currentStep);
        });

        const btnBack = document.getElementById('btn-wizard-back');
        const btnNext = document.getElementById('btn-wizard-next');
        const btnSave = document.getElementById('btn-wizard-save');

        if (btnBack) btnBack.style.display = this.currentStep === 1 ? 'none' : 'block';
        if (btnNext) btnNext.style.display = this.currentStep === this.totalSteps ? 'none' : 'block';
        if (btnSave) btnSave.style.display = this.currentStep === this.totalSteps ? 'block' : 'none';
    }

    // Mở Modal phụ và render dữ liệu
    openVelocityModal() {
        const tbody = document.getElementById('velocity-table-body');
        tbody.innerHTML = '';

        // Nếu không có dữ liệu, tạo mẫu mặc định
        if (!this.tempClassificationData || this.tempClassificationData.length === 0) {
            this.tempClassificationData = [
                { name: "Extremely rapid", mm_giay: 5000, desc: "> 5 m/s" },
                { name: "Very rapid", mm_giay: 50, desc: "3 m/min to 5 m/s" },
                { name: "Rapid", mm_giay: 0.5, desc: "1.8 m/h to 3 m/min" },
                { name: "Moderate", mm_giay: 0.0006, desc: "13 mm/mo to 1.8 m/h" },
                { name: "Slow", mm_giay: 0.00005, desc: "1.6 m/y to 13 mm/mo" },
                { name: "Very slow", mm_giay: 0.000001, desc: "16 mm/y to 1.6 m/y" },
                { name: "Extremely slow", mm_giay: 0, desc: "< 16 mm/y" }
            ];
        }

        // Render từng dòng
        this.tempClassificationData.forEach((row, index) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>
                    <input type="text" class="form-control form-control-sm fw-bold" 
                           value="${row.name}" id="vel-name-${index}">
                </td>
                <td>
                    <div class="input-group input-group-sm">
                        <input type="number" step="0.000000001" class="form-control" 
                               value="${row.mm_giay}" id="vel-val-${index}">
                        <span class="input-group-text">mm/s</span>
                    </div>
                </td>
                <td>
                    <input type="text" class="form-control form-control-sm text-muted" 
                           value="${row.desc || ''}" id="vel-desc-${index}">
                </td>
            `;
            tbody.appendChild(tr);
        });

        this.velocityModal.show();
    }

    // Đóng Modal phụ
    closeVelocityModal() {
        this.velocityModal.hide();
    }

    // Lưu dữ liệu từ bảng Modal phụ về biến tạm
    applyVelocityConfig() {
        const newTable = [];
        const rows = document.getElementById('velocity-table-body').children;

        for (let i = 0; i < rows.length; i++) {
            const name = document.getElementById(`vel-name-${i}`).value;
            const val = parseFloat(document.getElementById(`vel-val-${i}`).value);
            const desc = document.getElementById(`vel-desc-${i}`).value;

            if (name && !isNaN(val)) {
                newTable.push({
                    name: name,
                    mm_giay: val,
                    desc: desc,
                    // Tự động tính các đơn vị khác nếu cần thiết cho backend
                    m_giay: val / 1000.0
                });
            }
        }

        // Sắp xếp lại từ lớn đến bé để đảm bảo logic so sánh đúng
        newTable.sort((a, b) => b.mm_giay - a.mm_giay); 

        this.tempClassificationData = newTable;
        this.velocityModal.hide();
        
        if (window.toast) window.toast.success('Đã cập nhật bảng vận tốc tạm thời (Nhấn Lưu cấu hình để hoàn tất)');
    }

    // ========================================
    // USER MANAGEMENT
    // ========================================

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

    // ========================================
    // STATION MANAGEMENT
    // ========================================

    async loadStations() {
        try {
            const res = await fetch('/api/stations', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) throw new Error('Failed to load stations');

            const stations = await res.json();
            this.renderStations(stations);
        } catch (e) {
            console.error('Error loading stations:', e);
            window.toast?.error('Không thể tải danh sách trạm');
        }
    }

    renderStations(stations) {
        const list = document.getElementById('station-list');
        
        if (!list) return;

        if (stations.length === 0) {
            list.innerHTML = `
                <div class="col-12 text-center py-5">
                    <i class="bi bi-hdd-network fs-1 text-muted"></i>
                    <p class="text-muted mt-2">Chưa có trạm nào</p>
                </div>
            `;
            return;
        }

        list.innerHTML = stations.map(s => {
            // ✅ Xử lý hiển thị tọa độ
            let locationBadge = '';
            if (s.location && s.location.lat !== undefined && s.location.lon !== undefined) {
                // Làm tròn 5 số thập phân cho gọn
                const lat = parseFloat(s.location.lat).toFixed(5);
                const lon = parseFloat(s.location.lon).toFixed(5);
                locationBadge = `
                    <span class="badge bg-light text-dark border ms-2" title="Tọa độ tự động tính toán">
                        <i class="bi bi-geo-alt-fill text-danger me-1"></i>${lat}, ${lon}
                    </span>
                `;
            } else {
                locationBadge = `<span class="badge bg-light text-muted border ms-2"><i class="bi bi-question-circle me-1"></i>No Loc</span>`;
            }

            return `
            <div class="col-md-6 col-xl-4">
                <div class="station-card" onclick="window.adminManager.openStationConfig(${s.id})">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <h5 class="mb-0 text-truncate" style="max-width: 70%;" title="${s.name}">${s.name}</h5>
                        <span class="badge bg-${s.status === 'online' ? 'success' : 'secondary'}">
                            ${s.status || 'offline'}
                        </span>
                    </div>
                    
                    <!-- ✅ Hiển thị Mã trạm + Tọa độ -->
                    <div class="d-flex align-items-center mb-3">
                        <div class="text-muted small fw-bold">${s.station_code}</div>
                        ${locationBadge}
                    </div>

                    <div>
                        <span class="sensor-badge ${s.has_gnss ? 'active' : ''}">
                            <i class="bi bi-geo-alt"></i> GNSS
                        </span>
                        <span class="sensor-badge ${s.has_rain ? 'active' : ''}">
                            <i class="bi bi-cloud-rain"></i> RAIN
                        </span>
                        <span class="sensor-badge ${s.has_water ? 'active' : ''}">
                            <i class="bi bi-water"></i> WATER
                        </span>
                        <span class="sensor-badge ${s.has_imu ? 'active' : ''}">
                            <i class="bi bi-compass"></i> IMU
                        </span>
                    </div>
                </div>
            </div>
            `;
        }).join('');
    }

    openAddStationModal() {
        this.isEditMode = false;
        this.currentStationId = null;
        this.currentStep = 1;
        
        document.getElementById('modal-title').textContent = 'Thêm Trạm Mới';
        document.getElementById('edit-code').readOnly = false;
        document.getElementById('btn-delete-station').style.display = 'none';
        
        document.getElementById('stationConfigForm').reset();
        document.getElementById('edit-station-id').value = '';
        
        ['gnss', 'rain', 'water', 'imu'].forEach(type => {
            document.getElementById(`edit-${type}`).checked = false;
        });
        
        document.getElementById('origin-lat').value = '';
        document.getElementById('origin-lon').value = '';
        document.getElementById('origin-h').value = '';
        document.getElementById('origin-status').textContent = 'Chưa có dữ liệu gốc';
        document.getElementById('origin-status').className = 'text-muted small';
        
        this.toggleSensorSections();
        this.updateWizardUI();
        
        if (this.stationModal) {
            this.stationModal.show();
        }
    }

    async openStationConfig(stationId) {
        this.isEditMode = true;
        this.currentStationId = stationId;
        this.currentStep = 1;
        
        document.getElementById('modal-title').textContent = 'Cấu hình Trạm';
        document.getElementById('edit-code').readOnly = true;
        document.getElementById('btn-delete-station').style.display = 'block';
        
        try {
            const res = await fetch(`/api/stations/${stationId}/detail`, {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) throw new Error('Failed to load station');

            const data = await res.json();
            
            // 1. Load thông tin cơ bản
            document.getElementById('edit-station-id').value = data.id;
            document.getElementById('edit-code').value = data.station_code || '';
            document.getElementById('edit-name').value = data.name || '';
            
            document.getElementById('edit-gnss').checked = data.has_gnss || false;
            document.getElementById('edit-rain').checked = data.has_rain || false;
            document.getElementById('edit-water').checked = data.has_water || false;
            document.getElementById('edit-imu').checked = data.has_imu || false;
            
            this.toggleSensorSections();
            
            // 2. Load Config Chi tiết
            const config = data.config || {};
            const mqtt = config.mqtt_topics || {};
            this.tempClassificationData = config.GNSS_Classification || [];

            // --- MQTT Topics ---
            document.getElementById('topic-gnss').value = mqtt.gnss || '';
            document.getElementById('topic-rain').value = mqtt.rain || '';
            document.getElementById('topic-water').value = mqtt.water || '';
            document.getElementById('topic-imu').value = mqtt.imu || '';
            
            // --- Water & Displacement (Hỗ trợ fallback config cũ 'thresholds') ---
            const waterCfg = config.Water || config.thresholds || {};
            document.getElementById('cfg-water-warning').value = waterCfg.warning_threshold || 0.15;
            document.getElementById('cfg-water-critical').value = waterCfg.critical_threshold || 0.30;
            
            // --- Rain Alerting (Hỗ trợ fallback config cũ 'rain') ---
            const rainCfg = config.RainAlerting || config.rain || {};
            // Ưu tiên key mới, fallback về key cũ, cuối cùng là default
            document.getElementById('cfg-rain-watch').value = rainCfg.rain_intensity_watch_threshold || rainCfg.watch || 10.0;
            document.getElementById('cfg-rain-warning').value = rainCfg.rain_intensity_warning_threshold || rainCfg.warning || 25.0;
            document.getElementById('cfg-rain-critical').value = rainCfg.rain_intensity_critical_threshold || rainCfg.critical || 50.0;
            
            // --- GNSS Advanced Alerting ---
            const gnssCfg = config.GnssAlerting || config.gnss || {};
            document.getElementById('cfg-gnss-hdop').value = gnssCfg.gnss_max_hdop || 4.0;
            document.getElementById('cfg-gnss-steps').value = gnssCfg.gnss_confirm_steps || 3;
            document.getElementById('cfg-gnss-streak').value = gnssCfg.gnss_safe_streak || 10;
            document.getElementById('cfg-gnss-timeout').value = gnssCfg.gnss_degraded_timeout || 300;

            // --- IMU Alerting ---
            const imuCfg = config.ImuAlerting || config.imu || {};
            document.getElementById('cfg-imu-shock').value = imuCfg.shock_threshold_ms2 || 5.0;
            
            this.updateWizardUI();
            
            if (this.stationModal) {
                this.stationModal.show();
            }
        } catch (e) {
            console.error('Error loading station:', e);
            window.toast?.error('❌ Lỗi tải dữ liệu trạm');
        }
    }

    async fetchLatestOrigin() {
        const topic = document.getElementById('topic-gnss').value.trim();
        
        if (!topic) {
            window.toast?.warning('⚠️ Vui lòng nhập MQTT Topic trước!');
            return;
        }
        
        const btn = document.getElementById('btn-fetch-origin');
        const status = document.getElementById('origin-status');
        
        try {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Đang subscribe...';
            status.textContent = '📡 Đang subscribe vào topic MQTT và chờ dữ liệu GNSS...';
            status.className = 'small text-info';
            
            const res = await fetch('/api/admin/gnss/fetch-live-origin', {
                method: 'POST',
                headers: { 
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ topic: topic })
            });
            
            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || 'Không thể lấy dữ liệu GNSS');
            }
            
            const data = await res.json();
            
            document.getElementById('origin-lat').value = data.lat.toFixed(8);
            document.getElementById('origin-lon').value = data.lon.toFixed(8);
            document.getElementById('origin-h').value = data.h.toFixed(3);
            
            status.textContent = `✅ ${data.message}`;
            status.className = 'small text-success';
            
            window.toast?.success(`✅ Đã lấy tọa độ! Fix: ${data.fix_quality}, Satellites: ${data.num_sats}`);
            
        } catch (e) {
            console.error('Fetch origin error:', e);
            status.textContent = '❌ Lỗi: ' + e.message;
            status.className = 'small text-danger';
            window.toast?.error('❌ ' + e.message);
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-arrow-repeat me-1"></i> Lấy tọa độ hiện tại';
        }
    }

    async saveStation() {
        console.log('🔵 [SAVE] Starting save process...');

        // 1. Lấy giá trị tọa độ từ form (nếu có để khóa Origin)
        const originLat = document.getElementById('origin-lat').value;
        const originLon = document.getElementById('origin-lon').value;
        const originH = document.getElementById('origin-h').value;

        // 2. Tạo object location chuẩn
        let finalLocation = { lat: 0, lon: 0, address: "N/A" };
        
        // Nếu có bật GNSS và đã fetch được tọa độ -> Dùng luôn làm location hiển thị
        if (document.getElementById('edit-gnss').checked && originLat && originLon) {
            finalLocation = {
                lat: parseFloat(originLat),
                lon: parseFloat(originLon),
                address: "GNSS Origin"
            };
        }
        
        // 3. Xây dựng Payload theo cấu trúc MỚI
        const payload = {
            station_code: document.getElementById('edit-code').value.trim(),
            name: document.getElementById('edit-name').value.trim(),
            location: finalLocation,
            has_gnss: document.getElementById('edit-gnss').checked,
            has_rain: document.getElementById('edit-rain').checked,
            has_water: document.getElementById('edit-water').checked,
            has_imu: document.getElementById('edit-imu').checked,
            
            // Cấu trúc config lồng nhau
            config: {
                mqtt_topics: {
                    gnss: document.getElementById('topic-gnss').value.trim(),
                    rain: document.getElementById('topic-rain').value.trim(),
                    water: document.getElementById('topic-water').value.trim(),
                    imu: document.getElementById('topic-imu').value.trim()
                },
                
                // Nhóm Water
                Water: {
                    warning_threshold: parseFloat(document.getElementById('cfg-water-warning').value),
                    critical_threshold: parseFloat(document.getElementById('cfg-water-critical').value)
                },

                // Nhóm RainAlerting
                RainAlerting: {
                    rain_intensity_watch_threshold: parseFloat(document.getElementById('cfg-rain-watch').value),
                    rain_intensity_warning_threshold: parseFloat(document.getElementById('cfg-rain-warning').value),
                    rain_intensity_critical_threshold: parseFloat(document.getElementById('cfg-rain-critical').value)
                },

                // Nhóm GnssAlerting
                GnssAlerting: {
                    gnss_max_hdop: parseFloat(document.getElementById('cfg-gnss-hdop').value),
                    gnss_confirm_steps: parseInt(document.getElementById('cfg-gnss-steps').value),
                    gnss_safe_streak: parseInt(document.getElementById('cfg-gnss-streak').value),
                    gnss_degraded_timeout: parseInt(document.getElementById('cfg-gnss-timeout').value)
                },

                // Nhóm ImuAlerting
                ImuAlerting: {
                    shock_threshold_ms2: parseFloat(document.getElementById('cfg-imu-shock').value)
                },
                
                GNSS_Classification: this.tempClassificationData
            }
        };

        // 4. Xử lý GNSS Origin (Logic cũ giữ nguyên)
        if (payload.has_gnss) {
            if (originLat && originLon) {
                payload.config.gnss_origin = {
                    lat: parseFloat(originLat),
                    lon: parseFloat(originLon),
                    h: parseFloat(originH) || 0
                };
                console.log('✅ [SAVE] GNSS origin included:', payload.config.gnss_origin);
            } else if (this.isEditMode) {
                const confirm = window.confirm(
                    '⚠️ Bạn chưa khóa tọa độ gốc GNSS.\n\n' +
                    'Hệ thống cần tọa độ gốc để tính toán chuyển dịch.\n\n' +
                    'Tiếp tục lưu?'
                );
                if (!confirm) return;
            }
        }

        console.log('📦 [SAVE] Payload:', JSON.stringify(payload, null, 2));

        // 5. Gửi Request (Logic cũ giữ nguyên)
        try {
            let url, method;
            
            if (this.isEditMode) {
                url = `/api/admin/stations/${this.currentStationId}/config`;
                method = 'PUT';
            } else {
                url = '/api/stations';
                method = 'POST';
            }

            const res = await fetch(url, {
                method: method,
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                const savedStation = await res.json();
                
                let msg = '✅ Lưu cấu hình thành công!';
                if (savedStation.location && savedStation.location.lat) {
                    const lat = parseFloat(savedStation.location.lat).toFixed(6);
                    const lon = parseFloat(savedStation.location.lon).toFixed(6);
                    msg += `<br><small>📍 Tọa độ: <b>${lat}, ${lon}</b></small>`;
                }

                if (window.toast) window.toast.success(msg, 5000);

                // Reset modal state if creating new
                if (!this.isEditMode && savedStation.id) {
                    this.currentStationId = savedStation.id;
                    this.isEditMode = true;
                    document.getElementById('modal-title').textContent = 'Cấu hình Trạm';
                    document.getElementById('btn-delete-station').style.display = 'block';
                    document.getElementById('edit-code').readOnly = true;
                }
                
                if (this.stationModal) this.stationModal.hide();
                this.loadStations();
            } else {
                const error = await res.json();
                throw new Error(error.detail || 'Lỗi lưu cấu hình');
            }
        } catch (e) {
            console.error('Save error:', e);
            window.toast?.error('❌ Lỗi: ' + e.message);
        }
    }

    async deleteStation() {
        const stationCode = document.getElementById('edit-code')?.value || 'trạm này';

        if (!confirm(`⚠️ CẢNH BÁO: Xóa ${stationCode}?\n\nTất cả dữ liệu cảm biến sẽ bị xóa vĩnh viễn!`)) {
            return;
        }

        try {
            const res = await fetch(`/api/admin/stations/${this.currentStationId}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (res.ok) {
                window.toast?.success("✅ Đã xóa trạm!");

                if (this.stationModal) {
                    this.stationModal.hide();
                }

                this.loadStations();
            } else {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi xóa trạm');
            }
        } catch (e) {
            console.error('Delete station error:', e);
            window.toast?.error("❌ Lỗi: " + e.message);
        }
    }

    logout() {
        localStorage.removeItem('token');
        window.location.href = '/';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    console.log('✅ [ADMIN] DOM loaded, initializing AdminManager...');
    window.adminManager = new AdminManager();
    console.log('✅ [ADMIN] AdminManager initialized');
});