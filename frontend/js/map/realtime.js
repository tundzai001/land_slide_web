// =====================================================
// WEBSOCKET REALTIME CONNECTION
// =====================================================

function setupWebSocket() {
    if (!isMapViewActive()) return;
    if (wsConnection && [WebSocket.OPEN, WebSocket.CONNECTING].includes(wsConnection.readyState)) {
        return;
    }
    if (wsReconnectId) {
        clearTimeout(wsReconnectId);
        wsReconnectId = null;
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/updates`;

    console.log('🔌 [WS] Connecting to:', wsUrl);

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
            syncGnssAdjustmentStatus();
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

    socket.onclose = () => {
        if (wsConnection !== socket) return;
        console.warn('⚠️ [WS] Disconnected; scheduling reconnect...');
        document.documentElement.dataset.realtime = 'disconnected';
        wsConnection = null;
        if (wsHeartbeatId) clearInterval(wsHeartbeatId);
        wsHeartbeatId = null;
        gnssAdjustmentDebugState.wsStatus = 'DISCONNECTED';
        if (gnssAdjustmentDebugState.active) {
            addGnssAdjustmentDebug('WS', 'WebSocket bị ngắt; đang tự kết nối lại và vẫn theo dõi tiến trình qua API.', 'warning');
            syncGnssAdjustmentStatus();
        }
        else refreshGnssAdjustmentDebugUi();
        const baseDelay = Math.min(30000, 1000 * (2 ** Math.min(wsReconnectAttempt, 5)));
        const reconnectDelay = Math.round(baseDelay * (0.75 + Math.random() * 0.5));
        wsReconnectAttempt += 1;
        wsReconnectId = setTimeout(() => {
            wsReconnectId = null;
            setupWebSocket();
        }, reconnectDelay);
    };
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
    if (!wsConnection || wsConnection.readyState === WebSocket.CLOSED) setupWebSocket();
});
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && isMapViewActive()) {
        if (!wsConnection || wsConnection.readyState === WebSocket.CLOSED) {
            setupWebSocket();
        }
        loadStations();
        loadCorsBaseStations();
        loadRescueMarkers();
    }
});
window.addEventListener('spa:navigate', (event) => {
    if (event.detail?.view !== 'map') stopMapBackgroundWork();
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
            listBadge.className = `badge ${getRiskBadgeClass(riskUi.className)}`;
            listBadge.innerText = riskUi.display;

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
            if (Array.isArray(message.expected_station_ids)) {
                syncGnssExpectedStationIds(message.expected_station_ids);
            }
            setGnssAdjustmentPhase(message.phase, message.message || 'Server đã cập nhật phase.');
            const resultPhase = String(message.phase || '').toUpperCase();
            if (message.data && (resultPhase === 'COMPLETED' || resultPhase === 'FAILED_QUALITY_GATE')) {
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
                    resultPhase === 'FAILED_QUALITY_GATE'
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
                `${message.rover_name}: dN=${Number(message.baseline_neu?.[0]).toFixed(4)}, dE=${Number(message.baseline_neu?.[1]).toFixed(4)}, dH=${Number(message.baseline_neu?.[2]).toFixed(4)}`,
                'success',
            );
        }
        if (belongsToActiveRun && window.gnssBoardState && window.gnssBoardState.ctx) {
            const fromPoint = String(message.from || 'BASE');
            window.gnssBoardState.addPoint('BASE', 0, 0, true);
            const origin = window.gnssBoardState.points[fromPoint] || window.gnssBoardState.points.BASE;
            const relX = origin.x + Number(message.baseline_neu?.[1] || 0);
            const relY = origin.y + Number(message.baseline_neu?.[0] || 0);
            window.gnssBoardState.addPoint(message.rover_name, relX, relY, false);
            window.gnssBoardState.addBaseline(fromPoint, message.rover_name, {
                dn: message.baseline_neu[0],
                de: message.baseline_neu[1],
                dh: message.baseline_neu[2],
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
        if (!['COMPLETED', 'FAILED_QUALITY_GATE'].includes(gnssAdjustmentDebugState.phase)) return false;
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
    window.gnssBoardState?.loadAdjustmentResult?.(message.data);
    const adjResultsSection = document.getElementById('adj-results-section');
    const adjStatusEl = document.getElementById('adj-process-status');
    const adjTimeEl = document.getElementById('adj-val-time');
    const adjPointsList = document.getElementById('adj-points-list');

    if (adjStatusEl) {
        adjStatusEl.innerHTML = auditOnly
            ? '<span class="text-warning fw-bold"><i class="bi bi-file-earmark-check-fill me-1"></i>Đã tạo hồ sơ audit – không publish tọa độ</span>'
            : '<span class="text-success fw-bold"><i class="bi bi-check-circle-fill me-1"></i>Bình sai thành công</span>';
    }
    if (adjTimeEl) {
        const timestamp = Number(message.timestamp || message.data.computed_at || Date.now() / 1000);
        adjTimeEl.textContent = new Date(timestamp * 1000).toLocaleString();
    }
    if (adjResultsSection) adjResultsSection.style.display = 'block';
    if (adjPointsList) {
        adjPointsList.innerHTML = '';
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
        currentStationData.sensors[sensor_type].latest_timestamp = Number(timestamp || Date.now() / 1000);
    }

    const detailVisible = document.getElementById('detail-sidebar')?.classList.contains('active');
    const chartsVisible = document.getElementById('charts-panel')?.classList.contains('active');
    const advancedVisible = document.getElementById('gnss-advanced-sidepanel')?.classList.contains('active');
    if (!detailVisible && !chartsVisible && !advancedVisible) {
        if (sensor_type === 'imu' && data) maybeTriggerLocalImuCriticalFallback(stationId, data);
        return;
    }

    //console.log(`🔄 [REALTIME] ${sensor_type}:`, data);

    if (sensor_type === 'gnss' && data) {
        updateGnssFixBadge(data.fix_mode, data.fix_quality);

        const velocityMmS = getGnssVelocity(data);

        //console.log('📍 [GNSS] Velocity value:', velocityMmS, 'from data:', data);
        if (velocityMmS !== null) {
            animateValue('val-gnss-vel', velocityMmS, 4, 'mm/s');
        }

        // Update Advanced Sidepanel fields if it exists and data is available
        if (data.adv_x !== undefined) {
            if (advancedVisible) {
             // Vị trí hiện tại: VN2000 NEH
             setText('adv-val-lat', (data.adv_y || 0).toFixed(3));
             setText('adv-val-lon', (data.adv_x || 0).toFixed(3));
             setText('adv-val-alt', (data.adv_h || 0).toFixed(3));
             // Biến dạng lũy kế
            setText('adv-val-dx', (data.adv_dx || 0).toFixed(2));
            setText('adv-val-dy', (data.adv_dy || 0).toFixed(2));
            setText('adv-val-dh', (data.adv_dh || 0).toFixed(2));
             // Vận tốc biến dạng (mm/phút)
             setText('adv-val-vdx', (data.adv_vdx || 0).toFixed(2));
             setText('adv-val-vdy', (data.adv_vdy || 0).toFixed(2));
             setText('adv-val-vdh', (data.adv_vdh || 0).toFixed(2));
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
                     velocity_significant: data.velocity_significant,
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
                     displacement_sample_count: data.displacement_sample_count,
                     displacement_window_duration_s: data.displacement_window_duration_s,
                     num_sats: data.num_sats, hdop: data.hdop
                 });
             }
        }

        // Update Theil-Sen display in both Main Sidebar and Advanced Panel
        if (data.velocity_method === 'theil_sen_enu') {
            const sampleCount = data.velocity_sample_count || 0;
            const durationS = data.velocity_window_duration_s ? data.velocity_window_duration_s.toFixed(1) : 0;
            const rms = data.velocity_residual_rms_mm ? data.velocity_residual_rms_mm.toFixed(2) : 0;
            const mad = data.velocity_residual_mad_mm ? data.velocity_residual_mad_mm.toFixed(2) : '--';
            const uncert = data.velocity_uncertainty_mm_s ? data.velocity_uncertainty_mm_s.toFixed(4) : 0;
            const ci95 = data.velocity_confidence_95_mm_s ? data.velocity_confidence_95_mm_s.toFixed(4) : '--';

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
            setText('adv-val-raw-ve', (data.raw_vel_e_mm_s || 0).toFixed(4));
            setText('adv-val-raw-vn', (data.raw_vel_n_mm_s || 0).toFixed(4));
            setText('adv-val-raw-vu', (data.raw_vel_u_mm_s || 0).toFixed(4));
            setText('adv-val-raw-2d', (data.raw_speed_2d_mm_s || 0).toFixed(4));

            // Advanced Panel - Filtered velocity (sau Theil-Sen)
            setText('adv-val-filt-ve', (data.vel_e || 0).toFixed(4));
            setText('adv-val-filt-vn', (data.vel_n || 0).toFixed(4));
            setText('adv-val-filt-vu', (data.vel_u || 0).toFixed(4));
            setText('adv-val-filt-2d', velocityMmS !== null ? velocityMmS.toFixed(4) : '--');

            // Advanced Panel - Displacement
            setText('adv-val-disp-total', (data.total_displacement_mm || 0).toFixed(2));
            setText('adv-val-disp-peak', (data.peak_displacement_mm || 0).toFixed(2));
            setText('adv-val-disp-noise', (data.displacement_noise_floor_mm || 0).toFixed(3));
            setText('adv-val-disp-uncert', (data.displacement_uncertainty_mm || 0).toFixed(3));
            setText('adv-val-disp-window', data.displacement_sample_count || '--');
            setText('adv-val-disp-dur', (data.displacement_window_duration_s || 0).toFixed(1));

            // Advanced Panel - GNSS quality
            setText('adv-val-sats', data.num_sats || '--');
            setText('adv-val-hdop', data.hdop ? data.hdop.toFixed(1) : '--');

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
                const recvDate = new Date(data.timestamp * 1000);
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
                let trendHtml = '';
                if (data.velocity_significant === true) {
                    trendHtml = `<span class="text-warning"><i class="bi bi-arrow-right-circle-fill me-1"></i>Có chuyển dịch</span>`;
                } else {
                    trendHtml = `<span class="text-success"><i class="bi bi-check-circle-fill me-1"></i>Ổn định</span>`;
                }
                const velStr = velocityMmS !== null ? velocityMmS.toFixed(2) : '0.00';
                evalSummaryEl.innerHTML = `
                    <div class="d-flex flex-column gap-1">
                        <div>${trendHtml}</div>
                        <div class="text-muted fw-normal" style="font-size: 0.75rem;">
                            <i class="bi bi-speedometer2 me-1"></i>Vận tốc: <strong>${velStr} mm/s</strong>
                        </div>
                        <div class="text-muted fw-normal" style="font-size: 0.75rem;">
                            <i class="bi bi-funnel me-1"></i>Cửa sổ trượt: ${sampleCount} mẫu (${durationS}s)
                        </div>
                    </div>
                `;
            }
        }

        if (chartsVisible && charts['chart-gnss']) {
            const chart = charts['chart-gnss'];
            if (velocityMmS !== null) {
                chart.data.labels.push(new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
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
        const intensity = data.intensity_mm_h || data.intensity || 0;
        animateValue('val-rain', intensity, 1, 'mm/h');

        if (chartsVisible && charts['chart-rain']) {
            const chart = charts['chart-rain'];
            chart.data.labels.push(new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
            chart.data.datasets[0].data.push(intensity);

            if (chart.data.labels.length > 50) {
                chart.data.labels.shift();
                chart.data.datasets[0].data.shift();
            }

            chart.update('none');
        }
    }

    if (sensor_type === 'water' && data) {
        const level = data.water_level || data.level || data.processed_value_meters || 0;
        setHTML('val-water', formatWaterLevelDisplay(data));
        console.log('💧 [WATER] Level value:', level, 'from data:', data);
        if (chartsVisible && charts['chart-water']) {
            const chart = charts['chart-water'];
            chart.data.labels.push(new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
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
        if (data.drift_len_mm !== undefined && data.drift_dir !== undefined) {
            animateValue('val-imu-drift-len', (parseFloat(data.drift_len_mm) || 0) / 10, 1, ' cm', true);
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
            const timeLabel = new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            chart.data.labels.push(timeLabel);
            chart.data.datasets[0].data.push(parseFloat(data.roll) || 0);
            chart.data.datasets[1].data.push(parseFloat(data.pitch) || 0);
            chart.data.datasets[2].data.push(parseFloat(data.yaw) || 0);

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
