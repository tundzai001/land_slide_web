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
        this.totalSteps = 4;
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
            console.log('[SPA-NAV] admin no token redirect landing-login', {
                path: window.location.pathname,
                search: window.location.search,
            });
            window.SPA_SUPPRESS_AUTO_MAP_ON_LANDING = true;
            sessionStorage.setItem('loginReturnView', 'admin');
            sessionStorage.setItem('openLandingLogin', 'true');
            window.location.href = '/';
            return;
        }

        this.init();
        this.setupWebSocketListener();
    }

    /** Lắng nghe các sự kiện realtime từ Server */
    parseVn2000CentralMeridian(rawValue) {
        const raw = String(rawValue ?? '').trim().replace(',', '.');
        if (!raw) return { value: 105.0, format: 'default' };

        const dmsMatch = raw.match(/^([+-]?\d+(?:\.\d+)?)\s*(?:°|d|\s)\s*(\d+(?:\.\d+)?)\s*(?:'|m)?$/i);
        if (dmsMatch) {
            const deg = Number(dmsMatch[1]);
            const minutes = Number(dmsMatch[2]);
            if (Number.isFinite(deg) && Number.isFinite(minutes) && minutes >= 0 && minutes < 60) {
                const sign = deg < 0 ? -1 : 1;
                return { value: sign * (Math.abs(deg) + minutes / 60), format: 'deg_min' };
            }
        }

        const compactMatch = raw.match(/^([+-]?\d+)\.(\d{2})$/);
        if (compactMatch) {
            const deg = Number(compactMatch[1]);
            const minutes = Number(compactMatch[2]);
            if (Number.isFinite(deg) && minutes > 0 && minutes < 60) {
                const sign = deg < 0 ? -1 : 1;
                return { value: sign * (Math.abs(deg) + minutes / 60), format: 'deg_min_compact' };
            }
        }

        const decimal = Number(raw);
        return { value: Number.isFinite(decimal) ? decimal : 105.0, format: 'decimal_deg' };
    }

    setupWebSocketListener() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/admin?token=${this.token}`;

        try {
            this.ws = new WebSocket(wsUrl);
            this.ws.onmessage = (event) => {
                const message = JSON.parse(event.data);
                if (message.type === 'origin_locked_event' && message.station_id == this.currentStationId) {
                    console.log('🎯 GNSS Origin Locked via WebSocket:', message.data);

                    // Cập nhật ngay lập tức lên UI
                    const latEl = document.getElementById('origin-lat');
                    const lonEl = document.getElementById('origin-lon');
                    const hEl = document.getElementById('origin-h');
                    const statusEl = document.getElementById('origin-status');

                    if (latEl) latEl.value = message.data.lat;
                    if (lonEl) lonEl.value = message.data.lon;
                    if (hEl) hEl.value = message.data.h;

                    if (statusEl) {
                        statusEl.innerHTML = '<span class="text-success fw-bold"><i class="bi bi-check-circle-fill me-1"></i> Đã tự động cập nhật điểm gốc mới!</span>';
                        statusEl.className = 'small mt-1';
                    }

                    window.toast?.success('Thiết bị đã tự động khóa điểm gốc mới và cập nhật lên màn hình!');
                } else if (message.type === 'gnss_adjustment_step') {
                    const step = message.data;
                    const terminal = document.getElementById('gnss-terminal-output');
                    if (terminal) {
                        const now = new Date().toLocaleTimeString('vi-VN');
                        let colorClass = 'text-info';
                        if (step.step === 5) colorClass = 'text-success fw-bold';
                        if (step.error) colorClass = 'text-danger fw-bold';
                        
                        const div = document.createElement('div');
                        div.className = 'mb-2';
                        div.innerHTML = `<span class="text-secondary">[${now}]</span> <span class="${colorClass}">[Bước ${step.step}] ${step.title}:</span> ${step.message}`;
                        
                        terminal.appendChild(div);
                        terminal.scrollTop = terminal.scrollHeight;
                        
                        if (step.step === 5 && !step.error && document.getElementById('gnssTerminalModal')?.classList.contains('show')) {
                            window.toast?.success(step.message);
                        }
                    }
                }
            };

            this.ws.onclose = () => {
                // Thử kết nối lại sau 5 giây nếu mất kết nối
                setTimeout(() => this.setupWebSocketListener(), 5000);
            };
        } catch (e) {
            console.error('WebSocket connection error:', e);
        }
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
        } else if (tabId === 'tab-rescue') {
            this.loadRescueRequests?.();
        }
    }

    init() {
        console.log('[ADMIN] Initializing...');

        // Initialize modals
        const stationModalEl = document.getElementById('stationConfigModal');
        if (stationModalEl) {
            // Keep wizard stable while configuring: avoid accidental close by backdrop click/Esc.
            this.stationModal = new bootstrap.Modal(stationModalEl, {
                backdrop: 'static',
                keyboard: false
            });

            const stationForm = document.getElementById('stationConfigForm');
            if (stationForm && !stationForm.dataset.boundNoSubmit) {
                stationForm.addEventListener('submit', (e) => {
                    e.preventDefault();
                });
                stationForm.dataset.boundNoSubmit = '1';
            }

            // Always open the wizard from top to avoid inherited scroll position.
            stationModalEl.addEventListener('shown.bs.modal', () => {
                const body = stationModalEl.querySelector('.modal-body');
                if (body) body.scrollTop = 0;

                // Defensive re-sync in case stale DOM state leaked from previous opens.
                if (![1, 2, 3].includes(this.currentStep)) {
                    this.currentStep = 1;
                }
                this.updateWizardStep();
                this.ensureWizardButtonInteractivity();
            });

            this.bindWizardButtons();
            this.bindWizardButtonFallback();
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
                const roleEl = document.getElementById('new-role');
                const groupEl = document.getElementById('project-assign-group');
                if (groupEl) {
                    const role = roleEl?.value || 'viewer';
                    groupEl.style.display = (role === 'operator' || role === 'viewer') ? 'block' : 'none';
                }
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

        setInterval(() => {
            const rescueTab = document.getElementById('tab-rescue');
            if (rescueTab && rescueTab.classList.contains('active')) {
                this.loadRescueRequests(true);
            }
        }, 20000);

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

    /** Apply operator restrictions â€” hide Users/DB/System tabs, but allow editing stations in assigned projects */
    applyOperatorRestrictions() {
        console.log('🔧 Applying operator restrictions');

        // Hide sidebar tabs: Users, Database, System (keep Projects and Pi Devices)
        document.querySelectorAll('.admin-sidebar .nav-item').forEach(item => {
            const link = item.querySelector('[data-tab]');
            if (link) {
                const tab = link.getAttribute('data-tab');
                if (['tab-users', 'tab-database', 'tab-system', 'tab-rescue'].includes(tab)) {
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

    async loadRescueRequests(silent = false) {
        const body = document.getElementById('rescue-requests-body');
        if (!body) return;
        try {
            const res = await fetch('/api/admin/rescue-requests?limit=100', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const rows = await res.json();
            this.renderRescueRequests(rows || []);
        } catch (e) {
            if (!silent) window.toast?.error('Không tải được danh sách rescue requests');
            body.innerHTML = '<tr><td colspan="8" class="text-danger">Lỗi tải dữ liệu rescue requests</td></tr>';
            console.error('loadRescueRequests error:', e);
        }
    }

    renderRescueRequests(rows) {
        const body = document.getElementById('rescue-requests-body');
        if (!body) return;

        this.updateRescueSummary(rows);

        if (!Array.isArray(rows) || rows.length === 0) {
            body.innerHTML = '<tr><td colspan="8" class="text-muted">Chưa có yêu cầu cứu hộ</td></tr>';
            return;
        }

        const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (m) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[m]));

        body.innerHTML = rows.map(r => {
            const ts = r.created_at ? new Date(r.created_at * 1000).toLocaleString('vi-VN') : '--';
            const mapsLink = Number.isFinite(Number(r.latitude)) && Number.isFinite(Number(r.longitude))
                ? `<a href="https://maps.google.com/?q=${r.latitude},${r.longitude}" target="_blank" rel="noopener">${Number(r.latitude).toFixed(6)}, ${Number(r.longitude).toFixed(6)}</a>`
                : '--';

            const rescueTypeLabelMap = {
                can_cuu_ho: 'Cần cứu hộ',
                can_nhu_yeu_pham: 'Cần nhu yếu phẩm',
                can_cuu_ho_xe: 'Cần cứu hộ xe',
                khac: 'Khác'
            };
            const rescueType = String(r.rescue_type || '').toLowerCase();
            const rescueTypeLabel = rescueTypeLabelMap[rescueType] || '--';
            const sourceLink = String(r.source_link || '').trim();
            const isSafeSourceLink = /^https?:\/\//i.test(sourceLink);
            const sourceLinkHtml = (sourceLink && isSafeSourceLink)
                ? `<a href="${esc(sourceLink)}" target="_blank" rel="noopener">Mở link nguồn</a>`
                : '<span class="text-muted">--</span>';
            const provinceCity = String(r.province_city || '').trim() || '--';
            const imageUrl = String(r.image_url || r.image_data_url || '').trim();
            const imageHtml = imageUrl
                ? `<a href="${esc(imageUrl)}" target="_blank" rel="noopener"><img src="${esc(imageUrl)}" alt="rescue-evidence" style="width:72px;height:72px;object-fit:cover;border-radius:8px;border:1px solid #ddd;"></a>`
                : '<span class="text-muted">--</span>';

            const detailCellHtml = `
                <div class="small mb-1"><strong>Mô tả:</strong> ${esc(r.message || '--')}</div>
                <div class="small mb-1"><strong>Phân loại:</strong> ${esc(rescueTypeLabel)}</div>
                <div class="small mb-1"><strong>Tỉnh/TP:</strong> ${esc(provinceCity)}</div>
                <div class="small mb-1"><strong>Nguồn:</strong> ${sourceLinkHtml}</div>
                <div class="small"><strong>Ảnh:</strong> ${imageHtml}</div>
            `;

            const statusBadge = r.status === 'resolved'
                ? '<span class="badge bg-success">resolved</span>'
                : r.status === 'rejected'
                    ? '<span class="badge bg-secondary">rejected</span>'
                    : '<span class="badge bg-danger">pending</span>';

            const actionBtns = r.status === 'pending'
                ? `<div class="btn-group btn-group-sm" role="group">
                        <button class="btn btn-outline-success" onclick="window.adminManager.updateRescueRequestStatus(${r.id}, 'resolved')">Done</button>
                        <button class="btn btn-outline-secondary" onclick="window.adminManager.updateRescueRequestStatus(${r.id}, 'rejected')">Reject</button>
                   </div>`
                : `<button class="btn btn-sm btn-outline-danger" onclick="window.adminManager.deleteRescueRequest(${r.id})">
                        <i class="bi bi-trash me-1"></i>Xóa
                   </button>`;

            return `<tr>
                <td>${r.id}</td>
                <td>${esc(ts)}</td>
                <td>${esc(r.requester_name || '--')}</td>
                <td>${esc(r.phone || '--')}</td>
                <td>${mapsLink}</td>
                <td>${detailCellHtml}</td>
                <td>${statusBadge}</td>
                <td>${actionBtns}</td>
            </tr>`;
        }).join('');
    }

    updateRescueSummary(rows) {
        const totalEl = document.getElementById('rescue-count-total');
        const pendingEl = document.getElementById('rescue-count-pending');
        const resolvedEl = document.getElementById('rescue-count-resolved');
        const rejectedEl = document.getElementById('rescue-count-rejected');

        const safeRows = Array.isArray(rows) ? rows : [];
        const counts = safeRows.reduce((acc, row) => {
            const status = String(row?.status || '').toLowerCase();
            if (status === 'pending') acc.pending += 1;
            else if (status === 'resolved') acc.resolved += 1;
            else if (status === 'rejected') acc.rejected += 1;
            return acc;
        }, { pending: 0, resolved: 0, rejected: 0 });

        if (totalEl) totalEl.textContent = String(safeRows.length);
        if (pendingEl) pendingEl.textContent = String(counts.pending);
        if (resolvedEl) resolvedEl.textContent = String(counts.resolved);
        if (rejectedEl) rejectedEl.textContent = String(counts.rejected);
    }

    async updateRescueRequestStatus(requestId, status) {
        try {
            const res = await fetch(`/api/admin/rescue-requests/${requestId}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${this.token}`
                },
                body: JSON.stringify({ status })
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            window.toast?.success(`Rescue request #${requestId} -> ${status}`);
            await this.loadRescueRequests(true);
        } catch (e) {
            window.toast?.error('Cập nhật trạng thái rescue request thất bại');
            console.error('updateRescueRequestStatus error:', e);
        }
    }

    async deleteRescueRequest(requestId) {
        const ok = window.confirm(`Xóa rescue request #${requestId}? Chỉ nên xóa các case đã xử lý.`);
        if (!ok) return;

        try {
            const res = await fetch(`/api/admin/rescue-requests/${requestId}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${this.token}`
                }
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err?.detail || `HTTP ${res.status}`);
            }

            window.toast?.success(`Đã xóa rescue request #${requestId}`);
            await this.loadRescueRequests(true);
        } catch (e) {
            window.toast?.error(`Xóa rescue request thất bại: ${e.message}`);
            console.error('deleteRescueRequest error:', e);
        }
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
                                ${p.location ? `<p class="text-muted small mb-0 mt-2"><i class="bi bi-geo-alt"></i> ${typeof p.location === 'string' ? p.location : (p.location.address || p.location.source || `${p.location.lat ?? ''}, ${p.location.lon ?? ''}`)}</p>` : ''}

                            </div>
                            <div class="card-footer bg-transparent border-top-0 position-relative" style="z-index: 2;">
                                <div class="d-flex gap-2">
                                    <button class="btn btn-sm btn-outline-primary flex-1" onclick="event.stopPropagation(); window.adminManager.loadStations(${p.id})">
                                        <i class="bi bi-box-arrow-in-right me-1"></i> ACCESS
                                    </button>
                                    <button class="btn btn-sm btn-outline-success" onclick="event.stopPropagation(); window.adminManager.openProjectConfigModal(${p.id})" title="Cấu hình dự án">
                                        <i class="bi bi-gear-fill"></i>
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
    // PROJECT CONFIG (CORS Base & GNSS Clusters)
    // =========================================================================

    async openProjectConfigModal(projectId) {
        const project = (this.projectsData || []).find(p => p.id === projectId);
        if (!project) return;

        this.currentProjectId = projectId;
        this.projectStationsData = [];

        // 1. Fetch stations belonging to this project
        try {
            const res = await fetch(`/api/admin/projects/${projectId}/stations`, {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (res.ok) {
                this.projectStationsData = await res.json();
            }
        } catch (e) {
            console.error('Error fetching project stations:', e);
        }
        // 2. Auto load CORS stations
        await this.fetchCorsStations();

        // 3. Populate Clusters
        const clusters = project.gnss_clusters || [];
        const clustersContainer = document.getElementById('project-gnss-clusters-container');
        clustersContainer.innerHTML = '';
        
        if (clusters.length === 0) {
            this.addClusterRow(clustersContainer);
        } else {
            clusters.forEach(c => this.addClusterRow(clustersContainer, c.name, c.description, c.base_station, c.stations, c.base_stream, c));
        }

        document.getElementById('projectConfigModalTitle').textContent = `Cấu hình dự án: ${project.name}`;
        
        if (!this.projectConfigModal) {
            this.projectConfigModal = new bootstrap.Modal(document.getElementById('projectConfigModal'));
        }
        this.projectConfigModal.show();
    }

    addClusterRow(container, name = '', desc = '', base_station_code = '', stations = [], base_stream = '', clusterConfig = {}) {
        const row = document.createElement('div');
        row.className = 'cluster-row row g-2 mb-2 align-items-center';
        
        const randomId = Math.random().toString(36).substring(2, 9);
        const stationOptions = (this.projectStationsData || []).map((s, idx) => {
            const isChecked = (stations || []).includes(s.station_code);
            const inputId = `chk_${s.station_code}_${randomId}_${idx}`;
            return `
                <div class="px-2 py-1">
                    <div class="form-check">
                        <input class="form-check-input station-checkbox" type="checkbox" value="${s.station_code}" id="${inputId}" ${isChecked ? 'checked' : ''} onchange="window.adminManager.updateSelectedStationsLabel(this)">
                        <label class="form-check-label text-slate-300 small" style="cursor: pointer;" for="${inputId}">
                            ${s.station_name || s.name || s.station_code} (${s.station_code})
                        </label>
                    </div>
                </div>
            `;
        }).join('') || '<div class="px-3 py-2 text-muted small">Không tìm thấy trạm nào</div>';

        let baseOptionsHtml = '<option value="">-- Chọn Trạm Base --</option>';
        baseOptionsHtml += '<optgroup label="Trạm Dự Án">';
        if (this.projectStationsData) {
            this.projectStationsData.forEach(st => {
                const isSelected = (st.station_code === base_station_code) ? 'selected' : '';
                const devData = encodeURIComponent(JSON.stringify(st.devices || []));
                baseOptionsHtml += `<option value="${st.station_code}" data-devices="${devData}" data-lat="${st.location?.lat || ''}" data-lon="${st.location?.lon || ''}" data-alt="${st.location?.h || 0}" ${isSelected}>${st.name || st.station_code}</option>`;
            });
        }
        baseOptionsHtml += '</optgroup>';
        
        baseOptionsHtml += '<optgroup label="CORS Quốc Gia">';
        if (this.corsStationsData) {
            this.corsStationsData.forEach(st => {
                const isSelected = (st.name === base_station_code || st.code === base_station_code) ? 'selected' : '';
                const online = st.is_online === true || ['online', 'active', 'connected', 'streaming'].includes(String(st.status || '').toLowerCase());
                baseOptionsHtml += `<option value="${st.name || st.code}" data-online="${online}" data-serial="${st.serial || ''}" data-lat="${st.lat}" data-lon="${st.lon}" data-alt="${st.h !== undefined ? st.h : (st.alt || 0)}" data-streams="${encodeURIComponent(JSON.stringify(st.streams || []))}" data-service-config="${encodeURIComponent(JSON.stringify(st.service_config || {}))}" ${isSelected}>${online ? '🟢' : '🔴'} ${st.name || st.code} (${online ? 'ONLINE' : 'OFFLINE'})</option>`;
            });
        }
        baseOptionsHtml += '</optgroup>';

        const backupBaseCode = clusterConfig.backup_base_station || '';
        const backupBaseStream = clusterConfig.backup_base_stream || '';
        let backupBaseOptionsHtml = '<option value="">-- Backup fixed base (optional) --</option>';
        backupBaseOptionsHtml += '<optgroup label="Project stations">';
        (this.projectStationsData || []).forEach(st => {
            const selected = st.station_code === backupBaseCode ? 'selected' : '';
            const devices = encodeURIComponent(JSON.stringify(st.devices || []));
            backupBaseOptionsHtml += `<option value="${st.station_code}" data-devices="${devices}" data-lat="${st.location?.lat || ''}" data-lon="${st.location?.lon || ''}" data-alt="${st.location?.h || 0}" ${selected}>${st.name || st.station_code}</option>`;
        });
        backupBaseOptionsHtml += '</optgroup><optgroup label="CORS stations">';
        (this.corsStationsData || []).forEach(st => {
            const selected = (st.name === backupBaseCode || st.code === backupBaseCode) ? 'selected' : '';
            const online = st.is_online === true || ['online', 'active', 'connected', 'streaming'].includes(String(st.status || '').toLowerCase());
            backupBaseOptionsHtml += `<option value="${st.name || st.code}" data-online="${online}" data-serial="${st.serial || ''}" data-lat="${st.lat}" data-lon="${st.lon}" data-alt="${st.h !== undefined ? st.h : (st.alt || 0)}" data-streams="${encodeURIComponent(JSON.stringify(st.streams || []))}" data-service-config="${encodeURIComponent(JSON.stringify(st.service_config || {}))}" ${selected}>${online ? '🟢' : '🔴'} ${st.name || st.code} (${online ? 'ONLINE' : 'OFFLINE'})</option>`;
        });
        backupBaseOptionsHtml += '</optgroup>';

        const conflictBases = clusterConfig.conflict_bases || [];
        let conflictBaseOptionsHtml = '';
        if (this.corsStationsData) {
            this.corsStationsData.forEach(st => {
                const isSelected = conflictBases.some(cb => cb.serial === st.serial) ? 'selected' : '';
                conflictBaseOptionsHtml += `<option value="${st.serial}" data-name="${st.name || st.code}" ${isSelected}>${st.name || st.code}</option>`;
            });
        }


        row.innerHTML = `
            <!-- COMPACT ROW -->
            <div class="col-md-2">
                <input type="text" class="form-control form-control-sm cluster-name fw-bold" placeholder="Tên cụm (vd: Cụm 1)" value="${name}">
            </div>
            <div class="col-md-2">
                <select class="form-select form-select-sm cluster-type text-primary fw-medium" style="background-color: #f8fafc; border-color: #cbd5e1;">
                    <option value="normal" ${clusterConfig.cluster_type === 'total' ? '' : 'selected'}>⚡ Cụm thường</option>
                    <option value="total" ${clusterConfig.cluster_type === 'total' ? 'selected' : ''}>🌐 Cụm tổng</option>
                </select>
            </div>
            <div class="col-md-3">
                <div class="dropdown w-100">
                    <button class="btn btn-outline-secondary btn-sm dropdown-toggle w-100 text-start overflow-hidden text-truncate selected-stations-label" type="button" data-bs-toggle="dropdown" data-bs-auto-close="outside" aria-expanded="false">
                        Chọn trạm...
                    </button>
                    <div class="dropdown-menu p-2 station-checkbox-list w-100" style="min-width: 240px; max-height: 200px; overflow-y: auto;">
                        ${stationOptions}
                    </div>
                </div>
            </div>
            <div class="col-md-2">
                <input type="text" class="form-control form-control-sm cluster-desc" placeholder="Mô tả..." value="${desc}">
            </div>
            <div class="col-md-3 text-end d-flex gap-1 justify-content-end">
                <button type="button" class="btn btn-sm btn-primary" onclick="const bsCollapse = new bootstrap.Collapse(this.closest('.cluster-row').querySelector('.config-collapse'), {toggle: true});">
                    <i class="bi bi-gear"></i> Cấu hình Base
                </button>
                <button type="button" class="btn btn-sm btn-outline-danger" onclick="this.closest('.cluster-row').remove()">
                    <i class="bi bi-trash"></i>
                </button>
            </div>
            
            <!-- COLLAPSED CONFIGURATION PANEL -->
            <div class="col-12 collapse config-collapse mt-2">
                <div class="card card-body bg-light border-0 shadow-sm p-3">
                    <div class="row">
                        <!-- Primary Base config -->
                        <div class="col-md-6 border-end">
                            <label class="form-label small fw-bold text-primary mb-1"><i class="bi bi-broadcast"></i> Trạm Base Chính</label>
                            <select class="form-select cluster-base-select mb-2" style="font-size:0.85rem;" onchange="window.adminManager.onBaseStationSelected(this)">
                                ${baseOptionsHtml}
                            </select>
                            <select class="form-select cluster-stream-select" style="font-size:0.85rem; display: ${base_stream ? 'block' : 'none'};" data-selected-stream="${base_stream}">
                                <option value="">-- Chọn Luồng (S1/S2) --</option>
                            </select>
                            <div class="base-station-info mt-2" style="display: none; font-size: 0.75rem; background: rgba(14,165,233,0.08); border: 1px solid rgba(14,165,233,0.25); border-radius: 6px; padding: 8px;">
                                <div class="d-flex align-items-center gap-1 mb-1">
                                    <strong class="base-info-name text-info">--</strong>
                                </div>
                                <div class="text-muted" style="line-height: 1.4;">
                                    <span class="base-info-lat">--</span> · <span class="base-info-lon">--</span> · Alt: <span class="base-info-alt">--</span>m
                                </div>
                            </div>
                        </div>
                        
                        <!-- Conflict Bases config -->
                        <div class="col-12 mt-3 conflict-bases-container" style="display: ${clusterConfig.cluster_type === 'total' ? 'block' : 'none'};">
                            <label class="form-label small fw-bold text-danger mb-1"><i class="bi bi-power"></i> Các Trạm Base Phụ Cần Tắt (Khi chạy Cụm Tổng)</label>
                            <select class="form-select cluster-conflict-bases-select mb-2" multiple style="font-size:0.85rem; height: 80px;">
                                ${conflictBaseOptionsHtml}
                            </select>
                            <div class="form-text mt-0" style="font-size: 0.75rem;">Chọn các trạm vật lý phụ thuộc (VD: SinQuyen1) cần ép đi ngủ để tránh xung đột mốc khi Base Chính đẩy S2. Nhấn Ctrl để chọn nhiều.</div>
                        </div>
                        
                        <!-- Backup Base config -->
                        <div class="col-md-6">
                            <label class="form-label small fw-bold text-warning mb-1"><i class="bi bi-shield-check"></i> Trạm Base Dự Phòng</label>
                            <select class="form-select cluster-backup-base-select mb-2" style="font-size:0.85rem;" onchange="window.adminManager.onBaseStationSelected(this)">
                                ${backupBaseOptionsHtml}
                            </select>
                            <select class="form-select cluster-backup-stream-select" style="font-size:0.85rem; display:${backupBaseStream ? 'block' : 'none'};" data-selected-stream="${backupBaseStream}">
                                <option value="">-- Chọn Luồng Base Phụ --</option>
                            </select>
                            <div class="backup-base-station-info mt-2" style="display:none; font-size:0.75rem; background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.25); border-radius:6px; padding:8px;">
                                <strong class="base-info-name text-warning">--</strong>
                                <div class="text-muted"><span class="base-info-lat">--</span> · <span class="base-info-lon">--</span> · Alt: <span class="base-info-alt">--</span>m</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        container.appendChild(row);

        const clusterTypeSelect = row.querySelector('.cluster-type');
        const conflictBasesContainer = row.querySelector('.conflict-bases-container');
        if (clusterTypeSelect && conflictBasesContainer) {
            clusterTypeSelect.addEventListener('change', function() {
                conflictBasesContainer.style.display = this.value === 'total' ? 'block' : 'none';
            });
        }

        const baseSelect = row.querySelector('.cluster-base-select');
        if (baseSelect && baseSelect.value) {
            this.onBaseStationSelected(baseSelect);
        }
        const backupBaseSelect = row.querySelector('.cluster-backup-base-select');
        if (backupBaseSelect && backupBaseSelect.value) {
            this.onBaseStationSelected(backupBaseSelect);
        }

        const firstCheckbox = row.querySelector('.station-checkbox');
        if (firstCheckbox) {
            this.updateSelectedStationsLabel(firstCheckbox);
        }
    }

    onBaseStationSelected(selectEl) {
        const row = selectEl.closest('.cluster-row');
        const selectedOpt = selectEl.options[selectEl.selectedIndex];
        const isBackup = selectEl.classList.contains('cluster-backup-base-select');
        
        // --- 1. Stream Selection ---
        const streamSelect = row.querySelector(
            isBackup ? '.cluster-backup-stream-select' : '.cluster-stream-select'
        );
        const selectedStreamVal = streamSelect.getAttribute('data-selected-stream');
        
        streamSelect.innerHTML = '<option value="">-- Chọn Luồng --</option>';
        
        if (selectedOpt && selectedOpt.dataset.devices) {
            try {
                const devices = JSON.parse(decodeURIComponent(selectedOpt.dataset.devices));
                const gnssDevices = devices.filter(d => d.device_type === 'gnss' || d.device_code.toLowerCase().includes('gnss') || d.device_code.toLowerCase().includes('s1') || d.device_code.toLowerCase().includes('s2'));
                
                if (gnssDevices.length > 0) {
                    gnssDevices.forEach(d => {
                        const isSelected = (d.device_code === selectedStreamVal || d.mqtt_topic === selectedStreamVal) ? 'selected' : '';
                        streamSelect.innerHTML += `<option value="${d.device_code}" ${isSelected}>${d.name || d.device_code} (${d.mqtt_topic || 'No topic'})</option>`;
                    });
                    streamSelect.style.display = 'block';
                } else {
                    streamSelect.style.display = 'none';
                }
            } catch(e) {
                console.error("Error parsing devices config", e);
                streamSelect.style.display = 'none';
            }
        } else if (selectedOpt && selectedOpt.dataset.streams) {
            try {
                const streams = JSON.parse(decodeURIComponent(selectedOpt.dataset.streams));
                if (streams.length > 0) {
                    streams.forEach(s => {
                        const isSelected = (s.stream_id === selectedStreamVal || s.mountpoint === selectedStreamVal) ? 'selected' : '';
                        const hostLabel = s.host ? ` [${s.host}:${s.port}]` : '';
                        streamSelect.innerHTML += `<option value="${s.stream_id}" data-server-id="${s.server_id || String(s.stream_id || '').replace(/\D/g, '')}" data-host="${s.host || ''}" data-port="${s.port || ''}" data-mp="${s.mountpoint || ''}" ${isSelected}>Luồng: ${s.stream_id.toUpperCase()} - ${s.mountpoint}${hostLabel}</option>`;
                    });
                    streamSelect.style.display = 'block';
                } else {
                    streamSelect.style.display = 'none';
                }
            } catch(e) {
                console.error("Error parsing streams", e);
                streamSelect.style.display = 'none';
            }
        } else {
            // No devices or mountpoints
            streamSelect.style.display = 'none';
        }

        // --- 2. Base Info Display ---
        const infoPanel = row.querySelector(
            isBackup ? '.backup-base-station-info' : '.base-station-info'
        );
        if (!selectEl.value) {
            if (infoPanel) infoPanel.style.display = 'none';
            return;
        }

        const lat = selectedOpt.dataset.lat || '--';
        const lon = selectedOpt.dataset.lon || '--';
        const alt = selectedOpt.dataset.alt || '0';
        const name = selectEl.value;
        const online = selectedOpt.dataset.online === 'true';

        if (infoPanel) {
            infoPanel.querySelector('.base-info-name').textContent = `${online ? '🟢 ONLINE' : '🔴 OFFLINE'} · ${name}`;
            infoPanel.querySelector('.base-info-lat').textContent = `Lat: ${lat}`;
            infoPanel.querySelector('.base-info-lon').textContent = `Lon: ${lon}`;
            infoPanel.querySelector('.base-info-alt').textContent = alt;
            infoPanel.style.display = 'block';
        }
    }

    updateSelectedStationsLabel(el) {
        const row = el.closest('.cluster-row');
        const checkedList = Array.from(row.querySelectorAll('.station-checkbox:checked')).map(c => c.value);
        const btn = row.querySelector('.selected-stations-label');
        if (!btn) return;
        
        if (checkedList.length === 0) {
            btn.textContent = 'Chọn trạm...';
            btn.classList.remove('btn-outline-primary');
            btn.classList.add('btn-outline-secondary');
        } else {
            btn.textContent = `Đã chọn: ${checkedList.join(', ')}`;
            btn.classList.remove('btn-outline-secondary');
            btn.classList.add('btn-outline-primary');
        }
    }

    async fetchCorsStations() {
        if (this.corsStationsData && this.corsStationsData.length > 0) return; // Cache check

        try {
            const res = await fetch('/api/admin/projects/cors-stations', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) throw new Error('Không thể lấy danh sách trạm CORS từ URL');
            
            const data = await res.json();
            const stations = Array.isArray(data) ? data : (data.data || data.stations || []);
            
            this.corsStationsData = stations;
            
        } catch (e) {
            console.error(e);
            window.toast?.error('❌ ' + e.message);
        }
    }

    async saveProjectConfig() {
        const projectId = this.currentProjectId;
        if (!projectId) return;

        // Collect Clusters
        const clusters = [];
        let clusterConfigError = '';
        document.querySelectorAll('#project-gnss-clusters-container .cluster-row').forEach(row => {
            const name = row.querySelector('.cluster-name').value.trim();
            if (name) {
                const desc = row.querySelector('.cluster-desc').value.trim();
                const baseSelect = row.querySelector('.cluster-base-select');
                const baseStation = baseSelect?.value || '';
                const selectedOpt = baseSelect?.options[baseSelect.selectedIndex];
                const baseLat = selectedOpt?.dataset?.lat ? parseFloat(selectedOpt.dataset.lat) : null;
                const baseLon = selectedOpt?.dataset?.lon ? parseFloat(selectedOpt.dataset.lon) : null;
                const baseAlt = selectedOpt?.dataset?.alt ? parseFloat(selectedOpt.dataset.alt) : null;
                const backupSelect = row.querySelector('.cluster-backup-base-select');
                const backupOpt = backupSelect?.options[backupSelect.selectedIndex];
                const backupStreamSelect = row.querySelector('.cluster-backup-stream-select');
                const primaryStreamSelect = row.querySelector('.cluster-stream-select');
                const st = Array.from(row.querySelectorAll('.station-checkbox:checked')).map(c => c.value);
                const conflictBasesSelect = row.querySelector('.cluster-conflict-bases-select');
                const conflictBases = conflictBasesSelect ? Array.from(conflictBasesSelect.selectedOptions).map(opt => ({
                    serial: opt.value,
                    name: opt.dataset.name
                })) : [];
                
                const backupBaseStation = backupSelect?.value || '';
                const backupStreamHost = backupStreamSelect?.selectedIndex >= 0 ? (backupStreamSelect.options[backupStreamSelect.selectedIndex]?.dataset?.host || '') : '';
                const backupStreamMp = backupStreamSelect?.selectedIndex >= 0 ? (backupStreamSelect.options[backupStreamSelect.selectedIndex]?.dataset?.mp || '') : '';
                const primaryStreamMp = primaryStreamSelect?.selectedIndex >= 0 ? (primaryStreamSelect.options[primaryStreamSelect.selectedIndex]?.dataset?.mp || '') : '';
                if (backupBaseStation && backupBaseStation === baseStation) {
                    clusterConfigError ||= `${name}: base dự phòng phải khác base chính.`;
                } else if (backupBaseStation && (!backupStreamHost || !backupStreamMp)) {
                    clusterConfigError ||= `${name}: hãy chọn đúng luồng CORS S1/S2 cho base dự phòng.`;
                } else if (backupBaseStation && backupStreamMp !== primaryStreamMp) {
                    clusterConfigError ||= `${name}: luồng S2 dự phòng phải gửi vào cùng mountpoint của S1 chính.`;
                }
                clusters.push({
                    name, description: desc,
                    base_station: baseStation,
                    base_lat: baseLat, base_lon: baseLon, base_alt: baseAlt,
                    base_stream: row.querySelector('.cluster-stream-select')?.value || '',
                    base_stream_host: (row.querySelector('.cluster-stream-select')?.selectedIndex >= 0) ? (row.querySelector('.cluster-stream-select')?.options[row.querySelector('.cluster-stream-select')?.selectedIndex]?.dataset?.host || '') : '',
                    base_stream_port: (row.querySelector('.cluster-stream-select')?.selectedIndex >= 0) ? (row.querySelector('.cluster-stream-select')?.options[row.querySelector('.cluster-stream-select')?.selectedIndex]?.dataset?.port || '') : '',
                    base_stream_mp: (row.querySelector('.cluster-stream-select')?.selectedIndex >= 0) ? (row.querySelector('.cluster-stream-select')?.options[row.querySelector('.cluster-stream-select')?.selectedIndex]?.dataset?.mp || '') : '',
                    base_service_config: selectedOpt?.dataset?.serviceConfig ? JSON.parse(decodeURIComponent(selectedOpt.dataset.serviceConfig)) : {},
                    base_serial: selectedOpt?.dataset?.serial || '',
                    base_server_id: row.querySelector('.cluster-stream-select')?.selectedIndex >= 0 ? (row.querySelector('.cluster-stream-select')?.options[row.querySelector('.cluster-stream-select')?.selectedIndex]?.dataset?.serverId || '') : '',
                    backup_base_station: backupBaseStation,
                    backup_base_lat: backupOpt?.dataset?.lat ? parseFloat(backupOpt.dataset.lat) : null,
                    backup_base_lon: backupOpt?.dataset?.lon ? parseFloat(backupOpt.dataset.lon) : null,
                    backup_base_alt: backupOpt?.dataset?.alt ? parseFloat(backupOpt.dataset.alt) : null,
                    backup_base_stream: backupStreamSelect?.value || '',
                    backup_base_stream_host: backupStreamHost,
                    backup_base_stream_port: backupStreamSelect?.selectedIndex >= 0 ? (backupStreamSelect.options[backupStreamSelect.selectedIndex]?.dataset?.port || '') : '',
                    backup_base_stream_mp: backupStreamMp,
                    backup_base_service_config: backupOpt?.dataset?.serviceConfig ? JSON.parse(decodeURIComponent(backupOpt.dataset.serviceConfig)) : {},
                    backup_base_serial: backupOpt?.dataset?.serial || '',
                    backup_base_server_id: backupStreamSelect?.selectedIndex >= 0 ? (backupStreamSelect.options[backupStreamSelect.selectedIndex]?.dataset?.serverId || '') : '',
                    cluster_type: row.querySelector('.cluster-type')?.value || 'normal',
                    conflict_bases: conflictBases,
                    stations: st
                });
            }
        });

        if (clusterConfigError) {
            window.toast?.error(clusterConfigError);
            return;
        }

        try {
            const res = await fetch(`/api/admin/projects/${projectId}`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    gnss_clusters: clusters
                })
            });

            if (!res.ok) throw new Error('Lỗi lưu cấu hình dự án');

            window.toast?.success('✅ Đã lưu cấu hình dự án!');
            this.projectConfigModal.hide();
            await this.loadProjects();
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
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
                ${this.stationsData.map(s => {
                    const alertingDisabled = (s.config?.alerting?.enabled === false) || s.config?.alerting_enabled === false;
                    const offlineDisplayEnabled = (s.config?.offline_display?.enabled === true) || s.config?.offline_display_enabled === true;
                    const statusAccent = s.status === 'online' ? 'success' : (s.status === 'stale' ? 'warning' : 'secondary');
                    return `
                    <div class="col-md-6">
                        <div class="card hover-lift station-card">
                            <div class="card-body position-relative" style="z-index: 2;">
                                <div class="d-flex justify-content-between align-items-start mb-2">
                                    <div>
                                        <h6 class="mb-1 fw-bold neon-text" style="color: var(--accent-${statusAccent})">
                                            <i class="bi bi-broadcast-pin me-2"></i>
                                            ${s.name}
                                        </h6>
                                        <small class="text-muted font-monospace">${s.station_code}</small>
                                        ${alertingDisabled ? '<span class="badge bg-warning text-dark ms-2">Không cảnh báo</span>' : ''}
                                        ${offlineDisplayEnabled ? '<span class="badge bg-info text-dark ms-2">Offline giám sát</span>' : ''}
                                    </div>
                                    <div class="d-flex align-items-center gap-2">
                                        <span class="status-dot ${s.status === 'online' ? 'pulsing' : ''}"
                                              style="background-color: var(--accent-${statusAccent})"></span>
                                        <span class="small font-monospace text-uppercase" style="color: var(--accent-${statusAccent})">
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
                `;
                }).join('')
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
        if (this._originResetTimer) {
            clearInterval(this._originResetTimer);
            this._originResetTimer = null;
        }

        document.getElementById('stationConfigForm').reset();
        document.getElementById('edit-station-id').value = '';

        // Reset custom MQTT Broker inputs
        const mqttHostEl = document.getElementById('station-mqtt-host');
        if (mqttHostEl) mqttHostEl.value = '';
        const mqttPortEl = document.getElementById('station-mqtt-port');
        if (mqttPortEl) mqttPortEl.value = '';
        const mqttTlsEl = document.getElementById('station-mqtt-tls');
        if (mqttTlsEl) mqttTlsEl.checked = false;
        const mqttUserEl = document.getElementById('station-mqtt-user');
        if (mqttUserEl) mqttUserEl.value = '';
        const mqttPassEl = document.getElementById('station-mqtt-pass');
        if (mqttPassEl) mqttPassEl.value = '';
        document.getElementById('origin-lat').value = '';
        document.getElementById('origin-lon').value = '';
        document.getElementById('origin-h').value = '';
        document.getElementById('origin-status').textContent = 'Chưa có tọa độ gốc';
        this.updateOriginActionButtons(false);

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
        const alertingDisabledEl = document.getElementById('station-alerting-disabled');
        if (alertingDisabledEl) alertingDisabledEl.checked = false;
        const offlineDisplayEl = document.getElementById('station-offline-display-enabled');
        if (offlineDisplayEl) offlineDisplayEl.checked = false;
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

        // Reset RTK forwarding fields to default (all enabled)
        const fwdToggleIds = ['fwd-toggle-x', 'fwd-toggle-y', 'fwd-toggle-h', 'fwd-toggle-dx', 'fwd-toggle-dy', 'fwd-toggle-dh', 'fwd-toggle-vdx', 'fwd-toggle-vdy', 'fwd-toggle-vdh'];
        fwdToggleIds.forEach(id => { const el = document.getElementById(id); if (el) el.checked = true; });
        const rtkTopicEl = document.getElementById('gnss-rtk-topic');
        if (rtkTopicEl) rtkTopicEl.value = '';
        this.syncForwardingWrapStates();

        document.getElementById('mqtt-empty-state').style.display = 'block';
        this.updateOriginActionButtons(false);

        this.highlightPreset(null);
        this.updateWizardStep();
        if (this.stationModal) this.stationModal.show();
    }

    async editStation(stationId) {
        try {
            this.isEditMode = true;
            this.currentStationId = stationId;
            this.currentStep = 1;
            if (this._originResetTimer) {
                clearInterval(this._originResetTimer);
                this._originResetTimer = null;
            }

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
                        
                        const devConfig = dev.config || {};
                        const mqttCfg = devConfig.mqtt || {};
                        
                        const hostEl = document.getElementById(`cfg-${type}-mqtt-host`);
                        const portEl = document.getElementById(`cfg-${type}-mqtt-port`);
                        const tlsEl = document.getElementById(`cfg-${type}-mqtt-tls`);
                        const userEl = document.getElementById(`cfg-${type}-mqtt-user`);
                        const passEl = document.getElementById(`cfg-${type}-mqtt-pass`);
                        
                        if (hostEl) hostEl.value = mqttCfg.host || '';
                        if (portEl) portEl.value = mqttCfg.port || '';
                        if (tlsEl) {
                            tlsEl.checked = !!mqttCfg.use_tls;
                            const wrap = document.getElementById(`wrap-${type}-mqtt-tls`);
                            if (wrap) {
                                if (tlsEl.checked) {
                                    wrap.classList.add('is-on');
                                    wrap.classList.remove('is-off');
                                } else {
                                    wrap.classList.add('is-off');
                                    wrap.classList.remove('is-on');
                                }
                            }
                        }
                        if (userEl) userEl.value = mqttCfg.username || '';
                        if (passEl) passEl.value = mqttCfg.password || '';
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
            const alertingDisabledEl = document.getElementById('station-alerting-disabled');
            if (alertingDisabledEl) {
                alertingDisabledEl.checked = (cfg.alerting?.enabled === false) || cfg.alerting_enabled === false;
            }
            const offlineDisplayEl = document.getElementById('station-offline-display-enabled');
            if (offlineDisplayEl) {
                offlineDisplayEl.checked = (cfg.offline_display?.enabled === true) || cfg.offline_display_enabled === true;
            }
            this.currentStationConfig = cfg;

            // Populate custom MQTT Broker fields
            const mqttCfg = cfg.mqtt || {};
            const mqttHostEl = document.getElementById('station-mqtt-host');
            if (mqttHostEl) mqttHostEl.value = mqttCfg.host || '';
            const mqttPortEl = document.getElementById('station-mqtt-port');
            if (mqttPortEl) mqttPortEl.value = mqttCfg.port || '';
            const mqttTlsEl = document.getElementById('station-mqtt-tls');
            if (mqttTlsEl) mqttTlsEl.checked = !!mqttCfg.use_tls;
            const mqttUserEl = document.getElementById('station-mqtt-user');
            if (mqttUserEl) mqttUserEl.value = mqttCfg.username || '';
            const mqttPassEl = document.getElementById('station-mqtt-pass');
            if (mqttPassEl) mqttPassEl.value = mqttCfg.password || '';

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
            const waterWarningConfirmEl = document.getElementById('cfg-water-warning-confirm');
            const waterCriticalConfirmEl = document.getElementById('cfg-water-critical-confirm');
            const waterConfirmSrc = document.getElementById('cfg-water-confirm-source');
            if (waterWarningConfirmEl) {
                const wcs = waterCfg.water_warning_confirm_steps ?? waterCfg.water_confirm_steps;
                waterWarningConfirmEl.value = wcs ?? 3;
                if (waterConfirmSrc) {
                    waterConfirmSrc.textContent = wcs != null ? '✅ Đã lưu riêng cho trạm' : '⚠ Sẽ dùng giá trị Hệ thống';
                    waterConfirmSrc.className = wcs != null ? 'text-success small' : 'text-warning small';
                }
            }
            if (waterCriticalConfirmEl) {
                const wccs = waterCfg.water_critical_confirm_steps ?? waterCfg.water_confirm_steps;
                waterCriticalConfirmEl.value = wccs ?? 2;
            }
            const waterSafeConfirmEl = document.getElementById('cfg-water-safe-confirm');
            const waterSafeConfirmSrc = document.getElementById('cfg-water-safe-confirm-source');
            if (waterSafeConfirmEl) {
                const wscs = waterCfg.water_safe_confirm_steps;
                waterSafeConfirmEl.value = wscs ?? 3;
                if (waterSafeConfirmSrc) {
                    waterSafeConfirmSrc.textContent = wscs != null ? '✅ Đã lưu riêng cho trạm' : '⚠ Sẽ dùng giá trị Hệ thống';
                    waterSafeConfirmSrc.className = wscs != null ? 'text-success small' : 'text-warning small';
                }
            }

            const rainCfg = cfg.RainAlerting || {};
            document.getElementById('cfg-rain-watch').value = rainCfg.rain_intensity_watch_threshold ?? 10.0;
            document.getElementById('cfg-rain-warning').value = rainCfg.rain_intensity_warning_threshold ?? 25.0;
            document.getElementById('cfg-rain-critical').value = rainCfg.rain_intensity_critical_threshold ?? 50.0;

            // Rain confirm steps - hiển thị nguồn giá trị
            const rainWarningConfirmEl = document.getElementById('cfg-rain-warning-confirm');
            const rainCriticalConfirmEl = document.getElementById('cfg-rain-critical-confirm');
            const rainConfirmSrc = document.getElementById('cfg-rain-confirm-source');
            if (rainWarningConfirmEl) {
                const rcs = rainCfg.rain_warning_confirm_steps ?? rainCfg.rain_confirm_steps;
                rainWarningConfirmEl.value = rcs ?? 2;
                if (rainConfirmSrc) {
                    rainConfirmSrc.textContent = rcs != null ? '✅ Đã lưu riêng cho trạm' : '⚠ Sẽ dùng giá trị Hệ thống';
                    rainConfirmSrc.className = rcs != null ? 'text-success small' : 'text-warning small';
                }
            }
            if (rainCriticalConfirmEl) {
                const rccs = rainCfg.rain_critical_confirm_steps ?? rainCfg.rain_confirm_steps;
                rainCriticalConfirmEl.value = rccs ?? 1;
            }
            const rainSafeConfirmEl = document.getElementById('cfg-rain-safe-confirm');
            const rainSafeConfirmSrc = document.getElementById('cfg-rain-safe-confirm-source');
            if (rainSafeConfirmEl) {
                const rscs = rainCfg.rain_safe_confirm_steps;
                rainSafeConfirmEl.value = rscs ?? 3;
                if (rainSafeConfirmSrc) {
                    rainSafeConfirmSrc.textContent = rscs != null ? '✅ Đã lưu riêng cho trạm' : '⚠ Sẽ dùng giá trị Hệ thống';
                    rainSafeConfirmSrc.className = rscs != null ? 'text-success small' : 'text-warning small';
                }
            }
            const gnssCfg = cfg.GnssAlerting || {};
            document.getElementById('cfg-gnss-timeout').value = gnssCfg.gnss_degraded_timeout ?? 300;
            document.getElementById('cfg-gnss-hdop').value = gnssCfg.gnss_max_hdop ?? 4.0;

            const imuCfg = cfg.ImuAlerting || {};
            document.getElementById('cfg-imu-shock').value = imuCfg.shock_threshold_ms2 ?? 5.0;
            const tiltCritEl = document.getElementById('cfg-imu-tilt-crit');
            if (tiltCritEl) tiltCritEl.value = imuCfg.tilt_critical_deg ?? 15.0;
            const imuCriticalConfirmEl = document.getElementById('cfg-imu-critical-confirm');
            if (imuCriticalConfirmEl) imuCriticalConfirmEl.value = imuCfg.imu_critical_confirm_steps ?? imuCfg.imu_confirm_steps ?? 1;
            const imuSafeConfirmEl = document.getElementById('cfg-imu-safe-confirm');
            if (imuSafeConfirmEl) imuSafeConfirmEl.value = imuCfg.imu_safe_confirm_steps ?? 3;
            const gnssWarningStepsEl = document.getElementById('cfg-gnss-warning-steps');
            if (gnssWarningStepsEl) gnssWarningStepsEl.value = gnssCfg.gnss_warning_confirm_steps ?? gnssCfg.gnss_confirm_steps ?? 3;
            const gnssCriticalStepsEl = document.getElementById('cfg-gnss-critical-steps');
            if (gnssCriticalStepsEl) gnssCriticalStepsEl.value = gnssCfg.gnss_critical_confirm_steps ?? gnssCfg.gnss_confirm_steps ?? 2;
            const gnssSafeStepsEl = document.getElementById('cfg-gnss-safe-steps');
            if (gnssSafeStepsEl) gnssSafeStepsEl.value = gnssCfg.gnss_safe_confirm_steps ?? 5;

            const imuBaseline = cfg.ImuBaseline || {};
            const baseRollEl = document.getElementById('cfg-imu-base-roll');
            if (baseRollEl) baseRollEl.value = imuBaseline.baseline_roll ?? 0;
            const basePitchEl = document.getElementById('cfg-imu-base-pitch');
            if (basePitchEl) basePitchEl.value = imuBaseline.baseline_pitch ?? 0;
            const baseYawEl = document.getElementById('cfg-imu-base-yaw');
            if (baseYawEl) baseYawEl.value = imuBaseline.baseline_yaw ?? 0;

            // ✅ LOAD GNSS RTK FORWARDING
            const fwdCfg = cfg.gnss_rtk_forwarding || {};
            const fwdFields = fwdCfg.fields || {};
            const setToggle = (id, val, defaultVal = true) => {
                const el = document.getElementById(id);
                if (el) el.checked = (val !== undefined) ? !!val : defaultVal;
            };

            const fwdEnabledEl = document.getElementById('cfg-fwd-enabled');
            if (fwdEnabledEl) {
                fwdEnabledEl.checked = !!fwdCfg.enabled;
                this.toggleRtkForwardingSlide(false); // Init slide state
            }

            const rtkTopicEl = document.getElementById('gnss-rtk-topic');
            if (rtkTopicEl) rtkTopicEl.value = fwdCfg.rtk_topic || '';

            const rtkHostEl = document.getElementById('gnss-rtk-host');
            if (rtkHostEl) rtkHostEl.value = fwdCfg.host || '';
            const rtkPortEl = document.getElementById('gnss-rtk-port');
            if (rtkPortEl) rtkPortEl.value = fwdCfg.port || 1883;
            const rtkUserEl = document.getElementById('gnss-rtk-user');
            if (rtkUserEl) rtkUserEl.value = fwdCfg.username || '';
            const rtkPassEl = document.getElementById('gnss-rtk-pass');
            if (rtkPassEl) rtkPassEl.value = fwdCfg.password || '';
            const rtkCodeEl = document.getElementById('gnss-rtk-code');
            if (rtkCodeEl) rtkCodeEl.value = fwdCfg.gnss_code || '';

            setToggle('fwd-toggle-x', fwdFields.X);
            setToggle('fwd-toggle-y', fwdFields.Y);
            setToggle('fwd-toggle-h', fwdFields.H);
            setToggle('fwd-toggle-dx', fwdFields.dX);
            setToggle('fwd-toggle-dy', fwdFields.dY);
            setToggle('fwd-toggle-dh', fwdFields.dH);
            setToggle('fwd-toggle-vdx', fwdFields.VdX);
            setToggle('fwd-toggle-vdy', fwdFields.VdY);
            setToggle('fwd-toggle-vdh', fwdFields.VdH);
            this.syncForwardingWrapStates();

            // ✅ LOAD VN2000 ADVANCED PARAMS
            const vnCfg = cfg.vn2000 || cfg.vn2000_params || {};
            const vnEnabledEl = document.getElementById('vn2000-enabled');
            if (vnEnabledEl) {
                vnEnabledEl.checked = !!vnCfg.enabled;
                this.toggleVn2000AdvancedSlide(false); // Init slide state
            }
            if (document.getElementById('vn-dx')) document.getElementById('vn-dx').value = vnCfg.dx ?? 191.90441429;
            if (document.getElementById('vn-dy')) document.getElementById('vn-dy').value = vnCfg.dy ?? 39.30318279;
            if (document.getElementById('vn-dz')) document.getElementById('vn-dz').value = vnCfg.dz ?? 111.45032835;
            if (document.getElementById('vn-rx')) document.getElementById('vn-rx').value = vnCfg.rx ?? 0.00928836;
            if (document.getElementById('vn-ry')) document.getElementById('vn-ry').value = vnCfg.ry ?? -0.01975479;
            if (document.getElementById('vn-rz')) document.getElementById('vn-rz').value = vnCfg.rz ?? 0.00427372;
            if (document.getElementById('vn-k')) document.getElementById('vn-k').value = vnCfg.k ?? 0.999999747093722;
            if (document.getElementById('vn-l0')) document.getElementById('vn-l0').value = vnCfg.l0_deg ?? 105.0;
            if (document.getElementById('vn-k0')) document.getElementById('vn-k0').value = vnCfg.k0 ?? 0.9999;
            if (document.getElementById('vn-resb')) document.getElementById('vn-resb').value = vnCfg.res_b ?? 0.0;
            if (document.getElementById('vn-resl')) document.getElementById('vn-resl').value = vnCfg.res_l ?? 0.0;
            if (document.getElementById('vn-resh')) document.getElementById('vn-resh').value = vnCfg.res_h ?? 0.0;
            if (document.getElementById('vn-resn')) document.getElementById('vn-resn').value = vnCfg.res_n ?? 0.0;
            if (document.getElementById('vn-rese')) document.getElementById('vn-rese').value = vnCfg.res_e ?? 0.0;


            const gnssOrigin = cfg.gnss_origin || {};
            if (gnssOrigin.lat) {
                document.getElementById('origin-lat').value = gnssOrigin.lat;
                document.getElementById('origin-lon').value = gnssOrigin.lon;
                document.getElementById('origin-h').value = gnssOrigin.h || 0;
                document.getElementById('origin-status').innerHTML = '<span class="text-success">✅ Đã có tọa độ gốc</span>';
                this.updateOriginActionButtons(true);
            } else {
                document.getElementById('origin-lat').value = '';
                document.getElementById('origin-lon').value = '';
                document.getElementById('origin-h').value = '';
                document.getElementById('origin-status').textContent = 'Chưa thiết lập';
                this.updateOriginActionButtons(false);
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

            // ✅ STEP 4: LOAD PER-STATION SAVE INTERVALS
            const stationSaveIntervals = cfg.save_intervals || {};
            const saveGnssEl = document.getElementById('cfg-station-save-gnss');
            const saveRainEl = document.getElementById('cfg-station-save-rain');
            const saveWaterEl = document.getElementById('cfg-station-save-water');
            const saveImuEl = document.getElementById('cfg-station-save-imu');
            if (saveGnssEl) saveGnssEl.value = stationSaveIntervals.gnss || '';
            if (saveRainEl) saveRainEl.value = stationSaveIntervals.rain || '';
            if (saveWaterEl) saveWaterEl.value = stationSaveIntervals.water || '';
            if (saveImuEl) saveImuEl.value = stationSaveIntervals.imu || '';

            document.getElementById('modal-title').textContent = `Chỉnh sửa: ${stationData.name}`;

            this.highlightPreset(cfg.active_preset);
            this.updateWizardStep();
            if (this.stationModal) this.stationModal.show();

        } catch (e) {
            console.error('❌ Error in editStation:', e);
            window.toast?.error('Lỗi: ' + e.message);
        }
    }

    updateWizardStep() {
        const stationModalEl = document.getElementById('stationConfigModal');
        const scope = stationModalEl || document;

        scope.querySelectorAll('.wizard-step').forEach(step => {
            const stepNum = parseInt(step.dataset.step);
            step.classList.toggle('active', stepNum === this.currentStep);
        });

        scope.querySelectorAll('.wizard-content').forEach(content => {
            const stepNum = parseInt(content.dataset.step);
            const isActive = stepNum === this.currentStep;
            content.classList.toggle('active', isActive);
            content.style.display = isActive ? 'block' : 'none';
            content.setAttribute('aria-hidden', isActive ? 'false' : 'true');
        });

        const modalBody = stationModalEl?.querySelector('.modal-body');
        if (modalBody) {
            modalBody.scrollTop = 0;
        }

        const btnBack = document.getElementById('btn-wizard-back');
        const btnNext = document.getElementById('btn-wizard-next');
        const btnSave = document.getElementById('btn-wizard-save');

        if (btnBack) btnBack.style.display = this.currentStep > 1 ? 'inline-block' : 'none';
        if (btnNext) btnNext.style.display = this.currentStep < this.totalSteps ? 'inline-block' : 'none';
        if (btnSave) btnSave.style.display = this.currentStep === this.totalSteps ? 'inline-block' : 'none';
        if (btnNext) btnNext.disabled = false;
        if (btnSave) btnSave.disabled = false;
        this.ensureWizardButtonInteractivity();

        // When reaching step 3, load pending devices for provisioning (only if editing existing station)
        const pendingSection = document.getElementById('pending-devices-section');
        if (this.currentStep === 3 && this.currentStationId) {
            if (pendingSection) pendingSection.style.display = 'block';
            this.loadWizardPendingDevices().catch((e) => {
                console.error('Failed to load pending devices in step 3:', e);
            });
        } else {
            if (pendingSection) pendingSection.style.display = 'none';
        }

        this.syncMqttSectionsForStep();
        this.syncSaveIntervalsForStep();
    }

    goToWizardStep(nextStep) {
        const normalizedStep = Math.max(1, Math.min(this.totalSteps, Number(nextStep) || 1));
        if (normalizedStep === this.currentStep) return;

        this.currentStep = normalizedStep;

        try {
            this.updateWizardStep();
        } catch (e) {
            console.error('Wizard UI update failed, applying fallback render:', e);

            // Fallback render: force-show only the target step content.
            document.querySelectorAll('#stationConfigModal .wizard-content').forEach(content => {
                const stepNum = Number(content.dataset.step);
                const isActive = stepNum === this.currentStep;
                content.classList.toggle('active', isActive);
                content.style.display = isActive ? 'block' : 'none';
            });
        }
    }

    syncMqttSectionsForStep() {
        const sensorTypes = ['gnss', 'rain', 'water', 'imu'];
        const sectionByType = {
            gnss: document.getElementById('mqtt-gnss-section'),
            rain: document.getElementById('mqtt-rain-section'),
            water: document.getElementById('mqtt-water-section'),
            imu: document.getElementById('mqtt-imu-section')
        };
        const emptyState = document.getElementById('mqtt-empty-state');

        // Never show MQTT blocks outside step 2.
        if (this.currentStep !== 2) {
            sensorTypes.forEach(type => {
                const section = sectionByType[type];
                if (section) section.style.display = 'none';
            });
            if (emptyState) emptyState.style.display = 'none';
            return;
        }

        let anyChecked = false;
        sensorTypes.forEach(type => {
            const checked = !!document.getElementById(`edit-${type}`)?.checked;
            const section = sectionByType[type];
            if (section) section.style.display = checked ? 'block' : 'none';
            if (checked) anyChecked = true;
        });

        if (emptyState) emptyState.style.display = anyChecked ? 'none' : 'block';
    }

    syncSaveIntervalsForStep() {
        if (this.currentStep !== 4) return;

        const sensors = [
            { type: 'gnss', elId: 'cfg-station-save-gnss' },
            { type: 'rain', elId: 'cfg-station-save-rain' },
            { type: 'water', elId: 'cfg-station-save-water' },
            { type: 'imu', elId: 'cfg-station-save-imu' }
        ];

        let visibleCount = 0;
        sensors.forEach(({ type, elId }) => {
            const inputEl = document.getElementById(elId);
            const checkboxEl = document.getElementById(`edit-${type}`);
            if (inputEl && inputEl.closest('.col-md-6')) {
                const isEnabled = checkboxEl && checkboxEl.checked;
                inputEl.closest('.col-md-6').style.display = isEnabled ? 'block' : 'none';
                if (isEnabled) visibleCount++;
            }
        });
        
        // Cập nhật thông báo nếu không có cảm biến nào
        let emptyState = document.getElementById('save-interval-empty-state');
        const container = document.querySelector('.sensor-config-body .row.g-3');
        if (visibleCount === 0 && container) {
            if (!emptyState) {
                emptyState = document.createElement('div');
                emptyState.id = 'save-interval-empty-state';
                emptyState.className = 'col-12 text-center text-muted small py-3';
                emptyState.innerHTML = '<i class="bi bi-x-circle me-1"></i> Không có cảm biến nào được bật cho trạm này.';
                container.appendChild(emptyState);
            }
            emptyState.style.display = 'block';
        } else if (emptyState) {
            emptyState.style.display = 'none';
        }
    }

    bindWizardButtons() {
        const btnBack = document.getElementById('btn-wizard-back');
        const btnNext = document.getElementById('btn-wizard-next');
        const btnSave = document.getElementById('btn-wizard-save');

        // Use direct handler assignment so buttons always follow latest instance state.
        if (btnBack) {
            btnBack.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.wizardPrev();
            };
        }

        if (btnNext) {
            btnNext.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.wizardNext();
            };
        }

        if (btnSave) {
            btnSave.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.saveStation();
            };
        }
    }

    bindWizardButtonFallback() {
        if (this._wizardFallbackBound) return;

        document.addEventListener('click', (e) => {
            const btn = e.target?.closest?.('#btn-wizard-next, #btn-wizard-back, #btn-wizard-save');
            if (!btn) return;

            const modalEl = document.getElementById('stationConfigModal');
            if (!modalEl || !modalEl.classList.contains('show')) return;

            e.preventDefault();
            e.stopPropagation();

            if (btn.id === 'btn-wizard-next') {
                this.wizardNext();
            } else if (btn.id === 'btn-wizard-back') {
                this.wizardPrev();
            } else if (btn.id === 'btn-wizard-save') {
                this.saveStation();
            }
        }, true);

        // Extra fallback: bind directly on modal root so clicks still work even if another
        // layer/listener interferes at document level.
        const modalEl = document.getElementById('stationConfigModal');
        if (modalEl) {
            modalEl.addEventListener('click', (e) => {
                const btn = e.target?.closest?.('#btn-wizard-next, #btn-wizard-back, #btn-wizard-save');
                if (!btn) return;
                if (!modalEl.classList.contains('show')) return;

                e.preventDefault();
                e.stopPropagation();

                if (btn.id === 'btn-wizard-next') {
                    this.wizardNext();
                } else if (btn.id === 'btn-wizard-back') {
                    this.wizardPrev();
                } else if (btn.id === 'btn-wizard-save') {
                    this.saveStation();
                }
            }, true);
        }

        this._wizardFallbackBound = true;
    }

    ensureWizardButtonInteractivity() {
        const footer = document.querySelector('#stationConfigModal .modal-footer');
        const btnIds = ['btn-wizard-next', 'btn-wizard-back', 'btn-wizard-save'];

        if (footer) {
            footer.style.pointerEvents = 'auto';
            footer.style.position = 'relative';
            footer.style.zIndex = '1061';
        }

        btnIds.forEach((id) => {
            const btn = document.getElementById(id);
            if (!btn) return;
            btn.disabled = false;
            btn.style.pointerEvents = 'auto';
            btn.style.position = 'relative';
            btn.style.zIndex = '1062';
        });
    }

    wizardNext() {
        if (this.currentStep < this.totalSteps) {
            this.goToWizardStep(this.currentStep + 1);
        }
    }

    wizardPrev() {
        if (this.currentStep > 1) {
            this.goToWizardStep(this.currentStep - 1);
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
                gnss_warning_steps: 5,
                gnss_critical_steps: 3,
                water_warning_confirm: 5,
                water_critical_confirm: 3,
                rain_warning_confirm: 3,
                rain_critical_confirm: 2,
                gnss_hdop: 3.0,
                gnss_timeout: 600,
                water_warning: 0.20,
                water_critical: 0.40,
                rain_watch: 15.0,
                rain_warning: 35.0,
                rain_critical: 60.0,
                imu_tilt_crit: 25.0,
                imu_shock: 8.0,
                imu_critical_confirm: 1
            },
            balanced: {
                gnss_warning_steps: 3,
                gnss_critical_steps: 2,
                water_warning_confirm: 3,
                water_critical_confirm: 2,
                rain_warning_confirm: 2,
                rain_critical_confirm: 1,
                gnss_hdop: 4.0,
                gnss_timeout: 300,
                water_warning: 0.15,
                water_critical: 0.30,
                rain_watch: 10.0,
                rain_warning: 25.0,
                rain_critical: 50.0,
                imu_tilt_crit: 15.0,
                imu_shock: 5.0,
                imu_critical_confirm: 1
            },
            sensitive: {
                gnss_warning_steps: 1,
                gnss_critical_steps: 1,
                water_warning_confirm: 1,
                water_critical_confirm: 1,
                rain_warning_confirm: 1,
                rain_critical_confirm: 1,
                gnss_hdop: 5.0,
                gnss_timeout: 180,
                water_warning: 0.10,
                water_critical: 0.20,
                rain_watch: 5.0,
                rain_warning: 15.0,
                rain_critical: 30.0,
                imu_tilt_crit: 8.0,
                imu_shock: 3.0,
                imu_critical_confirm: 1
            }
        };

        const preset = presets[presetName];
        if (!preset) return;

        // ✅ ĐIỀN TỰ ĐỘNG CÁC GIÁ TRỊ VÀO FORM

        // Rain/Water confirm steps - warning/critical tách riêng
        const rainWarningConfirmEl = document.getElementById('cfg-rain-warning-confirm');
        const rainCriticalConfirmEl = document.getElementById('cfg-rain-critical-confirm');
        const waterWarningConfirmEl = document.getElementById('cfg-water-warning-confirm');
        const waterCriticalConfirmEl = document.getElementById('cfg-water-critical-confirm');
        if (rainWarningConfirmEl) rainWarningConfirmEl.value = preset.rain_warning_confirm;
        if (rainCriticalConfirmEl) rainCriticalConfirmEl.value = preset.rain_critical_confirm;
        if (waterWarningConfirmEl) waterWarningConfirmEl.value = preset.water_warning_confirm;
        if (waterCriticalConfirmEl) waterCriticalConfirmEl.value = preset.water_critical_confirm;

        // Cập nhật source indicator
        const rainSrc = document.getElementById('cfg-rain-confirm-source');
        const waterSrc = document.getElementById('cfg-water-confirm-source');
        if (rainSrc) { rainSrc.textContent = '🔧 Từ preset: ' + presetName; rainSrc.className = 'text-info small'; }
        if (waterSrc) { waterSrc.textContent = '🔧 Từ preset: ' + presetName; waterSrc.className = 'text-info small'; }

        // GNSS Quality
        const gnssHdopEl = document.getElementById('cfg-gnss-hdop');
        const gnssWarningStepsEl = document.getElementById('cfg-gnss-warning-steps');
        const gnssCriticalStepsEl = document.getElementById('cfg-gnss-critical-steps');
        const gnssTimeoutEl = document.getElementById('cfg-gnss-timeout');

        if (gnssHdopEl) gnssHdopEl.value = preset.gnss_hdop;
        if (gnssWarningStepsEl) gnssWarningStepsEl.value = preset.gnss_warning_steps;
        if (gnssCriticalStepsEl) gnssCriticalStepsEl.value = preset.gnss_critical_steps;
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
        const imuTiltCritEl = document.getElementById('cfg-imu-tilt-crit');
        const imuShockEl = document.getElementById('cfg-imu-shock');
        const imuCriticalConfirmEl = document.getElementById('cfg-imu-critical-confirm');

        if (imuTiltCritEl) imuTiltCritEl.value = preset.imu_tilt_crit;
        if (imuShockEl) imuShockEl.value = preset.imu_shock;
        if (imuCriticalConfirmEl) imuCriticalConfirmEl.value = preset.imu_critical_confirm;

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

    getConfirmStepWarnings() {
        const readInt = (id, fallback) => {
            const val = parseInt(document.getElementById(id)?.value, 10);
            return Number.isFinite(val) ? val : fallback;
        };

        const checks = [
            {
                name: 'GNSS',
                warning: readInt('cfg-gnss-warning-steps', 3),
                critical: readInt('cfg-gnss-critical-steps', 2),
                safe: readInt('cfg-gnss-safe-steps', 5)
            },
            {
                name: 'Rain',
                warning: readInt('cfg-rain-warning-confirm', 2),
                critical: readInt('cfg-rain-critical-confirm', 1),
                safe: readInt('cfg-rain-safe-confirm', 3)
            },
            {
                name: 'Water',
                warning: readInt('cfg-water-warning-confirm', 3),
                critical: readInt('cfg-water-critical-confirm', 2),
                safe: readInt('cfg-water-safe-confirm', 3)
            },
            {
                name: 'IMU',
                critical: readInt('cfg-imu-critical-confirm', 1),
                safe: readInt('cfg-imu-safe-confirm', 3)
            }
        ];

        const warnings = [];
        checks.forEach((item) => {
            if (item.critical <= 0) {
                warnings.push(`${item.name}: Critical Confirm Steps phải >= 1`);
            }
            if (item.name !== 'IMU' && item.critical > item.warning) {
                warnings.push(`${item.name}: Critical Confirm Steps (${item.critical}) nên <= Warning (${item.warning}) để cảnh báo nặng phản ứng nhanh hơn`);
            }
            const compareBase = item.name === 'IMU' ? item.critical : Math.max(item.warning, item.critical);
            if (item.safe <= compareBase) {
                warnings.push(`${item.name}: Safe Confirm Steps (${item.safe}) nên lớn hơn ${item.name === 'IMU' ? 'Critical' : 'Warning/Critical'} (${item.name === 'IMU' ? item.critical : `${item.warning}/${item.critical}`})`);
            }
        });

        return warnings;
    }

    confirmConfirmStepWarnings() {
        const warnings = this.getConfirmStepWarnings();
        if (warnings.length === 0) return true;

        const message = [
            '⚠ Cảnh báo cấu hình Confirm Steps:',
            ...warnings.map(w => `- ${w}`),
            '',
            'Bạn vẫn muốn lưu cấu hình trạm?'
        ].join('\n');

        return confirm(message);
    }

    confirmDeviceProvisionWarnings(deviceCode) {
        const warnings = this.getConfirmStepWarnings();

        const message = warnings.length > 0
            ? [
                `⚠ Cảnh báo trước khi gán thiết bị ${deviceCode}:`,
                ...warnings.map(w => `- ${w}`),
                '',
                'Nếu vẫn tiếp tục, thiết bị sẽ dùng cấu hình confirm steps hiện tại của trạm.',
                'Bạn có muốn tiếp tục?'
            ].join('\n')
            : [
                `Xác nhận gán thiết bị ${deviceCode} vào trạm hiện tại?`,
                'Bạn có muốn tiếp tục?'
            ].join('\n');

        return confirm(message);
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
                const topic = topicInput?.value?.trim();

                if (!topic) {
                    window.toast?.error(`Vui lòng nhập MQTT Topic cho ${type.toUpperCase()}`);
                    topicInput?.focus();
                    hasError = true;
                    return;
                }

                const mqttHost = document.getElementById(`cfg-${type}-mqtt-host`)?.value?.trim() || null;
                const mqttPort = document.getElementById(`cfg-${type}-mqtt-port`)?.value ? parseInt(document.getElementById(`cfg-${type}-mqtt-port`).value) : null;
                const mqttTls = !!document.getElementById(`cfg-${type}-mqtt-tls`)?.checked;
                const mqttUser = document.getElementById(`cfg-${type}-mqtt-user`)?.value?.trim() || null;
                const mqttPass = document.getElementById(`cfg-${type}-mqtt-pass`)?.value?.trim() || null;

                sensors[type] = { 
                    topic: topic,
                    mqtt: {
                        host: mqttHost,
                        port: mqttPort,
                        use_tls: mqttTls,
                        username: mqttUser,
                        password: mqttPass
                    }
                };

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
        if (!this.confirmConfirmStepWarnings()) return;

        const finalRainWarningConfirm = parseInt(document.getElementById('cfg-rain-warning-confirm')?.value) || 2;
        const finalRainCriticalConfirm = parseInt(document.getElementById('cfg-rain-critical-confirm')?.value) || 1;
        const finalWaterWarningConfirm = parseInt(document.getElementById('cfg-water-warning-confirm')?.value) || 3;
        const finalWaterCriticalConfirm = parseInt(document.getElementById('cfg-water-critical-confirm')?.value) || 2;
        const finalGnssWarningConfirm = parseInt(document.getElementById('cfg-gnss-warning-steps')?.value) || 3;
        const finalGnssCriticalConfirm = parseInt(document.getElementById('cfg-gnss-critical-steps')?.value) || 2;
        const finalImuCriticalConfirm = parseInt(document.getElementById('cfg-imu-critical-confirm')?.value) || 1;

        // ✅ THÊM OFFLINE THRESHOLDS VÀO CONFIG
        const offlineThresholds = {
            gnss: parseInt(document.getElementById('offline-gnss')?.value) || this.defaultOfflineThresholds.gnss,
            rain: parseInt(document.getElementById('offline-rain')?.value) || this.defaultOfflineThresholds.rain,
            water: parseInt(document.getElementById('offline-water')?.value) || this.defaultOfflineThresholds.water,
            imu: parseInt(document.getElementById('offline-imu')?.value) || this.defaultOfflineThresholds.imu
        };

        // ✅ ĐỌC GNSS RTK FORWARDING CONFIG
        const rtkForwarding = {
            enabled: !!document.getElementById('cfg-fwd-enabled')?.checked,
            host: document.getElementById('gnss-rtk-host')?.value?.trim() || '',
            port: parseInt(document.getElementById('gnss-rtk-port')?.value) || 1883,
            username: document.getElementById('gnss-rtk-user')?.value?.trim() || '',
            password: document.getElementById('gnss-rtk-pass')?.value?.trim() || '',
            rtk_topic: document.getElementById('gnss-rtk-topic')?.value?.trim() || '',
            gnss_code: document.getElementById('gnss-rtk-code')?.value?.trim() || 'gnss_processed',
            fields: {
                X: !!document.getElementById('fwd-toggle-x')?.checked,
                Y: !!document.getElementById('fwd-toggle-y')?.checked,
                H: !!document.getElementById('fwd-toggle-h')?.checked,
                dX: !!document.getElementById('fwd-toggle-dx')?.checked,
                dY: !!document.getElementById('fwd-toggle-dy')?.checked,
                dH: !!document.getElementById('fwd-toggle-dh')?.checked,
                VdX: !!document.getElementById('fwd-toggle-vdx')?.checked,
                VdY: !!document.getElementById('fwd-toggle-vdy')?.checked,
                VdH: !!document.getElementById('fwd-toggle-vdh')?.checked
            }
        };

        const l0Raw = document.getElementById('vn-l0')?.value;
        const l0Parsed = this.parseVn2000CentralMeridian(l0Raw);
        const l0Input = document.getElementById('vn-l0');
        if (l0Input) l0Input.value = Number(l0Parsed.value.toFixed(10));

        const vn2000 = {
            enabled: !!document.getElementById('vn2000-enabled')?.checked,
            dx: parseFloat(document.getElementById('vn-dx')?.value) || 191.90441429,
            dy: parseFloat(document.getElementById('vn-dy')?.value) || 39.30318279,
            dz: parseFloat(document.getElementById('vn-dz')?.value) || 111.45032835,
            rx: parseFloat(document.getElementById('vn-rx')?.value) || 0.00928836,
            ry: parseFloat(document.getElementById('vn-ry')?.value) || -0.01975479,
            rz: parseFloat(document.getElementById('vn-rz')?.value) || 0.00427372,
            k: parseFloat(document.getElementById('vn-k')?.value) || 0.999999747093722,
            l0_deg: l0Parsed.value,
            l0_raw: String(l0Raw ?? '').trim(),
            l0_input_format: l0Parsed.format,
            k0: parseFloat(document.getElementById('vn-k0')?.value) || 0.9999,
            res_b: parseFloat(document.getElementById('vn-resb')?.value) || 0.0,
            res_l: parseFloat(document.getElementById('vn-resl')?.value) || 0.0,
            res_h: parseFloat(document.getElementById('vn-resh')?.value) || 0.0,
            res_n: parseFloat(document.getElementById('vn-resn')?.value) || 0.0,
            res_e: parseFloat(document.getElementById('vn-rese')?.value) || 0.0
        };

        const stationMqtt = {
            host: document.getElementById('station-mqtt-host')?.value?.trim() || '',
            port: document.getElementById('station-mqtt-port')?.value ? parseInt(document.getElementById('station-mqtt-port').value) : null,
            use_tls: !!document.getElementById('station-mqtt-tls')?.checked,
            username: document.getElementById('station-mqtt-user')?.value?.trim() || '',
            password: document.getElementById('station-mqtt-pass')?.value?.trim() || ''
        };

        const config = {
            active_preset: this.activePreset || '',
            alerting: {
                enabled: !document.getElementById('station-alerting-disabled')?.checked
            },
            offline_display: {
                enabled: !!document.getElementById('station-offline-display-enabled')?.checked
            },
            Water: {
                warning_threshold: parseFloat(document.getElementById('cfg-water-warning')?.value || 0),
                critical_threshold: parseFloat(document.getElementById('cfg-water-critical')?.value || 0),
                water_warning_confirm_steps: finalWaterWarningConfirm,
                water_critical_confirm_steps: finalWaterCriticalConfirm,
                water_confirm_steps: finalWaterWarningConfirm,
                water_safe_confirm_steps: parseInt(document.getElementById('cfg-water-safe-confirm')?.value) || 3
            },
            RainAlerting: {
                rain_intensity_watch_threshold: parseFloat(document.getElementById('cfg-rain-watch')?.value || 0),
                rain_intensity_warning_threshold: parseFloat(document.getElementById('cfg-rain-warning')?.value || 0),
                rain_intensity_critical_threshold: parseFloat(document.getElementById('cfg-rain-critical')?.value || 0),
                rain_warning_confirm_steps: finalRainWarningConfirm,
                rain_critical_confirm_steps: finalRainCriticalConfirm,
                rain_confirm_steps: finalRainWarningConfirm,
                rain_safe_confirm_steps: parseInt(document.getElementById('cfg-rain-safe-confirm')?.value) || 3
            },
            GnssAlerting: {
                gnss_max_hdop: parseFloat(document.getElementById('cfg-gnss-hdop')?.value || 4.0),
                gnss_warning_confirm_steps: finalGnssWarningConfirm,
                gnss_critical_confirm_steps: finalGnssCriticalConfirm,
                gnss_confirm_steps: finalGnssWarningConfirm,
                gnss_safe_confirm_steps: parseInt(document.getElementById('cfg-gnss-safe-steps')?.value) || 5,
                gnss_degraded_timeout: parseInt(document.getElementById('cfg-gnss-timeout')?.value || 300)
            },
            ImuAlerting: {
                tilt_critical_deg: parseFloat(document.getElementById('cfg-imu-tilt-crit')?.value || 15.0),
                tilt_warning_deg: parseFloat(document.getElementById('cfg-imu-tilt-crit')?.value || 15.0),
                imu_warning_confirm_steps: finalImuCriticalConfirm,
                imu_critical_confirm_steps: finalImuCriticalConfirm,
                imu_confirm_steps: finalImuCriticalConfirm,
                imu_safe_confirm_steps: parseInt(document.getElementById('cfg-imu-safe-confirm')?.value) || 3,
                shock_threshold_ms2: parseFloat(document.getElementById('cfg-imu-shock')?.value || 5.0)
            },
            ImuBaseline: {
                baseline_roll: parseFloat(document.getElementById('cfg-imu-base-roll')?.value) || 0.0,
                baseline_pitch: parseFloat(document.getElementById('cfg-imu-base-pitch')?.value) || 0.0,
                baseline_yaw: parseFloat(document.getElementById('cfg-imu-base-yaw')?.value) || 0.0
            },
            gnss_origin: {
                lat: document.getElementById('origin-lat')?.value || null,
                lon: document.getElementById('origin-lon')?.value || null,
                h: document.getElementById('origin-h')?.value || 0
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
            velocity_classification: this.velocityConfig,
            offline_thresholds: offlineThresholds,
            gnss_rtk_forwarding: rtkForwarding,
            vn2000: vn2000,
            vn2000_params: vn2000,
            mqtt: stationMqtt,
            save_intervals: {
                gnss: (document.getElementById('edit-gnss')?.checked && document.getElementById('cfg-station-save-gnss')?.value) ? parseInt(document.getElementById('cfg-station-save-gnss').value) : null,
                rain: (document.getElementById('edit-rain')?.checked && document.getElementById('cfg-station-save-rain')?.value) ? parseInt(document.getElementById('cfg-station-save-rain').value) : null,
                water: (document.getElementById('edit-water')?.checked && document.getElementById('cfg-station-save-water')?.value) ? parseInt(document.getElementById('cfg-station-save-water').value) : null,
                imu: (document.getElementById('edit-imu')?.checked && document.getElementById('cfg-station-save-imu')?.value) ? parseInt(document.getElementById('cfg-station-save-imu').value) : null
            }
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

    async resetGnssOrigin(stationId) {
        if (!stationId || Number.isNaN(Number(stationId))) {
            window.toast?.warning('Save station first before resetting GNSS origin');
            return;
        }
        if (!confirm('Reset GNSS origin for this station? The system will collect fresh samples for around 1 minute.')) return;

        const resetBtn = document.getElementById('btn-reset-origin');
        try {
            if (resetBtn) resetBtn.disabled = true;

            const res = await fetch(`/api/admin/gnss/reset-origin/${stationId}`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Unknown error');
            }

            const data = await res.json();
            window.toast?.success(`Origin reset sent for ${data.reset_count} device(s)`);

            // ✅ Xóa trắng các ô nhập liệu trên UI để người dùng thấy rõ hiệu ứng reset
            const latEl = document.getElementById('origin-lat');
            const lonEl = document.getElementById('origin-lon');
            const hEl = document.getElementById('origin-h');
            const statusEl = document.getElementById('origin-status');

            if (latEl) latEl.value = '';
            if (lonEl) lonEl.value = '';
            if (hEl) hEl.value = '';
            if (statusEl) {
                statusEl.innerHTML = '<i class="bi bi-hourglass-split me-1"></i> Đang thu thập điểm gốc mới...';
                statusEl.className = 'text-warning small';
            }

            this.startOriginResetCountdown(60);
        } catch (e) {
            window.toast?.error('Reset origin failed: ' + e.message);
        } finally {
            if (resetBtn) resetBtn.disabled = false;
        }
    }

    startOriginResetCountdown(seconds = 60) {
        const statusEl = document.getElementById('origin-status');
        if (!statusEl) return;

        if (this._originResetTimer) {
            clearInterval(this._originResetTimer);
            this._originResetTimer = null;
        }

        let remain = Math.max(1, Number(seconds) || 60);
        statusEl.innerHTML = `<span class="text-warning">Collecting GNSS samples for new origin: ${remain}s</span>`;

        this._originResetTimer = setInterval(() => {
            remain -= 1;
            if (remain > 0) {
                statusEl.innerHTML = `<span class="text-warning">Collecting GNSS samples for new origin: ${remain}s</span>`;
                return;
            }

            clearInterval(this._originResetTimer);
            this._originResetTimer = null;
            statusEl.innerHTML = '<span class="text-info">1 minute completed. Click "L?y t?a d?" to verify the new origin.</span>';
        }, 1000);
    }

    updateOriginActionButtons(hasOrigin) {
        const resetBtn = document.getElementById('btn-reset-origin');
        const fetchBtn = document.getElementById('btn-fetch-origin');
        if (resetBtn) resetBtn.style.display = hasOrigin ? 'inline-block' : 'none';
        if (fetchBtn) fetchBtn.style.display = 'inline-block';
    }

    // =========================================================================
    // iOS TOGGLE HANDLER (Forwarding Output params)
    // =========================================================================

    toggleForwardingWrap(eventOrWrap, wrapOrId, maybeCheckboxId) {
        const hasEvent = !!(maybeCheckboxId && eventOrWrap && typeof eventOrWrap === 'object');
        const event = hasEvent ? eventOrWrap : null;
        const wrapEl = hasEvent ? wrapOrId : eventOrWrap;
        const checkboxId = hasEvent ? maybeCheckboxId : wrapOrId;

        const checkbox = document.getElementById(checkboxId);
        if (!checkbox) return;

        if (event?.target?.closest('input')) {
            // Let native checkbox behavior run, then sync visual state.
            setTimeout(() => {
                wrapEl.classList.toggle('is-on', checkbox.checked);
            }, 0);
            return;
        }

        event?.preventDefault?.();
        checkbox.checked = !checkbox.checked;
        wrapEl.classList.toggle('is-on', checkbox.checked);
    }

    syncForwardingWrapStates() {
        const map = {
            'fwd-toggle-x': 'wrap-fwd-x',
            'fwd-toggle-y': 'wrap-fwd-y',
            'fwd-toggle-h': 'wrap-fwd-h',
            'fwd-toggle-dx': 'wrap-fwd-dx',
            'fwd-toggle-dy': 'wrap-fwd-dy',
            'fwd-toggle-dh': 'wrap-fwd-dh',
            'fwd-toggle-vdx': 'wrap-fwd-vdx',
            'fwd-toggle-vdy': 'wrap-fwd-vdy',
            'fwd-toggle-vdh': 'wrap-fwd-vdh',
        };
        for (const [cbId, wrapId] of Object.entries(map)) {
            const cb = document.getElementById(cbId);
            const wrap = document.getElementById(wrapId);
            if (cb && wrap) wrap.classList.toggle('is-on', cb.checked);
        }
    }

    toggleRtkForwardingSlide(animate = true) {
        const checkbox = document.getElementById('cfg-fwd-enabled');
        const content = document.getElementById('rtk-forwarding-content');
        if (!checkbox || !content) return;

        if (checkbox.checked) {
            content.style.display = 'block';
            if (animate) {
                content.style.maxHeight = '0px';
                content.style.opacity = '0';
                setTimeout(() => {
                    content.style.maxHeight = '600px';
                    content.style.opacity = '1';
                }, 10);
            } else {
                content.style.maxHeight = '600px';
                content.style.opacity = '1';
            }
        } else {
            if (animate) {
                content.style.maxHeight = '0px';
                content.style.opacity = '0';
                setTimeout(() => {
                    content.style.display = 'none';
                }, 300);
            } else {
                content.style.display = 'none';
            }
        }
    }


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

        this.refreshVelocityDescriptions();

        const unitOptions = [
            'mm/s', 'mm/day', 'mm/month', 'mm/year',
            'cm/day', 'cm/year',
            'm/s', 'm/min', 'm/hr', 'm/day', 'm/month', 'm/year'
        ];

        tbody.innerHTML = this.velocityConfig.map((vel, index) => {
            const unitSelectHtml = unitOptions.map(u =>
                `<option value="${u}"${u === vel.unit ? ' selected' : ''}>${u}</option>`
            ).join('');

            return `
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
                            <select class="form-select form-select-sm" style="max-width:110px;"
                                    onchange="window.adminManager.updateVelocityUnit(${index}, this.value)">
                                ${unitSelectHtml}
                            </select>
                        </div>
                    ` : `<code>${vel.threshold} ${vel.unit}</code>`}
                </td>
                <td class="text-muted small">${vel.description}</td>
            </tr>`;
        }).join('');
    }

    updateVelocityThreshold(index, newValue) {
        const value = parseFloat(String(newValue).replace(',', '.'));
        if (!isNaN(value)) {
            this.velocityConfig[index].threshold = value;
            this.renderVelocityTable();
        }
    }

    updateVelocityUnit(index, newUnit) {
        if (newUnit && this.velocityConfig[index]) {
            this.velocityConfig[index].unit = newUnit;
            this.renderVelocityTable();
        }
    }

    formatVelocityThreshold(value) {
        const num = Number(value);
        if (!Number.isFinite(num)) return '--';
        if (Math.abs(num) >= 1000) return num.toFixed(0);
        if (Math.abs(num) >= 10) return num.toFixed(2).replace(/\.00$/, '');
        if (Math.abs(num) >= 1) return num.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
        return num.toFixed(6).replace(/0+$/, '').replace(/\.$/, '');
    }

    refreshVelocityDescriptions() {
        if (!Array.isArray(this.velocityConfig) || this.velocityConfig.length === 0) return;

        const n = this.velocityConfig.length;
        for (let i = 0; i < n; i++) {
            const curr = this.velocityConfig[i] || {};
            const next = this.velocityConfig[i + 1] || null;

            const currVal = this.formatVelocityThreshold(curr.threshold);
            const currUnit = curr.unit || 'mm/s';

            if (i === 0 && next) {
                const nextVal = this.formatVelocityThreshold(next.threshold);
                const nextUnit = next.unit || currUnit;
                curr.description = `< ${nextVal} ${nextUnit}`;
            } else if (i === n - 1) {
                curr.description = `> ${currVal} ${currUnit}`;
            } else if (next) {
                const nextVal = this.formatVelocityThreshold(next.threshold);
                const nextUnit = next.unit || currUnit;
                curr.description = `${currVal} ${currUnit} to ${nextVal} ${nextUnit}`;
            }
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
                body: JSON.stringify({ 
                    topic: topic,
                    mqtt: {
                        host: document.getElementById('cfg-gnss-mqtt-host')?.value?.trim() || '',
                        port: document.getElementById('cfg-gnss-mqtt-port')?.value ? parseInt(document.getElementById('cfg-gnss-mqtt-port').value) : null,
                        username: document.getElementById('cfg-gnss-mqtt-user')?.value?.trim() || '',
                        password: document.getElementById('cfg-gnss-mqtt-pass')?.value?.trim() || '',
                        use_tls: !!document.getElementById('cfg-gnss-mqtt-tls')?.checked
                    }
                })
            });

            const result = await res.json();

            if (res.ok) {
                const latEl = document.getElementById('origin-lat');
                const lonEl = document.getElementById('origin-lon');
                const hEl = document.getElementById('origin-h');
                const currentLat = parseFloat(latEl?.value);
                const currentLon = parseFloat(lonEl?.value);
                const currentH = parseFloat(hEl?.value);
                const hasOrigin = Number.isFinite(currentLat) && Number.isFinite(currentLon);

                if (!hasOrigin) {
                    // No existing origin -> allow filling
                    if (latEl) latEl.value = result.lat;
                    if (lonEl) lonEl.value = result.lon;
                    if (hEl) hEl.value = result.h;
                    this.updateOriginActionButtons(true);

                    statusEl.innerHTML = `<span class="text-success">✅ Đã nhận: Sats ${result.num_sats}, Fix ${result.fix_quality}</span>`;
                    window.toast?.success('Đã lấy tọa độ thực từ thiết bị!');
                } else {
                    // Existing origin -> verification only, do NOT overwrite locked origin fields
                    const deltaM = this.computeGeoDistanceMeters(currentLat, currentLon, result.lat, result.lon);
                    const deltaH = Number.isFinite(currentH) ? (result.h - currentH) : 0;
                    statusEl.innerHTML = `<span class="text-info">â„¹ Live check: Î”xy=${deltaM.toFixed(3)}m, Î”h=${deltaH.toFixed(3)}m (Sats ${result.num_sats}, Fix ${result.fix_quality})</span>`;
                    window.toast?.info('Đã kiểm tra live GNSS. Origin hiện tại không bị ghi đè.');
                }
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

    computeGeoDistanceMeters(lat1, lon1, lat2, lon2) {
        const toRad = (v) => (Number(v) * Math.PI) / 180;
        const R = 6371000;
        const p1 = toRad(lat1);
        const p2 = toRad(lat2);
        const dLat = toRad(lat2 - lat1);
        const dLon = toRad(lon2 - lon1);
        const a = Math.sin(dLat / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * (Math.sin(dLon / 2) ** 2);
        return 2 * R * Math.asin(Math.sqrt(a));
    }

    // =========================================================================
    // PENDING DEVICES (ADMIN PROVISIONING)
    // =========================================================================

    async loadAdminPendingDevices() {
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
                                ${d.config?.license ? '<span class="text-success">✅ ' + d.config.license + '</span>' : '<span class="text-warning">⚠ï¸ Chưa có license</span>'}
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

        if (!this.confirmDeviceProvisionWarnings(device_code)) return;

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
            this.loadAdminPendingDevices();
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

        if (!this.confirmDeviceProvisionWarnings(device_code)) return;

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
            this.loadAdminPendingDevices();
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
            if ((u.role === 'operator' || u.role === 'viewer') && u.assigned_projects && u.assigned_projects.length > 0) {
                projectBadges = `<br><small class="text-muted">Dự án: ${u.assigned_projects.map(
                    pid => `<span class="badge bg-dark text-info border border-info" style="font-size:.65rem">${this.getProjectName(pid)}</span>`
                ).join(' ')}</small>`;
            } else if (u.role === 'viewer') {
                projectBadges = `<br><small class="text-muted">Dự án: <span class="badge bg-dark text-success border border-success" style="font-size:.65rem">Tất cả</span></small>`;
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
                        ${(u.role === 'operator' || u.role === 'viewer') ? `<button class="btn btn-outline-info" onclick="window.adminManager.showAssignProjectsModal(${u.id}, '${u.username}')" title="Gán dự án"><i class="bi bi-folder-plus"></i></button>` : ''}
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
                    assigned_projects: (role === 'operator' || role === 'viewer') ? assignedProjects : []
                })
            });

            if (res.ok) {
                window.toast?.success('✅ Tạo tài khoản thành công');
                bootstrap.Modal.getInstance(document.getElementById('addUserModal'))?.hide();
                document.getElementById('addUserForm').reset();
                document.getElementById('project-assign-group').style.display = 'block';
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

    /** Apply viewer restrictions â€” hide all edit/create/delete UI elements */
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
            let statusBadge = `<span class="badge" style="background:${color};color:#000;font-size:.72rem">â— ${statusLabels[c.status] || c.status}</span>`;
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
                    const pLastPingText = p.last_seen ? this._formatTimeAgo(p.last_seen, pIsOnline) : 'â€”';
                    return `
                    <div style="margin-top: 6px; padding: 4px 8px; background-color: rgba(255, 193, 7, 0.15); border-left: 3px solid #ffc107; border-radius: 4px; font-size: 0.75rem; display: inline-block;">
                        <span class="badge bg-warning text-dark me-1" style="font-size:.6rem">Pi Hiện trường</span>
                        <strong style="color:var(--text-color)">${p.name}</strong>
                        <code class="text-muted mx-1">${p.serial}</code>
                        <span class="mx-1" style="font-size: 0.7rem; color: ${pIsOnline ? '#10b981' : '#ef4444'}">â— ${pLastPingText}</span>
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
            const lastPingText = c.last_seen ? this._formatTimeAgo(c.last_seen, isOnline) : 'â€”';

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
            <td><span class="${isOnline ? 'ping-online' : 'ping-offline'} me-1">â—</span><small>${lastPingText}</small></td>
        </tr>`;
        });

        // Những điểm (pi points) chưa được gán pi_center_id sẽ nằm riêng ở cuối
        // unassignedPoints đã được khai báo ở đầu hàm (line 1827)
        unassignedPoints.forEach(p => {
            const pColor = statusColors[p.status] || '#6b7280';
            let pStatusBadge = `<span class="badge" style="background:${pColor};color:#000;font-size:.72rem">â— ${statusLabels[p.status] || p.status}</span>`;
            if (p.is_locked) {
                pStatusBadge += ` <span class="badge bg-danger" style="font-size:.65rem" title="Thiết bị bị khóa">🔒</span>`;
            }

            const nameLabel = `<strong>${p.name}</strong><br><small class="text-muted"><span class="badge bg-warning text-dark me-1" style="font-size:.6rem">Pi Hiện trường</span><span style="font-size:.6rem">(Chưa Gắn)</span></small>`;
            const pIsOnline = p.last_seen && (Date.now() / 1000 - p.last_seen) < 120;
            const pLastPingText = p.last_seen ? this._formatTimeAgo(p.last_seen, pIsOnline) : 'â€”';

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
                <td><span class="${pIsOnline ? 'ping-online' : 'ping-offline'} me-1">â—</span><small>${pLastPingText}</small></td>
            </tr>`;
        });

        tbody.innerHTML = html;
        if (infoEl) infoEl.textContent = `Showing 1 to ${devices.length} of ${devices.length} entries`;
    }

    /** Format epoch timestamp to human-readable time ago */
    _formatTimeAgo(epoch, isOnline) {
        if (!epoch) return 'â€”';
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
                                        <button type="button" class="list-group-item list-group-item-action d-flex gap-3 align-items-center center-pick-item"
                                               data-center-id="${c.id}" style="cursor:pointer; background:transparent; border-color:var(--border-color)">
                                            <div class="pick-indicator"><i class="bi bi-check-lg"></i></div>
                                            <div class="text-start">
                                                <strong>${c.name}</strong>
                                                <small class="d-block text-muted font-monospace">${c.serial}</small>
                                                ${c.station_name ? `<small class="text-info">📍 ${c.station_name}</small>` : ''}
                                            </div>
                                            <span class="badge ${c.status === 'assigned' ? 'bg-primary' : 'bg-success'} ms-auto">${c.status === 'assigned' ? '📍 Assigned' : '✅ Activated'}</span>
                                        </button>
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

            let selectedCenterId = null;
            modal.querySelectorAll('.center-pick-item').forEach(item => {
                item.addEventListener('click', () => {
                    modal.querySelectorAll('.center-pick-item').forEach(x => x.classList.remove('is-selected'));
                    item.classList.add('is-selected');
                    selectedCenterId = parseInt(item.dataset.centerId, 10);
                });
            });

            document.getElementById('btn-confirm-center-pick').addEventListener('click', async () => {
                if (!selectedCenterId) {
                    window.toast?.warning('Vui lòng chọn Pi Trung tâm');
                    return;
                }
                const centerId = selectedCenterId;

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
        const optionsBox = document.getElementById('point-device-options');
        if (select) select.value = '';
        if (optionsBox) optionsBox.innerHTML = '<div class="text-muted small">-- Đang tải ... --</div>';

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
                if (optionsBox) {
                    optionsBox.innerHTML = '<div class="text-muted small">(Không có Pi Hiện trường nào đang rảnh và đã Activated)</div>';
                }
            } else {
                if (optionsBox) {
                    optionsBox.innerHTML = pointsToAssign.map(p => `
                        <button type="button" class="device-pick-option" data-point-id="${p.id}">
                            <div class="pick-indicator"><i class="bi bi-check-lg"></i></div>
                            <div class="text-start">
                                <strong>${p.name}</strong>
                                <small class="d-block text-muted font-monospace">${p.serial}</small>
                            </div>
                            <span class="badge bg-success ms-auto">✅ Activated</span>
                        </button>
                    `).join('');

                    optionsBox.querySelectorAll('.device-pick-option').forEach(item => {
                        item.addEventListener('click', () => {
                            optionsBox.querySelectorAll('.device-pick-option').forEach(x => x.classList.remove('is-selected'));
                            item.classList.add('is-selected');
                            if (select) select.value = item.dataset.pointId || '';
                        });
                    });
                }
            }
        } catch (e) {
            console.error(e);
            if (optionsBox) optionsBox.innerHTML = '<div class="text-danger small">(Lỗi tải danh sách)</div>';
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
    async loadWizardPendingDevices() {
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
                    <button type="button" class="list-group-item list-group-item-action d-flex gap-3 align-items-center wizard-pi-option"
                           data-pi-id="${d.id}" style="cursor:pointer; background:transparent; border-color:var(--border-color)">
                        <div class="pick-indicator"><i class="bi bi-check-lg"></i></div>
                        <div class="text-start">
                            <strong class="font-monospace">${d.name}</strong>
                            <small class="d-block text-muted font-monospace">${d.serial}</small>
                        </div>
                        <span class="badge bg-success ms-auto">✅ Sẵn sàng</span>
                    </button>
                `).join('')}
                </div>`;

            if (btnRow) btnRow.style.display = 'block';
            this._selectedWizardPiId = null;

            // Show assign button row only when a Pi is selected
            listEl.querySelectorAll('.wizard-pi-option').forEach(r => {
                r.addEventListener('click', () => {
                    listEl.querySelectorAll('.wizard-pi-option').forEach(x => x.classList.remove('is-selected'));
                    r.classList.add('is-selected');
                    this._selectedWizardPiId = parseInt(r.dataset.piId, 10);
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
        const piId = this._selectedWizardPiId;
        if (!piId) {
            window.toast?.warning('Vui lòng chọn một Pi');
            return;
        }
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
            this.loadWizardPendingDevices();
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
            this.loadWizardPendingDevices();
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

    logout() {
        console.log('[SPA-NAV] admin logout redirect landing', {
            path: window.location.pathname,
            search: window.location.search,
        });
        window.SPA_SUPPRESS_AUTO_MAP_ON_LANDING = true;
        localStorage.removeItem('token');
        window.location.href = '/';
    }

    toggleVn2000AdvancedSlide(animate = true) {
        const checkbox = document.getElementById('vn2000-enabled');
        const content = document.getElementById('vn2000-advanced-content');
        if (!checkbox || !content) return;

        if (checkbox.checked) {
            content.style.display = 'block';
            content.style.maxHeight = animate ? '0px' : 'none';
            if (animate) {
                setTimeout(() => {
                    content.style.maxHeight = '1000px';
                }, 10);
            }
        } else {
            if (animate) {
                content.style.maxHeight = '0px';
                setTimeout(() => {
                    content.style.display = 'none';
                }, 300);
            } else {
                content.style.display = 'none';
            }
        }
    }

    toggleRtkForwardingSlide(animate = true) {
        const checkbox = document.getElementById('cfg-fwd-enabled');
        const content = document.getElementById('rtk-forwarding-content');
        if (!checkbox || !content) return;

        if (checkbox.checked) {
            content.style.display = 'block';
            content.style.maxHeight = animate ? '0px' : 'none';
            if (animate) {
                setTimeout(() => {
                    content.style.maxHeight = '2000px';
                }, 10);
            }
        } else {
            if (animate) {
                content.style.maxHeight = '0px';
                setTimeout(() => {
                    content.style.display = 'none';
                }, 300);
            } else {
                content.style.display = 'none';
            }
        }
    }
}

// =========================================================================
// INITIALIZATION
// =========================================================================
async function bootstrapAdminManager() {
    const hasAdminDom = document.getElementById('projects-content-area');
    if (hasAdminDom && !window.adminManager) {
        window.adminManager = new AdminManager();
    } else if (!hasAdminDom) {
        console.error('[ADMIN] Dashboard DOM element missing');
        return;
    }

    const token = localStorage.getItem('token') || sessionStorage.getItem('token');
    if (!token) return;

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
                    console.log('[ADMIN] System tab enabled');
                }
            }
        }
    } catch (e) {
        console.error('[ADMIN] Error updating admin UI:', e);
    }
}

window.bootstrapAdminManager = bootstrapAdminManager;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapAdminManager, { once: true });
} else {
    bootstrapAdminManager();
}


