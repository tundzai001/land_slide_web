// =====================================================
// ADMIN MANAGER - COMPLETE VERSION WITH ALL FEATURES
// =====================================================

class AdminManager {
    constructor() {
        this.token = window.authSession?.getToken() || null;
        this._disposed = false;
        this._refreshIntervals = [];
        this._wsReconnectTimer = null;
        this._wsConnecting = false;
        this.operationsWs = null;
        this._operationsWsReconnectTimer = null;
        this._operationsWsConnecting = false;
        this._authzChangeHandler = (event) => this.applyAuthzSession(event.detail?.user || null);
        this._authzExpiredHandler = () => {
            this._tabRequestControllers?.forEach?.(controller => controller.abort());
            this._tabRequestControllers?.clear?.();
            this.operationsWs?.close?.(1000, 'authorization grace expired');
            this.ws?.close?.(1000, 'authorization grace expired');
        };
        this._popstateHandler = () => {
            const tab = new URLSearchParams(window.location.search).get('tab') || history.state?.adminTab;
            if (tab) {
                const control = Array.from(document.querySelectorAll('[data-tab]')).find(el => el.dataset.tab === tab) || null;
                this.switchTab(tab, control, true, { replace: true, restore: true });
            }
        };
        window.addEventListener('authzChanged', this._authzChangeHandler);
        window.addEventListener('authzExpired', this._authzExpiredHandler);
        window.addEventListener('popstate', this._popstateHandler);
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
        this.rescueState = { status: 'pending', q: '', sort: 'created_at', offset: 0, limit: 25, total: 0, rows: [] };
        this.rescueSearchTimer = null;
        this.selectedRescueRequest = null;

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
        if (this._wsConnecting) return;
        this._wsConnecting = true;

        try {
            const ticketResponse = await fetch('/api/auth/ws-ticket', {
                method: 'POST',
                headers: { Authorization: `Bearer ${this.token}` },
                cache: 'no-store',
            });
            if (!ticketResponse.ok) throw new Error(`WebSocket ticket HTTP ${ticketResponse.status}`);
            const { ticket } = await ticketResponse.json();
            if (this._disposed || document.documentElement.dataset.appView !== 'admin') { this._wsConnecting = false; return; }

            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/admin?ticket=${encodeURIComponent(ticket)}`;
            this.ws = new WebSocket(wsUrl);
            this._wsConnecting = false;
            this.ws.onmessage = (event) => {
                let message;
                try { message = JSON.parse(event.data); } catch (_) { return; }
                if (message.type === 'incident_changed') {
                    window.incidentStore?.applyEnvelope(message);
                    window.dispatchEvent(new CustomEvent('incidentChanged', { detail: message }));
                    window.loadAdminIncidents?.(true);
                    return;
                }
                if (message.type === 'origin_locked_event' && message.station_id == this.currentStationId) {
                    console.log('🎯 GNSS Origin Locked via WebSocket:', message.data);
                    const relocked = !!message.data?.relocked;

                    // Cập nhật ngay lập tức lên UI
                    const latEl = document.getElementById('origin-lat');
                    const lonEl = document.getElementById('origin-lon');
                    const hEl = document.getElementById('origin-h');
                    const statusEl = document.getElementById('origin-status');

                    if (latEl) latEl.value = message.data.lat;
                    if (lonEl) lonEl.value = message.data.lon;
                    if (hEl) hEl.value = message.data.h;

                    if (statusEl) {
                        statusEl.innerHTML = relocked
                            ? '<span class="text-success fw-bold"><i class="bi bi-check-circle-fill me-1"></i> Đã khóa lại tọa độ gốc mới.</span>'
                            : '<span class="text-success fw-bold"><i class="bi bi-check-circle-fill me-1"></i> Đã tự động cập nhật điểm gốc mới!</span>';
                        statusEl.className = 'small mt-1';
                    }

                    window.toast?.success(relocked
                        ? 'Đã khóa lại tọa độ gốc GNSS.'
                        : 'Thiết bị đã tự động khóa điểm gốc mới và cập nhật lên màn hình!');
                } else if (message.type === 'gnss_origin_relock_progress' &&
                    (message.station_id == this.currentStationId ||
                        message.station_id == this._gnssOriginRelockStationId)) {
                    const progress = message.data || {};
                    const statusEl = document.getElementById('origin-status');
                    const button = document.getElementById('btn-relock-origin');
                    if (progress.phase === 'complete') {
                        const isActiveStation = message.station_id == this.currentStationId;
                        const isLocalOperation = message.station_id == this._gnssOriginRelockStationId;
                        if (isLocalOperation) {
                            this._gnssOriginRelockCompleted = true;
                            this._gnssOriginRelockInProgress = false;
                            this._gnssOriginRelockStationId = null;
                        }
                        if (isActiveStation || isLocalOperation) {
                            if (button) button.disabled = false;
                            ['btn-reset-origin', 'btn-fetch-origin'].forEach(id => {
                                const relatedButton = document.getElementById(id);
                                if (relatedButton) relatedButton.disabled = false;
                            });
                        }
                        if (isActiveStation) {
                            this.updateGnssOriginRelockProgress?.(progress);
                            if (statusEl) {
                                statusEl.innerHTML = '<span class="text-success"><i class="bi bi-check-circle me-1" aria-hidden="true"></i>Đã khóa lại gốc; chuyển vị tracking tính từ mốc mới.</span>';
                                statusEl.className = 'text-success small';
                            }
                            this.renderGnssTrackingOffset?.([0, 0, 0], {
                                state: 'Gốc mới đã khóa',
                                source: `${progress.sample_count || 0} mẫu RTK FIXED`,
                                duration: `${Number(progress.duration_s || 0).toFixed(1)} giây`,
                            });
                        }
                    } else if (progress.phase === 'failed') {
                        const isActiveStation = message.station_id == this.currentStationId;
                        const isLocalOperation = message.station_id == this._gnssOriginRelockStationId;
                        if (isLocalOperation) {
                            this._gnssOriginRelockInProgress = false;
                            this._gnssOriginRelockStationId = null;
                        }
                        if (isActiveStation || isLocalOperation) {
                            if (button) button.disabled = false;
                            ['btn-reset-origin', 'btn-fetch-origin'].forEach(id => {
                                const relatedButton = document.getElementById(id);
                                if (relatedButton) relatedButton.disabled = false;
                            });
                        }
                        if (isActiveStation) {
                            this.updateGnssOriginRelockProgress?.(progress);
                            if (statusEl) {
                                statusEl.textContent = progress.message || 'Không thể khóa lại tọa độ gốc.';
                                statusEl.className = 'text-danger small';
                            }
                            window.toast?.error(progress.message || 'Không thể khóa lại tọa độ gốc.');
                        }
                    } else if (message.station_id == this.currentStationId) {
                        this.updateGnssOriginRelockProgress?.(progress);
                        if (statusEl) {
                            statusEl.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Đang thu mẫu RTK FIXED ổn định…';
                            statusEl.className = 'text-info small';
                        }
                        [button, document.getElementById('btn-reset-origin'), document.getElementById('btn-fetch-origin')]
                            .filter(Boolean).forEach(actionButton => { actionButton.disabled = true; });
                    }
                } else if (message.type === 'gnss_offset_calibration_progress' &&
                    (message.station_id == null || message.station_id == this.currentStationId)) {
                    const progress = message.data || {};
                    const statusEl = document.getElementById('origin-status');
                    if (statusEl && (this._gnssCalibrationInProgress || progress.phase === 'complete')) {
                        if (progress.phase === 'complete') {
                            statusEl.innerHTML = '<span class="text-success"><i class="bi bi-check-circle me-1" aria-hidden="true"></i>Backend đã thu đủ mẫu và áp dụng offset.</span>';
                            statusEl.className = 'text-success small';
                            this._gnssCalibrationCompleted = true;
                            this._gnssCalibrationInProgress = false;
                            const resetBtn = document.getElementById('btn-reset-origin');
                            if (resetBtn) resetBtn.disabled = false;
                            Promise.resolve(this.refreshGnssTrackingOffset?.(this.currentStationId)).catch(() => {});
                        } else {
                            const duration = Number(progress.duration_s || 0).toFixed(1);
                            const remaining = Math.max(0, Math.ceil(Number(progress.remaining_s || 0)));
                            const sampleCount = Number(progress.sample_count || 0);
                            const minimumSamples = Number(progress.minimum_samples || 61);
                            const intervalCount = Math.max(0, sampleCount - 1);
                            const minimumDuration = Number(progress.minimum_duration_s || 60).toFixed(1);
                            statusEl.innerHTML = `<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Đang thu RTK FIXED… ${sampleCount}/${minimumSamples} mẫu · ${intervalCount} khoảng đo · ${duration}/${minimumDuration}s · còn ${remaining}s`;
                            statusEl.className = 'text-info small';
                        }
                    }
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
            this._wsConnecting = false;
            console.warn('Admin WebSocket unavailable:', e);
            if (!this._disposed && document.documentElement.dataset.appView === 'admin') {
                this._wsReconnectTimer = setTimeout(() => {
                    this._wsReconnectTimer = null;
                    this.setupWebSocketListener();
                }, 5000);
            }
        }
    }

    async setupOperationsWebSocket() {
        if (this._disposed || document.documentElement.dataset.appView !== 'admin' || this._operationsWsConnecting || this.operationsWs) return;
        this._operationsWsConnecting = true;
        try {
            const response = await fetch('/api/auth/ws-ticket', { method: 'POST', headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ channel: 'operations' }), cache: 'no-store' });
            if (!response.ok) throw new Error(`Operations ticket HTTP ${response.status}`);
            const { ticket } = await response.json();
            if (this._disposed || document.documentElement.dataset.appView !== 'admin') { this._operationsWsConnecting = false; return; }
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const socket = new WebSocket(`${protocol}//${window.location.host}/ws/operations?ticket=${encodeURIComponent(ticket)}`);
            this.operationsWs = socket; this._operationsWsConnecting = false;
            socket.onopen = () => {
                const projects = (this.currentUserAssignedProjects || window.authManager?.getUserInfo?.()?.assigned_projects || []).map(Number).filter(Number.isFinite);
                socket.send(JSON.stringify({ type: 'subscribe', project_ids: projects, station_ids: [], channels: ['incident'] }));
                document.documentElement.dataset.incidentsRealtime = 'connected';
            };
            socket.onmessage = event => {
                try { const message = JSON.parse(event.data); if (message.type === 'incident_changed') { window.incidentStore?.applyEnvelope(message); window.dispatchEvent(new CustomEvent('incidentChanged', { detail: message })); } } catch (_) { /* malformed private event is ignored */ }
            };
            socket.onerror = () => { document.documentElement.dataset.incidentsRealtime = 'degraded'; };
            socket.onclose = () => {
                if (this.operationsWs !== socket) return;
                this.operationsWs = null; document.documentElement.dataset.incidentsRealtime = 'disconnected';
                if (!this._disposed && document.documentElement.dataset.appView === 'admin') this._operationsWsReconnectTimer = setTimeout(() => { this._operationsWsReconnectTimer = null; this.setupOperationsWebSocket(); }, 5000);
            };
        } catch (_) {
            this._operationsWsConnecting = false; document.documentElement.dataset.incidentsRealtime = 'degraded';
            if (!this._disposed && document.documentElement.dataset.appView === 'admin') this._operationsWsReconnectTimer = setTimeout(() => { this._operationsWsReconnectTimer = null; this.setupOperationsWebSocket(); }, 5000);
        }
    }

    /** Switch visible tab pane (called from sidebar icons) */
    switchTab(tabId, linkEl, loadData = true, options = {}) {
        if (!this.canAccessTab(tabId)) {
            linkEl?.setAttribute('aria-disabled', 'true');
            window.toast?.warning?.('Bạn không có quyền mở khu vực này.');
            return false;
        }
        // Hide all tab panes
        if (tabId !== 'tab-operations') this.closeOperationInspector?.();
        document.querySelectorAll('#admin-tab-content > .tab-pane').forEach(p => {
            p.classList.remove('show', 'active');
        });
        // Show target pane
        const target = document.getElementById(tabId);
        if (target) {
            target.classList.add('show', 'active');
        }
        // One active-state source for desktop rail, mobile navigation and More sheet.
        document.querySelectorAll('[data-tab]').forEach(control => {
            const active = control.dataset.tab === tabId;
            control.classList.toggle('active', active);
            if (active) control.setAttribute('aria-current', 'page');
            else control.removeAttribute('aria-current');
        });
        const previousTabId = this.currentTabId;
        this.currentTabId = tabId;
        const url = new URL(window.location.href);
        url.searchParams.set('tab', tabId);
        const state = { ...(history.state || {}), adminTab: tabId };
        if (options.replace || options.restore || previousTabId === tabId) history.replaceState(state, '', url);
        else history.pushState(state, '', url);
        if (!options.restore) linkEl?.focus?.({ preventScroll: true });

        if (!loadData) return;
        // Trigger data loading for specific tabs
        if (tabId === 'tab-projects') {
            this.resetNavigation?.();
            this.loadProjects?.();
        } else if (tabId === 'tab-database') {
            window.dbManager?.loadAllData?.();
        } else if (tabId === 'tab-operations') {
            this.loadOperations?.();
        } else if (tabId === 'tab-simulations') {
            this.loadSimulationRuns?.();
        } else if (tabId === 'tab-pi') {
            this.loadPiDevices?.();
        } else if (tabId === 'tab-rescue') {
            this.loadRescueRequests?.();
        } else if (tabId === 'tab-users') {
            this.loadUsers?.();
        }
        return true;
    }

    hasPermission(permission) {
        const permissions = this.currentUserPermissions || this.currentUser?.permissions || [];
        return permissions.includes(permission) || this.currentUserRole === 'admin';
    }

    canAccessTab(tabId) {
        const required = {
            'tab-users': 'MANAGE_USERS',
            'tab-projects': 'VIEW_STATIONS',
            'tab-database': 'MANAGE_DATABASE',
            'tab-operations': 'MANAGE_DATABASE',
            'tab-simulations': 'MANAGE_SIMULATIONS',
            'tab-pi': 'VIEW_FIELD_DEVICES',
            'tab-rescue': 'MANAGE_RESCUE',
        }[tabId];
        return !required || this.hasPermission(required);
    }

    applyPermissionVisibility() {
        document.querySelectorAll('[data-tab]').forEach(control => {
            const allowed = this.canAccessTab(control.dataset.tab);
            control.classList.toggle('is-locked', !allowed);
            control.toggleAttribute('aria-disabled', !allowed);
            if (!allowed) {
                control.setAttribute('title', 'Bạn không có quyền mở khu vực này');
            } else {
                control.removeAttribute('title');
            }
            const item = control.closest('.nav-item');
            if (item) item.classList.toggle('is-locked', !allowed);
        });
        document.querySelectorAll('[data-private-permission]').forEach(control => {
            const allowed = this.hasPermission(control.dataset.privatePermission);
            control.toggleAttribute('disabled', !allowed);
            control.toggleAttribute('aria-disabled', !allowed);
            control.classList.toggle('is-locked', !allowed);
        });
    }

    _safeFallbackTab() {
        return ['tab-projects', 'tab-pi', 'tab-rescue', 'tab-database', 'tab-simulations', 'tab-users']
            .find(tab => this.canAccessTab(tab)) || 'tab-projects';
    }

    async applyAuthzSession(user) {
        if (this._disposed) return;
        this.currentUser = user || null;
        this.currentUserRole = user?.role || '';
        this.currentUserAssignedProjects = user?.assigned_projects || [];
        this.currentUserPermissions = user?.permissions || [];
        this.applyPermissionVisibility();
        if (!this.canAccessTab(this.currentTabId)) {
            this.closeRescueInspector?.();
            this.closeOperationInspector?.();
            window.dbManager?.closeInspector?.();
            window.dbManager?.datasetRequestController?.abort?.();
            this.switchTab(this._safeFallbackTab(), null, true, { replace: true, restore: true });
        }
        if (this.hasPermission('VIEW_INCIDENTS')) {
            this.setupOperationsWebSocket();
        } else if (this.operationsWs) {
            this.operationsWs.close(1000, 'authorization changed');
            this.operationsWs = null;
        }
        if (this.currentUserRole === 'admin' && !this.ws) this.setupWebSocketListener();
        if (this.currentUserRole !== 'admin' && this.ws) {
            this.ws.close(1000, 'authorization changed');
            this.ws = null;
        }
    }

    async bootstrapRoleFirst() {
        const user = await this.fetchCurrentUserRole();
        if (this._disposed || !user) return;
        this.applyPermissionVisibility();
        const requested = new URLSearchParams(window.location.search).get('tab') || history.state?.adminTab;
        const initialTab = requested && this.canAccessTab(requested) ? requested : this._safeFallbackTab();
        const initialControl = Array.from(document.querySelectorAll('[data-tab]')).find(el => el.dataset.tab === initialTab) || null;
        this.switchTab(initialTab, initialControl, false, { replace: true, restore: true });
        if (initialTab === 'tab-operations') this.loadOperations?.();
        if (this.canAccessTab('tab-projects')) this.loadProjects?.();
        if (this.canAccessTab('tab-users')) this.loadUsers?.();
        if (this.hasPermission('VIEW_INCIDENTS')) {
            this.setupOperationsWebSocket();
        }
        if (this.currentUserRole === 'admin') this.setupWebSocketListener();
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
        (window.sensorTypes?.() || ['gnss', 'rain', 'water', 'imu']).forEach(type => {
            const cb = document.getElementById(`edit-${type}`);
            if (cb) {
                cb.addEventListener('change', (e) => {
                    const section = document.getElementById(`mqtt-${type}-section`);
                    if (section) section.style.display = e.target.checked ? 'block' : 'none';

                    if (type === 'gnss' && e.target.checked) {
                        this.loadAICasterUsers();
                    }

                    const anyChecked = (window.sensorTypes?.() || ['gnss', 'rain', 'water', 'imu']).some(t =>
                        document.getElementById(`edit-${t}`)?.checked
                    );
                    const emptyState = document.getElementById('mqtt-empty-state');
                    if (emptyState) emptyState.style.display = anyChecked ? 'none' : 'block';
                });
            }
        });

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

        // Resolve authz before any private manager starts a loader/socket.
        this.bootstrapRoleFirst();

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
            const res = await window.authManager?.apiFetch?.('/api/auth/me', { cache: 'no-store' }) || await fetch('/api/auth/me', {
                headers: { 'Authorization': `Bearer ${this.token}` },
                cache: 'no-store',
            });
            if (!res?.ok) return null;
            const user = await res.json();
            this.currentUser = user;
            this.currentUserRole = user.role;
            this.currentUserAssignedProjects = user.assigned_projects || [];
            this.currentUserPermissions = user.permissions || [];

            console.log(`[ADMIN] User role: ${user.role}, assigned projects: ${JSON.stringify(this.currentUserAssignedProjects)}`);

            this.applyPermissionVisibility();
            return user;
        } catch (e) {
            console.error('Error fetching user role:', e);
            return null;
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
                if (['tab-users', 'tab-database', 'tab-rescue'].includes(tab)) {
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
        if (!silent) body.innerHTML = '<div class="ops-loading"><span class="spinner-border spinner-border-sm"></span><span>Đang tải queue cứu hộ…</span></div>';
        try {
            const state = this.rescueState;
            const query = new URLSearchParams({ offset: String(state.offset), limit: String(state.limit), sort: state.sort });
            if (state.status !== 'all') query.set('status', state.status);
            if (state.q) query.set('q', state.q);
            const res = await fetch(`/api/admin/rescue-requests?${query}`, {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const rows = await res.json();
            state.rows = rows || [];
            state.total = Number(res.headers.get('X-Total-Count') || state.rows.length);
            this.renderRescueRequests(rows || []);
            this.renderRescuePagination();
            this.fetchRescueCounts();
        } catch (e) {
            if (!silent) window.toast?.error('Không tải được danh sách rescue requests');
            body.innerHTML = `<div class="ops-empty is-error"><i class="bi bi-exclamation-circle"></i><strong>Không tải được queue</strong><p>${this.escapeHtml?.(e.message) || e.message}</p><button class="btn btn-outline-primary" onclick="window.adminManager.loadRescueRequests()">Thử lại</button></div>`;
            console.error('loadRescueRequests error:', e);
        }
    }

    renderRescueRequests(rows) {
        const body = document.getElementById('rescue-requests-body');
        if (!body) return;

        if (!Array.isArray(rows) || rows.length === 0) {
            body.innerHTML = '<div class="ops-empty"><i class="bi bi-shield-check"></i><strong>Queue đang trống</strong><p>Không có yêu cầu phù hợp với bộ lọc hiện tại.</p></div>';
            return;
        }

        const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (m) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[m]));

        body.innerHTML = rows.map(r => {
            const ts = r.created_at ? new Date(r.created_at * 1000).toLocaleString('vi-VN') : '--';
            const rescueTypeLabelMap = {
                can_cuu_ho: 'Cần cứu hộ',
                can_nhu_yeu_pham: 'Cần nhu yếu phẩm',
                can_cuu_ho_xe: 'Cần cứu hộ xe',
                khac: 'Khác'
            };
            const rescueType = String(r.rescue_type || '').toLowerCase();
            const rescueTypeLabel = rescueTypeLabelMap[rescueType] || '--';
            const provinceCity = String(r.province_city || '').trim() || '--';
            const urgency = this.getRescueUrgency(r);
            return `<article class="rescue-case ${urgency.className}" tabindex="0" onclick="window.adminManager.openRescueInspector(${r.id})" onkeydown="if(event.key==='Enter') window.adminManager.openRescueInspector(${r.id})">
                <div class="rescue-case-priority"><span>${esc(urgency.label)}</span><small>${esc(this.formatRescueAge(r.created_at))}</small></div>
                <div class="rescue-case-main"><div class="rescue-case-title"><strong>${esc(rescueTypeLabel)}</strong><span>#${r.id}</span></div><p>${esc(r.message || 'Không có mô tả')}</p><div class="rescue-case-meta"><span><i class="bi bi-person"></i>${esc(r.requester_name || 'Ẩn danh')}</span><span><i class="bi bi-telephone"></i>${esc(r.phone || 'Không có SĐT')}</span><span><i class="bi bi-geo-alt"></i>${esc(provinceCity)}</span></div></div>
                <div class="rescue-case-end"><time>${esc(ts)}</time><span class="management-status ${r.status === 'resolved' ? 'is-success' : r.status === 'rejected' ? 'is-secondary' : 'is-warning'}">${r.status === 'resolved' ? 'Đã xử lý' : r.status === 'rejected' ? 'Từ chối' : 'Đang chờ'}</span><button class="management-icon-btn btn btn-outline-secondary" aria-label="Mở case #${r.id}"><i class="bi bi-chevron-right"></i></button></div>
            </article>`;
        }).join('');
    }

    getRescueUrgency(row) {
        if (row.status !== 'pending') return { label: 'Đã đóng', className: 'is-closed' };
        const ageSeconds = Math.max(0, Date.now() / 1000 - Number(row.created_at || 0));
        const urgentType = ['can_cuu_ho', 'can_cuu_ho_xe'].includes(String(row.rescue_type || '').toLowerCase());
        if (urgentType && ageSeconds >= 1800) return { label: 'Khẩn cấp', className: 'is-critical' };
        if (urgentType || ageSeconds >= 3600) return { label: 'Ưu tiên cao', className: 'is-high' };
        if (String(row.rescue_type || '').toLowerCase() === 'can_nhu_yeu_pham') return { label: 'Ưu tiên vừa', className: 'is-medium' };
        return { label: 'Thông thường', className: 'is-normal' };
    }

    formatRescueAge(timestamp) {
        const minutes = Math.max(0, Math.floor((Date.now() / 1000 - Number(timestamp || 0)) / 60));
        if (minutes < 1) return 'Vừa gửi';
        if (minutes < 60) return `Chờ ${minutes} phút`;
        const hours = Math.floor(minutes / 60);
        return hours < 24 ? `Chờ ${hours} giờ` : `Chờ ${Math.floor(hours / 24)} ngày`;
    }

    async fetchRescueCounts() {
        try {
            const statuses = ['pending', 'resolved', 'rejected'];
            const counts = await Promise.all(statuses.map(async status => {
                const res = await fetch(`/api/admin/rescue-requests?status=${status}&limit=1`, { headers: { 'Authorization': `Bearer ${this.token}` } });
                return Number(res.headers.get('X-Total-Count') || 0);
            }));
            const values = { pending: counts[0], resolved: counts[1], rejected: counts[2] };
            values.total = counts.reduce((sum, value) => sum + value, 0);
            Object.entries(values).forEach(([key, value]) => { const el = document.getElementById(`rescue-count-${key}`); if (el) el.textContent = value.toLocaleString('vi-VN'); });
        } catch (error) {
            console.warn('fetchRescueCounts error:', error);
        }
    }

    setRescueStatus(status, button) {
        this.rescueState.status = status;
        this.rescueState.offset = 0;
        document.querySelectorAll('.rescue-status-tabs button').forEach(el => el.classList.toggle('active', el === button));
        this.loadRescueRequests();
    }

    scheduleRescueSearch() {
        clearTimeout(this.rescueSearchTimer);
        this.rescueSearchTimer = setTimeout(() => {
            this.rescueState.q = document.getElementById('rescue-search')?.value.trim() || '';
            this.rescueState.offset = 0;
            this.loadRescueRequests();
        }, 250);
    }

    changeRescueSort(value) {
        this.rescueState.sort = value === 'newest' ? '-created_at' : 'created_at';
        this.rescueState.offset = 0;
        this.loadRescueRequests();
    }

    changeRescuePage(direction) {
        const next = this.rescueState.offset + direction * this.rescueState.limit;
        if (next < 0 || next >= this.rescueState.total) return;
        this.rescueState.offset = next;
        this.loadRescueRequests();
    }

    renderRescuePagination() {
        const state = this.rescueState;
        const start = state.total ? state.offset + 1 : 0;
        const end = Math.min(state.offset + state.rows.length, state.total);
        document.getElementById('rescue-page-summary').textContent = `Hiển thị ${start}–${end} / ${state.total}`;
        document.getElementById('rescue-page-number').textContent = `Trang ${Math.floor(state.offset / state.limit) + 1}`;
        document.getElementById('rescue-page-prev').disabled = state.offset === 0;
        document.getElementById('rescue-page-next').disabled = state.offset + state.limit >= state.total;
    }

    openRescueInspector(id) {
        const row = this.rescueState.rows.find(item => Number(item.id) === Number(id));
        if (!row) return;
        this.selectedRescueRequest = row;
        const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
        const imageUrl = /^\/api\/admin\/rescue-images\/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(String(row.image_url || '')) ? row.image_url : '';
        const mapUrl = `https://maps.google.com/?q=${encodeURIComponent(`${row.latitude},${row.longitude}`)}`;
        const urgency = this.getRescueUrgency(row);
        document.getElementById('rescue-inspector-title').textContent = `Yêu cầu #${row.id}`;
        document.getElementById('rescue-inspector-content').innerHTML = `<section class="drawer-summary"><span class="rescue-priority ${urgency.className}">${esc(urgency.label)}</span><h6>${esc(row.requester_name || 'Người gửi ẩn danh')}</h6><p>${esc(row.phone || 'Không có số điện thoại')} · ${esc(this.formatRescueAge(row.created_at))}</p></section>${imageUrl ? `<img class="rescue-evidence" data-auth-src="${esc(imageUrl)}" alt="Ảnh hiện trường của yêu cầu #${row.id}">` : ''}<dl class="drawer-facts"><div><dt>Loại yêu cầu</dt><dd>${esc(row.rescue_type || '--')}</dd></div><div><dt>Khu vực</dt><dd>${esc(row.province_city || '--')}</dd></div><div><dt>Tọa độ</dt><dd><a href="${mapUrl}" target="_blank" rel="noopener">${Number(row.latitude).toFixed(6)}, ${Number(row.longitude).toFixed(6)}</a></dd></div><div><dt>Độ chính xác GPS</dt><dd>${row.accuracy_m ? `±${Number(row.accuracy_m).toFixed(1)} m` : '--'}</dd></div></dl><section class="drawer-message"><span>Mô tả</span><p>${esc(row.message || '--')}</p></section><label class="form-label" for="rescue-admin-note">Ghi chú xử lý</label><textarea class="form-control" id="rescue-admin-note" rows="4" maxlength="500" placeholder="Ghi lại kết quả liên hệ hoặc lý do xử lý…">${esc(row.admin_note || '')}</textarea>`;
        document.getElementById('rescue-inspector-actions').innerHTML = row.status === 'pending' ? `<button class="btn btn-outline-secondary" onclick="window.adminManager.updateRescueRequestStatus(${row.id}, 'rejected')">Từ chối</button><button class="btn btn-success" onclick="window.adminManager.updateRescueRequestStatus(${row.id}, 'resolved')"><i class="bi bi-check2-circle me-1"></i>Đánh dấu đã xử lý</button>` : `<button class="btn btn-outline-danger" onclick="window.adminManager.deleteRescueRequest(${row.id})"><i class="bi bi-trash3 me-1"></i>Xóa case</button>`;
        document.getElementById('rescue-inspector').classList.add('open');
        document.getElementById('rescue-inspector').setAttribute('aria-hidden', 'false');
        document.getElementById('rescue-inspector-backdrop').classList.add('show');
        document.querySelector('#rescue-inspector > header button')?.focus();
        void window.hydrateAuthenticatedImages?.(document.getElementById('rescue-inspector-content'));
    }

    closeRescueInspector() {
        document.getElementById('rescue-inspector')?.classList.remove('open');
        document.getElementById('rescue-inspector')?.setAttribute('aria-hidden', 'true');
        document.getElementById('rescue-inspector-backdrop')?.classList.remove('show');
    }

    async updateRescueRequestStatus(requestId, status) {
        if (status === 'rejected' && !window.confirm(`Từ chối yêu cầu cứu hộ #${requestId}?`)) return;
        try {
            const res = await fetch(`/api/admin/rescue-requests/${requestId}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${this.token}`
                },
                body: JSON.stringify({ status, admin_note: document.getElementById('rescue-admin-note')?.value.trim() || null })
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            window.toast?.success(`Rescue request #${requestId} -> ${status}`);
            this.closeRescueInspector();
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
            this.closeRescueInspector();
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
