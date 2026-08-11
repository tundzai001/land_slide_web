// =====================================================
// ADMIN MANAGER - COMPLETE VERSION WITH ALL FEATURES
// =====================================================

class AdminManager {
    constructor() {
        this.token = window.authSession?.getToken() || null;
        this._disposed = false;
        this._refreshIntervals = [];
        this._wsReconnectTimer = null;
        this._spaNavigateHandler = (event) => {
            if (event.detail?.view !== 'admin') this.dispose();
        };
        window.addEventListener('spa:navigate', this._spaNavigateHandler);

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
            window.location.href = '/login?return_to=%2Fmanagement';
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

    async setupWebSocketListener() {
        if (this._disposed || document.documentElement.dataset.appView !== 'admin') return;

        try {
            const ticketResponse = await fetch('/api/auth/ws-ticket', {
                method: 'POST',
                headers: { Authorization: `Bearer ${this.token}` },
                cache: 'no-store',
            });
            if (!ticketResponse.ok) throw new Error(`WebSocket ticket HTTP ${ticketResponse.status}`);
            const { ticket } = await ticketResponse.json();
            if (this._disposed || document.documentElement.dataset.appView !== 'admin') return;

            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/admin?ticket=${encodeURIComponent(ticket)}`;
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
                if (this._disposed || document.documentElement.dataset.appView !== 'admin') return;
                // Thử kết nối lại sau 5 giây nếu mất kết nối
                this._wsReconnectTimer = setTimeout(() => {
                    this._wsReconnectTimer = null;
                    this.setupWebSocketListener();
                }, 5000);
            };
        } catch (e) {
            console.warn('Admin WebSocket unavailable:', e);
            if (!this._disposed && document.documentElement.dataset.appView === 'admin') {
                this._wsReconnectTimer = setTimeout(() => {
                    this._wsReconnectTimer = null;
                    this.setupWebSocketListener();
                }, 5000);
            }
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

                    if (type === 'gnss' && e.target.checked) {
                        this.loadAICasterUsers();
                    }

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
        this._refreshIntervals.push(setInterval(() => {
            const piTab = document.getElementById('tab-pi');
            if (piTab && piTab.classList.contains('active')) {
                this.loadPiDevices(true);
            }
        }, 15000));

        this._refreshIntervals.push(setInterval(() => {
            const rescueTab = document.getElementById('tab-rescue');
            if (rescueTab && rescueTab.classList.contains('active')) {
                this.loadRescueRequests(true);
            }
        }, 20000));

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
            const protectedImageUrl = /^\/api\/admin\/rescue-images\/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(imageUrl)
                ? imageUrl
                : '';
            const imageHtml = protectedImageUrl
                ? `<img data-auth-src="${esc(protectedImageUrl)}" alt="rescue-evidence" style="width:72px;height:72px;object-fit:cover;border-radius:8px;border:1px solid #ddd;">`
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
        void window.hydrateAuthenticatedImages?.(body);
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

}

window.AdminManager = AdminManager;
window.applyAdminFeature = function applyAdminFeature(FeatureClass) {
    Object.getOwnPropertyNames(FeatureClass.prototype).filter((name) => name !== 'constructor').forEach((name) => {
        Object.defineProperty(
            AdminManager.prototype,
            name,
            Object.getOwnPropertyDescriptor(FeatureClass.prototype, name),
        );
    });
};
