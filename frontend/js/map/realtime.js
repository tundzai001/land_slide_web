// =====================================================
// WEBSOCKET REALTIME CONNECTION
// =====================================================

let rescueAdminSocket = null;
let rescueAdminReconnectId = null;
let rescueAdminReconnectAttempt = 0;
let rescueAdminTicketPromise = null;
let wsTicketPending = null;
let wsSetupGeneration = 0;
let rescueSetupGeneration = 0;

function rescueAdminSocketAllowed() {
    return document.visibilityState !== 'hidden' && isMapViewActive() && window.authManager?.isAuthenticated?.() && window.authManager.getUserInfo?.()?.role === 'admin';
}
async function requestRescueAdminTicket() {
    if (rescueAdminTicketPromise) return rescueAdminTicketPromise;
    rescueAdminTicketPromise = (async () => {
        const response = await window.authManager.apiFetch('/api/auth/ws-ticket', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ channel: 'legacy_admin' }), cache: 'no-store',
        });
        if (!response?.ok) throw new Error(`Admin ticket HTTP ${response?.status || 0}`);
        return (await response.json()).ticket;
    })().finally(() => { rescueAdminTicketPromise = null; });
    return rescueAdminTicketPromise;
}
function scheduleRescueAdminReconnect() {
    if (rescueAdminReconnectId || !rescueAdminSocketAllowed()) return;
    const delay = Math.min(30000, 1000 * (2 ** Math.min(rescueAdminReconnectAttempt, 5)));
    rescueAdminReconnectAttempt += 1;
    rescueAdminReconnectId = setTimeout(() => { rescueAdminReconnectId = null; void setupRescueAdminSocket(); }, delay);
}
async function setupRescueAdminSocket() {
    if (!rescueAdminSocketAllowed() || rescueAdminSocket) return;
    const generation = rescueSetupGeneration;
    try {
        const ticket = await requestRescueAdminTicket();
        if (generation !== rescueSetupGeneration || !rescueAdminSocketAllowed() || !ticket || rescueAdminSocket) return;
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const socket = new WebSocket(`${protocol}//${window.location.host}/ws/admin?ticket=${encodeURIComponent(ticket)}`);
        rescueAdminSocket = socket;
        socket.onopen = () => { if (rescueAdminSocket === socket) { rescueAdminReconnectAttempt = 0; document.documentElement.dataset.rescueRealtime = 'connected'; } };
        socket.onmessage = event => {
            if (rescueAdminSocket !== socket) return;
            try { const message = JSON.parse(event.data); if (message.type === 'rescue_request') updateRescueMarkerFromWebSocket(message); } catch (_) { /* keep the private channel fail-soft */ }
        };
        socket.onerror = () => { if (rescueAdminSocket === socket) document.documentElement.dataset.rescueRealtime = 'degraded'; };
        socket.onclose = async event => {
            if (rescueAdminSocket !== socket) return;
            rescueAdminSocket = null;
            document.documentElement.dataset.rescueRealtime = 'disconnected';
            if (event.code === 1008) await window.authManager?.verifyToken?.();
            scheduleRescueAdminReconnect();
        };
    } catch (_) {
        if (generation === rescueSetupGeneration) {
            document.documentElement.dataset.rescueRealtime = 'degraded';
            scheduleRescueAdminReconnect();
        }
    }
}
function stopRescueAdminSocket() {
    rescueSetupGeneration += 1;
    if (rescueAdminReconnectId) clearTimeout(rescueAdminReconnectId);
    rescueAdminReconnectId = null; rescueAdminReconnectAttempt = 0;
    const socket = rescueAdminSocket; rescueAdminSocket = null;
    if (socket) { socket.onclose = null; socket.close(); }
    document.documentElement.dataset.rescueRealtime = 'disconnected';
}

function finiteMetric(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}

async function setupWebSocket() {
    if (!isMapViewActive()) return;
    void setupRescueAdminSocket();
    if (wsConnection && [WebSocket.OPEN, WebSocket.CONNECTING].includes(wsConnection.readyState)) {
        return;
    }
    if (wsReconnectId) {
        clearTimeout(wsReconnectId);
        wsReconnectId = null;
    }
    if (!window.authManager?.isAuthenticated?.() || wsTicketPending) return;
    const attempt = { generation: wsSetupGeneration };
    wsTicketPending = attempt;
    try {
        const response = await window.authManager.apiFetch('/api/auth/ws-ticket', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel: 'updates' }), cache: 'no-store',
        });
        if (!response?.ok) throw new Error('Realtime ticket unavailable');
        const ticket = (await response.json()).ticket;
        if (attempt.generation !== wsSetupGeneration || !isMapViewActive() || !window.authManager?.isAuthenticated?.()) return;
        if (!ticket) throw new Error('Realtime ticket unavailable');
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/updates?ticket=${encodeURIComponent(ticket)}`;
        const socket = new WebSocket(wsUrl);
        wsConnection = socket;

    socket.onopen = () => {
        if (wsConnection !== socket) return;
        console.log('✅ [WS] Connected');
        document.documentElement.dataset.realtime = 'connected';
        wsReconnectAttempt = 0;
        syncWebSocketSubscription();
        gnssAdjustmentDebugState.wsStatus = 'CONNECTED';
        if (gnssAdjustmentDebugState.active) {
            addGnssAdjustmentDebug('WS', 'WebSocket đã kết nối.', 'success');
            void syncGnssAdjustmentStatus();
        }
        else refreshGnssAdjustmentDebugUi();
        if (wsHeartbeatId) clearInterval(wsHeartbeatId);
        wsHeartbeatId = setInterval(() => {
            if (wsConnection === socket && socket.readyState === WebSocket.OPEN) {
                try {
                    socket.send('ping');
                } catch (error) {
                    console.warn('[WS] Keepalive send failed:', error);
                }
            }
        }, 20000);
    };

    socket.onmessage = (event) => {
        if (wsConnection !== socket) return;
        try {
            const message = JSON.parse(event.data);
            if (message.type === 'pong') return;
            handleRealtimeUpdate(message);
        } catch (e) {
            console.error('❌ [WS] Parse error:', e);
        }
    };

    socket.onerror = (error) => {
        if (wsConnection !== socket) return;
        console.error('❌ [WS] Error:', error);
        // WebSocket is only the realtime display channel. The adjustment runs
        // server-side and the authoritative state continues via REST polling.
        gnssAdjustmentDebugState.wsStatus = 'RECONNECTING';
        refreshGnssAdjustmentDebugUi();
    };

    socket.onclose = async event => {
        if (wsConnection !== socket) return;
        console.warn('⚠️ [WS] Disconnected; scheduling reconnect...');
        document.documentElement.dataset.realtime = 'disconnected';
        wsConnection = null;
        if (wsHeartbeatId) clearInterval(wsHeartbeatId);
        wsHeartbeatId = null;
        gnssAdjustmentDebugState.wsStatus = 'DISCONNECTED';
        if (gnssAdjustmentDebugState.active) {
            addGnssAdjustmentDebug('WS', 'WebSocket bị ngắt; đang tự kết nối lại và vẫn theo dõi tiến trình qua API.', 'warning');
            void syncGnssAdjustmentStatus();
        }
        else refreshGnssAdjustmentDebugUi();
        if (event.code === 1008) await window.authManager?.verifyToken?.();
        if (attempt.generation !== wsSetupGeneration || !isMapViewActive() || !window.authManager?.isAuthenticated?.()) return;
        const baseDelay = Math.min(30000, 1000 * (2 ** Math.min(wsReconnectAttempt, 5)));
        const randomFactor = (window.crypto?.getRandomValues ? window.crypto.getRandomValues(new Uint32Array(1))[0] / 4294967296 : 0.5) * 0.5;
        const reconnectDelay = Math.round(baseDelay * (0.75 + randomFactor));
        wsReconnectAttempt += 1;
        wsReconnectId = setTimeout(() => {
            wsReconnectId = null;
            void setupWebSocket();
        }, reconnectDelay);
    };
    } catch (error) {
        if (attempt.generation === wsSetupGeneration && isMapViewActive() && window.authManager?.isAuthenticated?.()) {
            wsConnection = null;
            const delay = Math.min(30000, 1000 * (2 ** Math.min(wsReconnectAttempt++, 5)));
            wsReconnectId = setTimeout(() => { wsReconnectId = null; void setupWebSocket(); }, delay);
        }
    } finally {
        if (wsTicketPending === attempt) wsTicketPending = null;
    }
}

function syncWebSocketSubscription(stationId = currentStationData?.id) {
    if (!wsConnection || wsConnection.readyState !== WebSocket.OPEN) return;
    const normalizedStationId = Number(stationId || 0);
    try {
        wsConnection.send(JSON.stringify({
            type: 'subscribe',
            station_ids: normalizedStationId > 0 ? [normalizedStationId] : [],
            project_ids: [],
            channels: ['sensor', 'status', 'alerts', 'adjustment', 'rescue'],
        }));
    } catch (error) {
        console.warn('[WS] Subscription update failed:', error);
    }
}

window.addEventListener('online', () => {
    if (!isMapViewActive()) return;
    if (!wsConnection || wsConnection.readyState === WebSocket.CLOSED) void setupWebSocket();
    if (!rescueAdminSocket || rescueAdminSocket.readyState === WebSocket.CLOSED) void setupRescueAdminSocket();
});
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') {
        stopRescueAdminSocket();
        return;
    }
    if (document.visibilityState === 'visible' && isMapViewActive()) {
        if (!wsConnection || wsConnection.readyState === WebSocket.CLOSED) {
            void setupWebSocket();
        }
        void setupRescueAdminSocket();
        void loadStations();
        void loadCorsBaseStations();
        void loadRescueMarkers();
    }
});
window.addEventListener('auth:ready', () => {
    if (isMapViewActive()) {
        void setupWebSocket();
        void setupRescueAdminSocket();
    }
});
window.addEventListener('authzExpired', () => {
    wsSetupGeneration += 1;
    wsTicketPending = null;
    stopRescueAdminSocket();
    if (wsReconnectId) clearTimeout(wsReconnectId);
    wsReconnectId = null;
    if (wsHeartbeatId) clearInterval(wsHeartbeatId);
    wsHeartbeatId = null;
    if (wsConnection) { const socket = wsConnection; wsConnection = null; socket.onclose = null; socket.close(); }
});
window.addEventListener('spa:navigate', (event) => {
    if (event.detail?.view !== 'map') {
        wsSetupGeneration += 1;
        wsTicketPending = null;
        stopMapBackgroundWork();
    }
});

function handleRealtimeUpdate(message) {
    //console.log('📡 [WS] Received:', message);

    if (message.type === 'hello') {
        syncWebSocketSubscription();
        return;
    }
    if (message.type === 'subscription_ack') return;

    if (message.type === 'sensor_data') {
        if (currentStationData && message.station_id === currentStationData.id) {
            scheduleRealtimeSensorUiUpdate(message);
        }
    }

    if (message.type === 'sensor_status') {
        if (
            currentStationData
            && message.station_id === currentStationData.id
            && message.sensor_type === 'gnss_adjusted'
        ) {
            scheduleRealtimeSensorUiUpdate(message);
            if (gnssAdjustmentDebugState.active) {
                addGnssAdjustmentDebug('RESULT', 'Đã nhận kết quả bình sai từ server.', 'success');
            }
        }
        if (currentStationData && message.station_id === currentStationData.id && message.sensor_type === 'gnss') {
            const fixMode = message.data?.fix_mode;
            const fixQuality = Number(message.data?.fix_quality);
            if (
                gnssAdjustmentDebugState.active
                && gnssAdjustmentDebugState.expectedStationIds.includes(Number(message.station_id))
            ) {
                const now = Date.now();
                const lastAt = Number(gnssAdjustmentDebugState.lastGnssStatusAtByStation[message.station_id] || 0);
                if (now - lastAt >= 5000) {
                    gnssAdjustmentDebugState.lastGnssStatusAtByStation[message.station_id] = now;
                    addGnssAdjustmentDebug(
                        'GNSS',
                        `Trạm #${message.station_id} có GGA: ${fixMode || 'UNKNOWN'} (quality=${fixQuality || 0}). Đang chờ #AGRICA.`,
                        fixQuality >= 4 ? 'info' : 'warning',
                    );
                }
            }
            updateGnssFixBadge(fixMode, fixQuality);

            const normalizedMode = (fixMode || '').toString().trim().toUpperCase();
            const isNoData = (
                !normalizedMode ||
                normalizedMode === 'UNKNOWN' ||
                normalizedMode === 'INVALID' ||
                normalizedMode === 'NO_DATA' ||
                normalizedMode === 'GNSS_UNKNOWN' ||
                normalizedMode === 'GNSS_INVALID' ||
                fixQuality <= 0
            );

            // Chỉ reset velocity khi trạng thái GNSS thực sự không có dữ liệu.
            if (isNoData) {
                setHTML('val-gnss-vel', `--<span class="sensor-unit">mm/s</span>`);
            }
        }
    }

    if (message.type === 'station_status') {
        const riskLevel = String(message.risk_level || 'LOW').toUpperCase();
        const riskUi = getRiskPresentation(riskLevel);
        const stationId = message.station_id;

        // ✅ Nếu trạm về AN TOÀN → Reset tất cả UI state liên quan + dừng âm thanh
        if (riskUi.normalized === 'LOW' || riskUi.normalized === 'OFFLINE') {
            // 1. Clear marker flashing (phải gọi TRƯỚC updateStationMarker)
            if (markerAlertState[stationId]) {
                clearMarkerAlert(stationId);
            }

            // 2. Dismiss alert banner nếu đang hiện cho trạm này
            if (currentAlertStationId === stationId) {
                const banner = document.getElementById('alert-banner');
                if (banner) {
                    banner.classList.remove('show');
                    banner.classList.remove('level-warning', 'level-critical');
                }
                currentAlertStationId = null;
                lastAlertKey = null; // Reset dedup để alert mới có thể hiện lại
            }
            delete alertBannerSnoozeUntil[stationId];
            delete acknowledgedAlertKeyByStation[stationId];
            delete bannerSuppressedUntilByStation[stationId];
            // Clear tất cả sensor card highlight khi trạm về safe
            clearAllSensorCardAlerts();

            // 3. Reset siren buttons to idle if viewing this station
            if (currentStationData && stationId === currentStationData.id) {
                setSirenButtonState('idle');
            }

            // 4. ✅ Xóa cảnh báo âm thanh cho trạm này → âm thanh dừng nếu không còn trạm nào báo
            AlertSoundManager.clearStationAlert(stationId);
        }

        const isAlertingRisk = (riskUi.normalized === 'MEDIUM' || riskUi.normalized === 'CRITICAL');
        if (isAlertingRisk) {
            // ✅ Cập nhật âm thanh theo mức cảnh báo của trạm
            const soundLevel = (riskUi.normalized === 'CRITICAL' ? 'CRITICAL' : 'WARNING');
            AlertSoundManager.setStationAlert(stationId, soundLevel);

            const banner = document.getElementById('alert-banner');
            const isVisible = !!banner?.classList.contains('show');
            const snoozeUntil = Number(alertBannerSnoozeUntil[stationId] || 0);

            if (Date.now() >= snoozeUntil) {
                const incomingLevel = soundLevel;
                const incomingSeverity = getAlertSeverity(incomingLevel);
                const currentSeverity = getAlertSeverity(banner?.dataset?.alertLevel || 'WARNING');
                const sameStation = currentAlertStationId === stationId;
                const shouldShowOrReplace = !isVisible || sameStation || incomingSeverity > currentSeverity;

                if (shouldShowOrReplace) {
                    const cachedAlert = latestAlertByStation[stationId];
                    const candidateAlert = cachedAlert ? {
                        ...cachedAlert,
                        level: incomingLevel
                    } : {
                        station_id: stationId,
                        level: incomingLevel,
                        message: message.message || message.warning_message || getDefaultAlertMessageForStationStatus(riskUi)
                    };
                    const candidateKey = buildAlertKey(candidateAlert);
                    if (candidateKey && acknowledgedAlertKeyByStation[stationId] === candidateKey) {
                        return;
                    }
                    if (isBannerSuppressed(stationId)) {
                        return;
                    }
                    showAlertBanner(candidateAlert, { silent: true });
                }
            }
        }

        if (currentAlertStationId === stationId && (riskUi.normalized === 'MEDIUM' || riskUi.normalized === 'CRITICAL')) {
            const banner = document.getElementById('alert-banner');
            if (banner?.classList.contains('show')) {
                const nextLevel = (riskUi.normalized === 'CRITICAL' ? 'CRITICAL' : 'WARNING');
                // Luôn cập nhật theme theo mức cảnh báo hiện tại (WARNING → vàng, CRITICAL → đỏ)
                updateAlertBannerTheme(nextLevel);
                const alertTitle = document.getElementById('alert-title');
                if (alertTitle && !alertTitle.textContent.includes('(persistent)')) {
                    alertTitle.textContent = `${riskUi.display} ALERT!`;
                }
            }

            // ✅ Cập nhật sensor card highlight theo mức cảnh báo mới
            // Khi CRITICAL → WARNING: chuyển card đang nháy đỏ sang nháy vàng
            // Khi WARNING → CRITICAL: chuyển card đang nháy vàng sang nháy đỏ
            if (currentStationData && stationId === currentStationData.id) {
                const alertLevel = (riskUi.normalized === 'CRITICAL' ? 'CRITICAL' : 'WARNING');
                Object.values(SENSOR_CARD_IDS).forEach(id => {
                    const card = document.getElementById(id);
                    if (card && (card.classList.contains('sensor-alert-warning') || card.classList.contains('sensor-alert-critical'))) {
                        card.classList.remove('sensor-alert-warning', 'sensor-alert-critical');
                        card.classList.add(alertLevel === 'CRITICAL' ? 'sensor-alert-critical' : 'sensor-alert-warning');
                    }
                });
            }
        }

        if (currentStationData && stationId === currentStationData.id && (riskUi.normalized === 'MEDIUM' || riskUi.normalized === 'CRITICAL')) {
            const banner = document.getElementById('alert-banner');
            const isVisible = !!banner?.classList.contains('show');
            const snoozeUntil = Number(alertBannerSnoozeUntil[stationId] || 0);
            if (!isVisible && Date.now() >= snoozeUntil) {
                const cachedAlert = latestAlertByStation[stationId];
                if (cachedAlert) {
                    // Ghi đè level bằng mức rủi ro HIỆN TẠI của trạm
                    // để banner luôn phản ánh đúng màu (WARNING→vàng, CRITICAL→đỏ)
                    const currentLevel = (riskUi.normalized === 'CRITICAL' ? 'CRITICAL' : 'WARNING');
                    const candidateAlert = { ...cachedAlert, level: currentLevel };
                    const candidateKey = buildAlertKey(candidateAlert);
                    if (!candidateKey || acknowledgedAlertKeyByStation[stationId] !== candidateKey) {
                        if (isBannerSuppressed(stationId)) {
                            return;
                        }
                        showAlertBanner(candidateAlert, { silent: true });
                    }
                }
            }
        }

        // ✅ Nếu trạm chuyển sang EXTREME/CRITICAL → Cập nhật siren buttons
        if (riskUi.normalized === 'CRITICAL' && currentStationData && stationId === currentStationData.id) {
            const user = window.authManager?.getUserInfo();
            const userRole = user?.role;
            if (userRole === 'admin' || userRole === 'operator') {
                currentAlertStationId = stationId;
                // Transition idle/offline buttons to alerting
                document.querySelectorAll('.btn-siren-toggle').forEach(b => {
                    const target = b.getAttribute('data-target');
                    const currentState = b.getAttribute('data-siren-state');
                    if (currentState === 'idle' || currentState === 'offline') {
                        setSirenButtonState('alerting', target);
                    }
                });
            }
        }

        // Update marker color on map
        updateStationMarker(stationId, riskUi.normalized);

        // Update status badge in sidebar
        if (currentStationData && stationId === currentStationData.id) {
            const riskEl = document.getElementById('st-risk');
            if (riskEl) {
                riskEl.className = `status-badge ${riskUi.className}`;
                riskEl.innerHTML = `<span class="status-dot"></span> ${riskUi.display}`;
            }
        }

        // Update station list badge
        const listBadge = document.getElementById(`list-badge-${stationId}`);
        if (listBadge) {
            listBadge.className = `badge station-status ${getRiskBadgeClass(riskUi.className)}`;
            listBadge.innerText = getStationListRiskLabel(riskUi.normalized);
            const listItem = listBadge.closest('.station-item');
            if (listItem) {
                listItem.dataset.state = riskUi.normalized.toLowerCase();
                listItem.dataset.connection = riskUi.normalized === 'OFFLINE'
                    ? 'offline'
                    : riskUi.normalized === 'STALE' ? 'stale' : 'online';
            }
            filterStations(document.getElementById('search-station')?.value || '');

            listBadge.style.transition = '0.3s';
            listBadge.style.transform = 'scale(1.2)';
            setTimeout(() => listBadge.style.transform = 'scale(1)', 300);
        }
    }

    // ✅ XỬ LÝ CẢNH BÁO MỚI — Chỉ hiện 1 lần per alert (dedup)
    if (message.type === 'alert') {
        const incomingAlert = normalizeIncomingAlert(message);
        latestAlertByStation[incomingAlert.station_id] = incomingAlert;
        // Dedup theo station + sensor + level để không nuốt cảnh báo mới cùng level từ sensor khác.
        const alertKey = buildAlertKey(incomingAlert);
        const isAcknowledged = acknowledgedAlertKeyByStation[incomingAlert.station_id] === alertKey;
        if (!isAcknowledged) {
            delete bannerSuppressedUntilByStation[incomingAlert.station_id];
        }
        if (alertKey !== lastAlertKey && !isAcknowledged) {
            lastAlertKey = alertKey;
            showAlertBanner(incomingAlert);
        }
        // Highlight sensor card nếu đang xem trạm đang báo
        if (currentStationData && incomingAlert.station_id === currentStationData.id && incomingAlert.sensor_type) {
            setSensorCardAlert(incomingAlert.sensor_type, incomingAlert.level);
        }
        // ✅ Marker chuyển đỏ + nhấp nháy khi có cảnh báo
        setMarkerAlert(incomingAlert.station_id, true);

        // ✅ Phát âm thanh theo cấp độ cảnh báo — loop liên tục cho đến khi về bình thường
        const alertSoundLevel = normalizeAlertLevel(incomingAlert.level) === 'CRITICAL' ? 'CRITICAL' : 'WARNING';
        AlertSoundManager.setStationAlert(incomingAlert.station_id, alertSoundLevel);

        // ✅ Cập nhật siren buttons nếu đang xem trạm này
        // Phân biệt pi_point / pi_center — chỉ set 'alerting' nếu thiết bị online
        if (currentStationData && incomingAlert.station_id === currentStationData.id) {
            const user = window.authManager?.getUserInfo();
            const userRole = user?.role;
            if (userRole === 'admin' || userRole === 'operator') {
                currentAlertStationId = incomingAlert.station_id;
                const piDevices = currentStationData.pi_devices || [];
                document.querySelectorAll('.btn-siren-toggle').forEach(b => {
                    const target = b.getAttribute('data-target');
                    const currentState = b.getAttribute('data-siren-state');
                    if (currentState === 'offline') return; // thiết bị offline, bỏ qua
                    // Kiểm tra pi device tương ứng có online không
                    const piDev = piDevices.find(d => d.device_type === target);
                    if (piDev && !piDev.is_online) {
                        setSirenButtonState('offline', target);
                        return;
                    }
                    if (currentState === 'idle') {
                        setSirenButtonState('alerting', target);
                    }
                });
            }
        }
    }

    // ✅ Handle rescue request updates from WebSocket
    if (message.type === 'rescue_request') {
        updateRescueMarkerFromWebSocket(message);
    }
    
    // ✅ Handle gnss adjustment progress
    if (message.type === 'gnss_adjustment_progress') {
        const belongsToActiveRun = (
            !gnssAdjustmentDebugState.projectId
            || Number(message.project_id) === gnssAdjustmentDebugState.projectId
        );
        if (belongsToActiveRun) {
            applyGnssAdjustmentRoster(message.roster, message.run_id);
            if (Array.isArray(message.expected_station_ids)) {
                syncGnssExpectedStationIds(message.expected_station_ids, message.run_id);
            }
            setGnssAdjustmentPhase(message.phase, message.message || 'Server đã cập nhật phase.');
            const resultPhase = String(message.phase || '').toUpperCase();
            if (message.data && ['COMPLETED', 'FAILED_QUALITY_GATE', 'PARTIAL_FAILED', 'ERROR'].includes(resultPhase)) {
                const resultMessage = {
                    sensor_type: 'gnss_adjusted',
                    timestamp: message.timestamp || message.data.computed_at || Math.floor(Date.now() / 1000),
                    data: message.data,
                };
                if (resultPhase === 'COMPLETED') {
                    updateRealtimeSensorValues(resultMessage);
                } else {
                    renderGnssAdjustmentAuditResult(resultMessage);
                }
                addGnssAdjustmentDebug(
                    'REPORT',
                    resultPhase === 'ERROR'
                        ? 'Đã ghi hồ sơ lỗi JSON; các lịch chạy tiếp theo vẫn được giữ nguyên.'
                        : ['FAILED_QUALITY_GATE', 'PARTIAL_FAILED'].includes(resultPhase)
                        ? 'Hồ sơ audit đã sẵn sàng để tải; tọa độ không được publish.'
                        : 'Đã nhận liên kết tải JSON và XLSX.',
                    'success',
                );
            }
        }
    }

    if (message.type === 'gnss_adjustment_debug') {
        const belongsToActiveRun = (
            gnssAdjustmentDebugState.active
            && Number(message.project_id) === gnssAdjustmentDebugState.projectId
        );
        if (belongsToActiveRun) {
            const station = message.station_id ? `Trạm #${message.station_id}: ` : '';
            addGnssAdjustmentDebug('AGRICA', `${station}${message.message || '-'}`, message.level || 'info');
        }
    }

    // ✅ Handle gnss baseline collected (Draw board)
    if (message.type === 'gnss_baseline_collected') {
        const baseline = Array.isArray(message.baseline_neu)
            ? message.baseline_neu.map(finiteMetric)
            : null;
        if (!baseline || baseline.some(value => value === null)) return;
        const belongsToActiveRun = (
            gnssAdjustmentDebugState.active
            && Number(message.project_id) === gnssAdjustmentDebugState.projectId
        );
        if (belongsToActiveRun) {
            if (!isGnssAdjustmentExpectedStation(message.station_id)) {
                return;
            }
            gnssAdjustmentDebugState.baselineCount += 1;
            syncGnssWorkflowBaseline(message);
            addGnssAdjustmentDebug(
                'BASELINE',
                `${message.rover_name}: dN=${baseline[0].toFixed(4)}, dE=${baseline[1].toFixed(4)}, dH=${baseline[2].toFixed(4)}`,
                'success',
            );
        }
        if (belongsToActiveRun && window.gnssBoardState && window.gnssBoardState.ctx) {
            const fromPoint = String(message.from || 'BASE');
            window.gnssBoardState.addPoint('BASE', 0, 0, true);
            const origin = window.gnssBoardState.points[fromPoint] || window.gnssBoardState.points.BASE;
            const relX = origin.x + baseline[1];
            const relY = origin.y + baseline[0];
            window.gnssBoardState.addPoint(message.rover_name, relX, relY, false, message.station_id);
            window.gnssBoardState.addBaseline(fromPoint, message.rover_name, {
                dn: baseline[0],
                de: baseline[1],
                dh: baseline[2],
                full_data: message.full_data
            });
        }
    }
}

function getAdjustedPointCoordinates(point) {
    if (Array.isArray(point)) return point;
    if (point && typeof point === 'object') {
        return [point.adjusted_n, point.adjusted_e, point.adjusted_u];
    }
    return [];
}

function formatAdjustedCoordinate(value) {
    const coordinate = Number(value);
    return Number.isFinite(coordinate) ? coordinate.toFixed(4) : '--';
}

function isGnssAdjustmentResultRelevant(result, timestamp = null) {
    if (!result || typeof result !== 'object') return false;
    const expectedProjectId = Number(
        gnssAdjustmentDebugState.projectId || currentStationData?.project_id || 0
    );
    const resultProjectId = Number(result.project_id || 0);
    if (expectedProjectId && resultProjectId && expectedProjectId !== resultProjectId) {
        return false;
    }
    if (gnssAdjustmentDebugState.active) {
        // While a new run is collecting/networking, never show an old cached
        // result panel. Project-level terminal events render either an official
        // result or a downloadable audit-only result.
        if (!['COMPLETED', 'FAILED_QUALITY_GATE', 'PARTIAL_FAILED', 'ERROR'].includes(gnssAdjustmentDebugState.phase)) return false;
        const resultTimestamp = Number(timestamp || result.computed_at || result.epoch_ts || 0);
        const runStartedAt = Math.floor(Number(gnssAdjustmentDebugState.startedAt || 0) / 1000);
        if (runStartedAt && (!resultTimestamp || resultTimestamp < runStartedAt - 2)) {
            return false;
        }
    }
    return true;
}

function renderGnssAdjustmentResultPanel(message, { auditOnly = false } = {}) {
    if (!message?.data || !isGnssAdjustmentResultRelevant(message.data, message.timestamp)) return false;
    const failed = String(message.data.status || '').toLowerCase() === 'failed'
        || ['ERROR', 'PARTIAL_FAILED'].includes(gnssAdjustmentDebugState.phase);
    window.gnssBoardState?.loadAdjustmentResult?.(message.data);
    const adjResultsSection = document.getElementById('adj-results-section');
    const adjStatusEl = document.getElementById('adj-process-status');
    const adjTimeEl = document.getElementById('adj-val-time');
    const adjPointsList = document.getElementById('adj-points-list');
    const retryButton = document.getElementById('gnss-retry-adjustment-btn');

    if (adjStatusEl) {
        adjStatusEl.innerHTML = failed
            ? '<span class="text-danger fw-bold"><i class="bi bi-exclamation-octagon-fill me-1"></i>Bình sai lỗi – đã lưu hồ sơ JSON</span>'
            : auditOnly
            ? '<span class="text-warning fw-bold"><i class="bi bi-file-earmark-check-fill me-1"></i>Đã tạo hồ sơ audit – không publish tọa độ</span>'
            : '<span class="text-success fw-bold"><i class="bi bi-check-circle-fill me-1"></i>Bình sai thành công</span>';
    }
    if (adjTimeEl) {
        const timestamp = Number(message.timestamp || message.data.computed_at || Date.now() / 1000);
        adjTimeEl.textContent = new Date(normalizeEpochMs(timestamp)).toLocaleString();
    }
    if (adjResultsSection) adjResultsSection.style.display = 'flex';
    const terminalModal = document.getElementById('gnssTerminalModal');
    terminalModal?.classList.add('gnss-result-visible');
    if (retryButton) retryButton.style.display = failed || auditOnly ? 'inline-flex' : 'none';
    if (failed) {
        // A terminal error no longer needs two large live panes. Collapse Debug
        // once to guarantee that the result actions remain visible and clickable.
        terminalModal?.querySelector('#gnss-data-column')?.classList.add('gnss-debug-collapsed');
    }
    if (adjPointsList) {
        adjPointsList.innerHTML = '';
        if (failed) {
            const errorItem = document.createElement('div');
            errorItem.className = 'alert alert-danger py-2 px-3 mb-0 small';
            errorItem.textContent = message.data.error?.message || 'Quy trình bình sai đã dừng do lỗi.';
            adjPointsList.appendChild(errorItem);
            window.gnssBoardState?.fitToResult?.();
            return true;
        }
        for (const [ptName, ptCoords] of Object.entries(message.data.points || {})) {
            const coordinates = getAdjustedPointCoordinates(ptCoords);
            const item = document.createElement('div');
            item.className = 'list-group-item bg-transparent text-slate-300 py-1 px-0 d-flex justify-content-between align-items-center border-bottom border-secondary';
            item.innerHTML = `
                <span class="fw-semibold text-info font-monospace" style="font-size:0.75rem;">${ptName}</span>
                <span class="text-light font-monospace text-end" style="font-size:0.68rem; line-height:1.2;">
                    X: ${formatAdjustedCoordinate(coordinates[0])}<br>
                    Y: ${formatAdjustedCoordinate(coordinates[1])}<br>
                    Z: ${formatAdjustedCoordinate(coordinates[2])}
                </span>
            `;
            adjPointsList.appendChild(item);
        }
    }
    window.gnssBoardState?.fitToResult?.();
    return true;
}

function renderGnssAdjustmentAuditResult(message) {
    return renderGnssAdjustmentResultPanel(message, { auditOnly: true });
}

function updateRealtimeSensorValues(message) {
    if (message.sensor_type === 'gnss_adjusted' && message.data) {
        if (!isGnssAdjustmentResultRelevant(message.data, message.timestamp)) return;
        pendingGnssAdjustmentResult = message.data;
        const terminalVisible = document.getElementById('gnssTerminalModal')?.classList.contains('show');
        if (terminalVisible) renderGnssAdjustmentResultPanel(message);

        const ind = document.getElementById('gnss-phase-indicator');
        gnssAdjustmentDebugState.phase = 'COMPLETED';
        if (ind) {
            ind.textContent = `Phase: COMPLETED`;
            ind.className = 'ms-4 text-success fw-bold font-monospace';
        }
        return;
    }
    const { sensor_type, data, timestamp, station_id } = message;
    const stationId = station_id || currentStationData?.id;

    if (stationId && sensor_type && timestamp) {
        latestRealtimeSensorTs[`${stationId}_${sensor_type}`] = Number(timestamp);
    }

    if (currentStationData && Number(stationId) === Number(currentStationData.id) && sensor_type && data) {
        currentStationData.sensors ||= {};
        currentStationData.sensors[sensor_type] ||= {};
        currentStationData.sensors[sensor_type].latest = data;
        if (stationSensorCatalog(currentStationData).some(sensor => sensor.key === sensor_type && !sensor.legacy)) {
            currentStationData.sensors[sensor_type].is_online = true;
        }
        currentStationData.sensors[sensor_type].latest_timestamp = Number(timestamp || Date.now() / 1000);
    }

    const isSelectedStation = mapUiState.selectedStation != null
        && Number(stationId) === Number(mapUiState.selectedStation);
    if (!isSelectedStation) {
        if (sensor_type === 'imu' && data) maybeTriggerLocalImuCriticalFallback(stationId, data);
        return;
    }

    const detailVisible = document.getElementById('detail-sidebar')?.classList.contains('active');
    const chartsVisible = document.getElementById('charts-panel')?.classList.contains('active');
    const advancedVisible = document.getElementById('gnss-advanced-sidepanel')?.classList.contains('active');
    if (!detailVisible && !chartsVisible && !advancedVisible) {
        if (sensor_type === 'imu' && data) maybeTriggerLocalImuCriticalFallback(stationId, data);
        return;
    }

    if (stationSensorCatalog(currentStationData).some(sensor => sensor.key === sensor_type && !sensor.legacy)) {
        renderMonitoringSensors(currentStationData);
        const spec = stationSensorCatalog(currentStationData).find(sensor => sensor.key === sensor_type);
        const fields = sensor_type === 'extensometer' ? [...document.querySelectorAll('#extensometer-charts canvas')].map(canvas => canvas.dataset.point) : spec.fields;
        if (chartsVisible && sensor_type === 'accelerometer') renderAccelerometerWaveform(currentStationData.sensors.accelerometer);
        if (chartsVisible) fields.forEach((field, index) => {
            const chart = charts[sensor_type === 'extensometer' ? `chart-extensometer-${index}` : `chart-${sensor_type}-${field}`];
            if (!chart) return;
            chart.data.labels.push(new Date(normalizeEpochMs(data.measured_at || timestamp)).toLocaleTimeString('vi-VN'));
            chart.data.datasets[0].data.push(data.quality === 'invalid' ? null : (sensor_type === 'extensometer' ? data.points?.[field] : data[field]) ?? null);
            if (chart.data.labels.length > 2000) {
                chart.data.labels.shift();
                chart.data.datasets[0].data.shift();
            }
            chart.update('none');
        });
    }
    //console.log(`🔄 [REALTIME] ${sensor_type}:`, data);

    if (sensor_type === 'gnss' && data) {
        updateGnssFixBadge(data.fix_mode, data.fix_quality);
        updateGnssIntegrityStatus(data);

        const velocityMmS = getGnssVelocity(data);

        //console.log('📍 [GNSS] Velocity value:', velocityMmS, 'from data:', data);
        if (velocityMmS !== null) {
            setHTML('val-gnss-vel', `${velocityMmS.toFixed(4)}<span class="sensor-unit">mm/s</span>`);
        }

        // Update Advanced Sidepanel fields if it exists and data is available
        if (data.adv_x !== undefined) {
            if (advancedVisible) {
             // Vị trí hiện tại: VN2000 NEH
             setText('adv-val-lat', safeNumber(data.adv_x, 3));
             setText('adv-val-lon', safeNumber(data.adv_y, 3));
             setText('adv-val-alt', safeNumber(data.adv_h, 3));
             // Biến dạng lũy kế
            setText('adv-val-dx', safeNumber(data.adv_dx, 2));
            setText('adv-val-dy', safeNumber(data.adv_dy, 2));
            setText('adv-val-dh', safeNumber(data.adv_dh, 2));
             // Vận tốc biến dạng (mm/phút)
             setText('adv-val-vdx', formatGnssVelocityValue(data.adv_vdx, data, 2));
             setText('adv-val-vdy', formatGnssVelocityValue(data.adv_vdy, data, 2));
             setText('adv-val-vdh', formatGnssVelocityValue(data.adv_vdh, data, 2));
            }

             // ✅ CACHE: Lưu vào currentStationData để không bị mất khi refresh định kỳ
             if (currentStationData?.sensors?.gnss?.latest) {
                 if (!currentStationData.sensors.gnss.latest.data) {
                     currentStationData.sensors.gnss.latest.data = {};
                 }
                 Object.assign(currentStationData.sensors.gnss.latest.data, {
                     lat: data.lat, lon: data.lon, h: data.h,
                     adv_x: data.adv_x, adv_y: data.adv_y, adv_h: data.adv_h,
                     adv_dx: data.adv_dx, adv_dy: data.adv_dy, adv_dh: data.adv_dh,
                     adv_vdx: data.adv_vdx, adv_vdy: data.adv_vdy, adv_vdh: data.adv_vdh,
                     velocity_method: data.velocity_method,
                     velocity_sample_count: data.velocity_sample_count,
                     velocity_window_duration_s: data.velocity_window_duration_s,
                     velocity_residual_rms_mm: data.velocity_residual_rms_mm,
                     velocity_residual_mad_mm: data.velocity_residual_mad_mm,
                     velocity_uncertainty_mm_s: data.velocity_uncertainty_mm_s,
                     velocity_confidence_95_mm_s: data.velocity_confidence_95_mm_s,
                     velocity_detection_threshold_mm_s: data.velocity_detection_threshold_mm_s,
                     velocity_z_score: data.velocity_z_score,
                     velocity_min_sigma: data.velocity_min_sigma,
                     velocity_significant: data.velocity_significant,
                     velocity_statistically_significant: data.velocity_statistically_significant,
                     velocity_persistent: data.velocity_persistent,
                     velocity_confirmed: data.velocity_confirmed,
                     velocity_confirmation_sample_count: data.velocity_confirmation_sample_count,
                     velocity_confirmation_duration_s: data.velocity_confirmation_duration_s,
                     velocity_confirmation_direction_cosine: data.velocity_confirmation_direction_cosine,
                     velocity_confirmation_accepted_sample: data.velocity_confirmation_accepted_sample,
                     velocity_confirmation_min_gap_s: data.velocity_confirmation_min_gap_s,
                     velocity_confirmation_required_samples: data.velocity_confirmation_required_samples,
                     velocity_confirmation_required_duration_s: data.velocity_confirmation_required_duration_s,
                     velocity_reliable: data.velocity_reliable,
                     vel_e: data.vel_e, vel_n: data.vel_n, vel_u: data.vel_u,
                     raw_vel_e_mm_s: data.raw_vel_e_mm_s,
                     raw_vel_n_mm_s: data.raw_vel_n_mm_s,
                     raw_vel_u_mm_s: data.raw_vel_u_mm_s,
                     raw_speed_2d_mm_s: data.raw_speed_2d_mm_s,
                     speed_2d_mm_s: data.speed_2d_mm_s,
                     total_displacement_mm: data.total_displacement_mm,
                     peak_displacement_mm: data.peak_displacement_mm,
                     displacement_noise_floor_mm: data.displacement_noise_floor_mm,
                     displacement_uncertainty_mm: data.displacement_uncertainty_mm,
                     candidate_step_displacement_mm: data.candidate_step_displacement_mm,
                     displacement_change_threshold_mm: data.displacement_change_threshold_mm,
                     position_change_significant: data.position_change_significant,
                     displacement_sample_count: data.displacement_sample_count,
                     integrity: data.integrity || data.data,
                     displacement_window_duration_s: data.displacement_window_duration_s,
                     num_sats: data.num_sats, hdop: data.hdop
                 });
             }
        }

        // Update Theil-Sen display in both Main Sidebar and Advanced Panel
        clearGnssEvaluationSummary();
        if (data.velocity_method === 'theil_sen_enu') {
            const sampleCount = Number.isFinite(Number(data.velocity_sample_count)) ? Number(data.velocity_sample_count) : '--';
            const durationS = safeNumber(data.velocity_window_duration_s, 1);
            const rms = safeNumber(data.velocity_residual_rms_mm, 2);
            const mad = safeNumber(data.velocity_residual_mad_mm, 2);
            const uncert = safeNumber(data.velocity_uncertainty_mm_s, 4);
            const ci95 = safeNumber(data.velocity_confidence_95_mm_s, 4);

            if (advancedVisible) {
            // Advanced Panel - Theil-Sen section
            setText('adv-val-method', 'Theil-Sen Robust Estimator');
            setText('adv-val-samples', sampleCount);
            setText('adv-val-duration', durationS);
            setText('adv-val-rms', rms);
            setText('adv-val-mad', mad);
            setText('adv-val-uncert', `± ${uncert}`);
            setText('adv-val-ci95', `± ${ci95}`);

            // Advanced Panel - Raw velocity (trước lọc)
            setText('adv-val-raw-ve', safeNumber(data.raw_vel_e_mm_s, 4));
            setText('adv-val-raw-vn', safeNumber(data.raw_vel_n_mm_s, 4));
            setText('adv-val-raw-vu', safeNumber(data.raw_vel_u_mm_s, 4));
            setText('adv-val-raw-2d', safeNumber(data.raw_speed_2d_mm_s, 4));

            // Advanced Panel - Filtered velocity (sau Theil-Sen)
            setText('adv-val-filt-ve', formatGnssVelocityValue(data.vel_e, data, 4));
            setText('adv-val-filt-vn', formatGnssVelocityValue(data.vel_n, data, 4));
            setText('adv-val-filt-vu', formatGnssVelocityValue(data.vel_u, data, 4));
            setText('adv-val-filt-2d', formatGnssVelocityValue(data.speed_2d_mm_s, data, 4));

            // Advanced Panel - Displacement
            setText('adv-val-disp-total', safeNumber(data.total_displacement_mm, 2));
            setText('adv-val-disp-peak', safeNumber(data.peak_displacement_mm, 2));
            setText('adv-val-disp-noise', safeNumber(data.displacement_noise_floor_mm, 3));
            setText('adv-val-disp-uncert', safeNumber(data.displacement_uncertainty_mm, 3));
            setText('adv-val-disp-window', Number.isFinite(Number(data.displacement_sample_count)) ? Number(data.displacement_sample_count) : '--');
            setText('adv-val-disp-dur', safeNumber(data.displacement_window_duration_s, 1));

            // Advanced Panel - GNSS quality
            setText('adv-val-sats', Number.isFinite(Number(data.num_sats)) ? Number(data.num_sats) : '--');
            setText('adv-val-hdop', safeNumber(data.hdop, 1));

            // Advanced Panel - Timestamps
            if (data.gga_utc) {
                const utcStr = data.gga_utc.toString();
                if (utcStr.length >= 6) {
                    setText('adv-val-ts-gga', `${utcStr.substring(0,2)}:${utcStr.substring(2,4)}:${utcStr.substring(4,6)} UTC`);
                } else {
                    setText('adv-val-ts-gga', data.gga_utc);
                }
            } else {
                setText('adv-val-ts-gga', '--');
            }
            if (data.timestamp) {
                const recvDate = new Date(normalizeEpochMs(data.timestamp));
                setText('adv-val-ts-recv', recvDate.toLocaleTimeString('vi-VN', { hour12: false }) + '.' + recvDate.getMilliseconds());
            } else {
                setText('adv-val-ts-recv', '--');
            }
            const now = new Date();
            setText('adv-val-ts-calc', now.toLocaleTimeString('vi-VN', { hour12: false }) + '.' + now.getMilliseconds());
            }

            // Main sidebar eval summary — use backend flag, no UI-side filtering
            const evalSummaryEl = document.getElementById('gnss-eval-summary');
            if (evalSummaryEl) {
                evalSummaryEl.style.display = 'block';
                const integrity = data.integrity || data.data;
                const integrityState = String(integrity?.integrity_state || '').toUpperCase();
                if (['REFERENCE_TRANSITION', 'UNVERIFIED_POSITION_SHIFT', 'UNTRUSTED_GEOMETRY'].includes(integrityState)) {
                    const shift2d = Number.isFinite(Number(integrity.shift_2d_m))
                        ? `Δ2D ${Number(integrity.shift_2d_m).toFixed(3)} m` : '';
                    const label = integrityState === 'REFERENCE_TRANSITION'
                        ? `Đang kiểm tra reference ${integrity.candidate_count || 0}/${integrity.candidate_target || 6}`
                        : integrityState === 'UNTRUSTED_GEOMETRY'
                            ? 'RTK FIXED nhưng geometry không đạt ngưỡng monitoring'
                            : `Shift chưa xác minh${shift2d ? ` · ${shift2d}` : ''}`;
                    evalSummaryEl.innerHTML = `<span class="gnss-eval-warning fw-bold"><i class="bi bi-exclamation-triangle-fill me-1"></i>${label}</span>`;
                    return;
                }
                let trendHtml = '';
                const hasConfirmationField = Object.prototype.hasOwnProperty.call(data, 'velocity_confirmed');
                const movementConfirmed = hasConfirmationField
                    ? data.velocity_confirmed === true
                    : data.velocity_significant === true;
                const statisticalSignal = data.velocity_statistically_significant === true
                    || (!hasConfirmationField && data.velocity_significant === true);
                const persistentVelocity = data.velocity_persistent === true;
                if (movementConfirmed && data.velocity_reliable !== false) {
                    trendHtml = `<span class="gnss-eval-warning fw-bold"><i class="bi bi-arrow-right-circle-fill me-1"></i>Đủ bằng chứng chuyển dịch</span>`;
                } else if (data.velocity_reliable === false) {
                    trendHtml = `<span class="gnss-eval-secondary fw-bold"><i class="bi bi-question-circle-fill me-1"></i>Vận tốc chưa đủ tin cậy để kết luận</span>`;
                } else if (persistentVelocity && data.position_change_significant !== true) {
                    trendHtml = `<span class="gnss-eval-secondary fw-bold"><i class="bi bi-shield-exclamation me-1"></i>Vận tốc kéo dài nhưng chưa đủ bằng chứng vị trí</span>`;
                } else if (hasConfirmationField && statisticalSignal) {
                    const confirmedSamples = Number.isFinite(Number(data.velocity_confirmation_sample_count))
                        ? Number(data.velocity_confirmation_sample_count)
                        : 0;
                    const requiredSamples = Number.isFinite(Number(data.velocity_confirmation_required_samples))
                        ? Number(data.velocity_confirmation_required_samples)
                        : 3;
                    trendHtml = `<span class="gnss-eval-info fw-bold"><i class="bi bi-hourglass-split me-1"></i>Đang xác minh chuyển dịch (${confirmedSamples}/${requiredSamples} cửa sổ)</span>`;
                } else {
                    trendHtml = `<span class="gnss-eval-success fw-bold"><i class="bi bi-info-circle-fill me-1"></i>Chưa vượt ngưỡng xác nhận; có thể là nhiễu GNSS</span>`;
                }
                const velStr = velocityMmS !== null ? velocityMmS.toFixed(2) : '--';
                const ciStr = data.velocity_confidence_95_mm_s ? `± ${Number(data.velocity_confidence_95_mm_s).toFixed(2)}` : '';
                const zScore = Number(data.velocity_z_score);
                const zHtml = Number.isFinite(zScore)
                    ? `<span class="font-monospace">z=${zScore.toFixed(2)}σ / ngưỡng ${Number(data.velocity_min_sigma || 3).toFixed(1)}σ</span>`
                    : '';
                evalSummaryEl.innerHTML = `
                    <div class="d-flex flex-column gap-1">
                        <div>${trendHtml}</div>
                        <div class="gnss-eval-muted fw-normal" style="font-size: 0.75rem;">
                            <i class="bi bi-speedometer2 me-1"></i>Vận tốc 3D (ước lượng cửa sổ): <strong>${velStr} mm/s</strong> ${ciStr ? `<span class="font-monospace">(${ciStr})</span>` : ''} ${zHtml}
                        </div>
                        <div class="gnss-eval-muted fw-normal" style="font-size: 0.75rem;">
                            <i class="bi bi-funnel me-1"></i>Cửa sổ vận tốc: ${sampleCount} mẫu (${durationS}s)
                        </div>
                    </div>
                `;
            }
        }

        if (chartsVisible && charts['chart-gnss']) {
            const chart = charts['chart-gnss'];
            if (velocityMmS !== null) {
                chart.data.labels.push(new Date(normalizeEpochMs(timestamp)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
                chart.data.datasets[0].data.push(velocityMmS);

                if (chart.data.labels.length > 50) {
                    chart.data.labels.shift();
                    chart.data.datasets[0].data.shift();
                }

                chart.update('none');
            }
        }
    }

    if (sensor_type === 'rain' && data) {
        const intensity = finiteMetric(data.intensity_mm_h ?? data.intensity);
        animateValue('val-rain', intensity, 1, 'mm/h');

        if (chartsVisible && charts['chart-rain']) {
            const chart = charts['chart-rain'];
            chart.data.labels.push(new Date(normalizeEpochMs(timestamp)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
            chart.data.datasets[0].data.push(intensity);

            if (chart.data.labels.length > 50) {
                chart.data.labels.shift();
                chart.data.datasets[0].data.shift();
            }

            chart.update('none');
        }
    }

    if (sensor_type === 'water' && data) {
        const level = finiteMetric(data.water_level ?? data.level ?? data.processed_value_meters);
        setHTML('val-water', formatWaterLevelDisplay(data));
        console.log('💧 [WATER] Level value:', level, 'from data:', data);
        if (chartsVisible && charts['chart-water']) {
            const chart = charts['chart-water'];
            chart.data.labels.push(new Date(normalizeEpochMs(timestamp)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
            chart.data.datasets[0].data.push(level);

            if (chart.data.labels.length > 50) {
                chart.data.labels.shift();
                chart.data.datasets[0].data.shift();
            }

            chart.update('none');
        }
    }

    if (sensor_type === 'imu' && data) {
        if (stationId && timestamp) {
            console.debug(`🧭 [IMU][WS] station=${stationId} ts=${timestamp}`, data);
        }
        updateImuOfflineBadge(true);
        animateValue('val-imu-roll', data.raw_roll, 1, '°', true);
        animateValue('val-imu-pitch', data.raw_pitch, 1, '°', true);
        animateValue('val-imu-yaw', data.raw_yaw, 1, '°', true);

        // Delta values (secondary display) — với mũi tên hướng lệch
        setText('val-imu-delta-roll', formatImuDelta(data.roll, 'roll'));
        setText('val-imu-delta-pitch', formatImuDelta(data.pitch, 'pitch'));
        setText('val-imu-delta-yaw', formatImuDelta(data.yaw, 'yaw'));

        // Use backend drift calculation if available, fallback to JS
        if (finiteMetric(data.drift_len_mm) !== null && data.drift_dir !== undefined && data.drift_dir !== null) {
            animateValue('val-imu-drift-len', finiteMetric(data.drift_len_mm) / 10, 1, ' cm', true);
            setText('val-imu-drift-dir', `(${data.drift_dir})`);
        } else {
            updateImuDrift(data.roll, data.pitch);
        }

        // Update battery in real-time
        const batteryContainer = document.getElementById('battery-container');
        const batteryVal = data.battery;
        if (batteryVal !== undefined && batteryVal !== null && parseFloat(batteryVal) > 0) {
            if (batteryContainer) batteryContainer.style.display = '';
            animateValue('val-battery', batteryVal, 2, 'V');
        }

        // Update IMU chart in real-time
        const imuCanvas = document.getElementById('chart-imu');
        if (chartsVisible && !charts['chart-imu'] && imuCanvas) {
            renderImuChart(currentStationData?.sensors?.imu?.history || []);
        }
        if (chartsVisible && charts['chart-imu']) {
            const chart = charts['chart-imu'];
            const ts = Number(timestamp) || Math.floor(Date.now() / 1000);
            const timeLabel = new Date(normalizeEpochMs(ts)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            chart.data.labels.push(timeLabel);
            chart.data.datasets[0].data.push(finiteMetric(data.roll));
            chart.data.datasets[1].data.push(finiteMetric(data.pitch));
            chart.data.datasets[2].data.push(finiteMetric(data.yaw));

            if (chart.data.labels.length > 50) {
                chart.data.labels.shift();
                chart.data.datasets.forEach(ds => ds.data.shift());
            }

            chart.update('none');
        }

        // Fallback phía client: vẫn báo đỏ/banner nếu IMU vượt ngưỡng nhưng backend chưa phát alert.
        maybeTriggerLocalImuCriticalFallback(stationId, data);
    }
}

function updateStationMarker(stationId, riskLevel) {
    const marker = markers[stationId];
    if (!marker) return;

    // ✅ Nếu marker đang trong trạng thái alert (đỏ nhấp nháy), không cập nhật
    if (markerAlertState[stationId]) return;

    const normalized = normalizeRiskLevel(riskLevel);

    const colors = {
        'CRITICAL': '#fa5252',
        'MEDIUM': '#ffd43b',
        'LOW': '#51cf66',
        'OFFLINE': '#6c757d'
    };

    const effectiveLevel = (normalized && colors[normalized]) ? normalized : 'LOW';
    const color = colors[effectiveLevel];
    const shouldPulse = effectiveLevel === 'CRITICAL';
    const pulseClass = shouldPulse ? ' marker-alert-pulse' : '';

    // ✅ Dùng setIcon với HTML string để Leaflet giữ pulse class khi re-render
    const iconHtml = `<div class="marker-circle${pulseClass}" style="
                width: 18px; height: 18px; box-sizing: border-box; background: ${color};
                border-radius: 50%; border: 2px solid white;
                box-shadow: 0 0 8px rgba(0,0,0,0.5);
                transition: background 0.3s ease;
            "></div>`;

    const newIcon = L.divIcon({
        className: 'custom-map-marker',
        html: iconHtml,
        iconSize: [18, 18],
        iconAnchor: [9, 9]
    });
    marker.setIcon(newIcon);
}
