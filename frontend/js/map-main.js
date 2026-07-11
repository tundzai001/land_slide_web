// =====================================================
// MAP MAIN - FIXED VERSION
// =====================================================

console.log('[MAP] Script loaded, waiting for DOM...');

let map;
let currentTileLayer = null;
let markers = {};
let charts = {};
let currentStationData = null;
let allStations = [];
let currentView = 'realtime';
let wsConnection = null;
let latestRealtimeSensorTs = {}; // key: `${stationId}_${sensorType}` -> unix timestamp
let isRainCorrelationAiEnabled = false;
let rainCorrelationAiRunning = false;
let localImuFallbackNextAllowedAtByStation = {}; // cooldown để tránh spam banner/siren từ local fallback

// Realtime 3D state
let realtimeImuScene, realtimeImuCamera, realtimeImuRenderer, realtimeImuControls, realtimeImuAnimationId;
let realtimeImuSensorBlock = null;
let realtimeImuTargetQuaternion = null;
let realtimeImuActive = false;
let _THREE = null; // Cached Three.js module for use outside async import scope
let guestRescueModal = null;
let guestRescueImageBlob = null;
let guestRescueImagePreviewUrl = null;

// Rescue marker management
let rescueMarkers = {}; // key: rescue_request_id -> marker
let rescueRequestsData = []; // Store rescue data for popup reference
let corsBaseMarkers = {}; // key: station name -> marker
let showStationMarkers = true;
let stationClusterGroup = null;
let clusterPolylines = [];
let showRescueMarkers = true;
let currentMapMode = 'station';

const gnssAdjustmentDebugState = {
    active: false,
    projectId: null,
    phase: 'WAITING',
    expectedStationIds: [],
    baselineCount: 0,
    startedAt: null,
    wsStatus: 'CONNECTING',
    entries: [],
    entriesRevision: 0,
    autoScroll: true,
    lastGnssStatusAtByStation: {},
    watchdogId: null,
};

function formatGnssDebugTime(date = new Date()) {
    return date.toLocaleTimeString('vi-VN', { hour12: false });
}

function phaseClassForGnssAdjustment(phase) {
    switch (String(phase || '').toUpperCase()) {
        case 'COLLECTING_BASELINE': return 'ms-4 text-info fw-bold font-monospace';
        case 'FREE_NETWORK': return 'ms-4 text-warning fw-bold font-monospace';
        case 'COMPLETED': return 'ms-4 text-success fw-bold font-monospace';
        case 'ERROR': return 'ms-4 text-danger fw-bold font-monospace';
        default: return 'ms-4 text-warning fw-bold font-monospace';
    }
}

function refreshGnssAdjustmentDebugUi() {
    const indicator = document.getElementById('gnss-phase-indicator');
    if (indicator) {
        indicator.textContent = `Phase: ${gnssAdjustmentDebugState.phase}`;
        indicator.className = phaseClassForGnssAdjustment(gnssAdjustmentDebugState.phase);
    }

    const summary = document.getElementById('gnss-debug-summary');
    if (summary) {
        const elapsed = gnssAdjustmentDebugState.startedAt
            ? Math.floor((Date.now() - gnssAdjustmentDebugState.startedAt) / 1000)
            : 0;
        const expected = gnssAdjustmentDebugState.expectedStationIds.length
            ? gnssAdjustmentDebugState.expectedStationIds.join(', ')
            : 'chưa xác định';
        summary.textContent = `WS: ${gnssAdjustmentDebugState.wsStatus} | Baseline: ${gnssAdjustmentDebugState.baselineCount} | Chờ trạm: ${expected} | ${elapsed}s`;
    }

    const log = document.getElementById('gnss-debug-log');
    if (log) {
        const revision = String(gnssAdjustmentDebugState.entriesRevision);
        if (log.dataset.entriesRevision !== revision) {
            const previousScrollTop = log.scrollTop;
            const shouldAutoScroll = gnssAdjustmentDebugState.autoScroll;
            log.innerHTML = '';
            gnssAdjustmentDebugState.entries.forEach(entry => {
                const row = document.createElement('div');
                const color = entry.level === 'error'
                    ? '#ff6b6b'
                    : entry.level === 'warning'
                        ? '#ffd166'
                        : entry.level === 'success'
                            ? '#5eead4'
                            : '#93c5fd';
                row.style.color = color;
                row.textContent = `[${entry.time}] ${entry.label}: ${entry.message}`;
                log.appendChild(row);
            });
            log.dataset.entriesRevision = revision;
            if (shouldAutoScroll) {
                log.scrollTop = log.scrollHeight;
            } else {
                log.scrollTop = Math.min(
                    previousScrollTop,
                    Math.max(0, log.scrollHeight - log.clientHeight),
                );
            }
        }
        const followButton = document.getElementById('gnss-debug-follow');
        if (followButton) {
            followButton.classList.toggle('btn-warning', !gnssAdjustmentDebugState.autoScroll);
            followButton.classList.toggle('btn-outline-secondary', gnssAdjustmentDebugState.autoScroll);
            followButton.title = gnssAdjustmentDebugState.autoScroll
                ? 'Đang tự cuộn theo log mới'
                : 'Đã tạm dừng tự cuộn; bấm để xuống cuối';
        }
    }
}

function formatGnssAdjustmentDebugOutput() {
    return gnssAdjustmentDebugState.entries
        .map(entry => `[${entry.time}] ${entry.label}: ${entry.message}`)
        .join('\n');
}

async function copyGnssAdjustmentDebugOutput(button = null) {
    const output = formatGnssAdjustmentDebugOutput();
    if (!output) return;
    try {
        if (navigator.clipboard?.writeText && window.isSecureContext) {
            await navigator.clipboard.writeText(output);
        } else {
            const textarea = document.createElement('textarea');
            textarea.value = output;
            textarea.setAttribute('readonly', '');
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            textarea.remove();
        }
        if (button) {
            const originalText = button.innerHTML;
            button.textContent = 'Đã chép';
            setTimeout(() => { button.innerHTML = originalText; }, 1200);
        }
    } catch (error) {
        console.error('Could not copy GNSS debug output:', error);
        window.toast?.error?.('Không thể sao chép Live Debug');
    }
}

function scrollGnssAdjustmentDebugToBottom() {
    gnssAdjustmentDebugState.autoScroll = true;
    const log = document.getElementById('gnss-debug-log');
    if (log) log.scrollTop = log.scrollHeight;
    refreshGnssAdjustmentDebugUi();
}

function addGnssAdjustmentDebug(label, message, level = 'info') {
    if (!gnssAdjustmentDebugState.active) return;
    gnssAdjustmentDebugState.entries.push({
        time: formatGnssDebugTime(),
        label,
        message: String(message || '-'),
        level,
    });
    gnssAdjustmentDebugState.entriesRevision += 1;
    if (gnssAdjustmentDebugState.entries.length > 500) {
        gnssAdjustmentDebugState.entries.splice(0, gnssAdjustmentDebugState.entries.length - 500);
    }
    refreshGnssAdjustmentDebugUi();
}

function setGnssAdjustmentPhase(phase, message = '') {
    gnssAdjustmentDebugState.phase = String(phase || 'WAITING').toUpperCase();
    refreshGnssAdjustmentDebugUi();
    if (message) addGnssAdjustmentDebug('PHASE', message, gnssAdjustmentDebugState.phase === 'ERROR' ? 'error' : 'info');
}

function resetGnssAdjustmentDebug({ projectId, stationIds } = {}) {
    if (gnssAdjustmentDebugState.watchdogId) clearInterval(gnssAdjustmentDebugState.watchdogId);
    Object.assign(gnssAdjustmentDebugState, {
        active: true,
        projectId: Number(projectId) || null,
        phase: 'WAITING',
        expectedStationIds: Array.isArray(stationIds) ? stationIds.map(Number).filter(Number.isFinite) : [],
        baselineCount: 0,
        startedAt: Date.now(),
        wsStatus: wsConnection?.readyState === WebSocket.OPEN ? 'CONNECTED' : 'DISCONNECTED',
        entries: [],
        entriesRevision: gnssAdjustmentDebugState.entriesRevision + 1,
        autoScroll: true,
        lastGnssStatusAtByStation: {},
    });
    const resultsSection = document.getElementById('adj-results-section');
    const pointsList = document.getElementById('adj-points-list');
    if (resultsSection) resultsSection.style.display = 'none';
    if (pointsList) pointsList.innerHTML = '';
    addGnssAdjustmentDebug('UI', 'Đã mở phiên debug Bình sai.', 'info');
    gnssAdjustmentDebugState.watchdogId = setInterval(() => {
        if (!gnssAdjustmentDebugState.active) return;
        const elapsed = Math.floor((Date.now() - gnssAdjustmentDebugState.startedAt) / 1000);
        if (elapsed >= 10 && gnssAdjustmentDebugState.baselineCount === 0 && gnssAdjustmentDebugState.phase === 'COLLECTING_BASELINE') {
            const last = gnssAdjustmentDebugState.entries.at(-1);
            if (!last || last.label !== 'WAIT') {
                addGnssAdjustmentDebug('WAIT', 'Chưa nhận baseline hợp lệ. Kiểm tra #AGRICA, RTK Fixed và WebSocket.', 'warning');
            }
        } else {
            refreshGnssAdjustmentDebugUi();
        }
    }, 1000);
}

const TILE_URLS = {
    light: 'https://{s}.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
    dark: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
};
const TILE_OPTIONS = {
    light: { maxZoom: 20, subdomains: ['mt0', 'mt1', 'mt2', 'mt3'] },
    dark: { maxZoom: 20, subdomains: ['a', 'b', 'c', 'd'] }
};

function runWhenDomReady(callback) {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', callback, { once: true });
    } else {
        callback();
    }
}

function normalizeRiskLevel(rawRisk, stationStatus = null) {
    if (stationStatus === 'offline') return 'OFFLINE';
    if (stationStatus === 'stale') return 'STALE';

    const level = String(rawRisk || 'LOW').toUpperCase();
    if (level === 'OFFLINE') return 'OFFLINE';
    if (level === 'STALE') return 'STALE';
    if (level === 'LOW' || level === 'SAFE') return 'LOW';
    if (level === 'WARNING' || level === 'MEDIUM' || level === 'HIGH') return 'MEDIUM';
    if (level === 'CRITICAL' || level === 'EXTREME') return 'CRITICAL';
    return 'LOW';
}

function getRiskPresentation(rawRisk, stationStatus = null) {
    const normalized = normalizeRiskLevel(rawRisk, stationStatus);
    if (normalized === 'OFFLINE') {
        return { normalized, display: 'OFFLINE', className: 'OFFLINE' };
    }
    if (normalized === 'STALE') {
        return { normalized, display: 'STALE', className: 'STALE' };
    }
    if (normalized === 'MEDIUM') {
        return { normalized, display: 'WARNING', className: 'MEDIUM' };
    }
    if (normalized === 'CRITICAL') {
        return { normalized, display: 'CRITICAL', className: 'CRITICAL' };
    }
    return { normalized, display: 'SAFE', className: 'LOW' };
}

function normalizeAlertLevel(rawLevel) {
    const level = String(rawLevel || '').toUpperCase();
    if (level === 'CRITICAL' || level === 'EXTREME') return 'CRITICAL';
    if (level === 'WARNING' || level === 'MEDIUM' || level === 'HIGH') return 'WARNING';
    return 'WARNING';
}

function normalizeIncomingAlert(alertData) {
    if (!alertData || typeof alertData !== 'object') return alertData;

    const normalized = { ...alertData };
    const sensorType = String(normalized.sensor_type || '').toLowerCase();
    const rawLevel = String(normalized.level || normalized.risk_level || '').toUpperCase();
    const isDangerous = ['WARNING', 'MEDIUM', 'HIGH', 'CRITICAL', 'EXTREME'].includes(rawLevel);

    // FE safety net: IMU dangerous alerts are always treated as CRITICAL.
    if (sensorType === 'imu' && isDangerous) {
        normalized.level = 'CRITICAL';
        if (normalized.category === 'tilt_warning') {
            normalized.category = 'tilt_critical';
        }
        if (!normalized.audio_code || normalized.audio_code === 'imu_warning') {
            normalized.audio_code = 'imu_critical';
        }
    }

    return normalized;
}

function buildAlertKey(alertData) {
    if (!alertData || typeof alertData !== 'object') return '';
    const stationId = alertData.station_id ?? '';
    const sensorType = String(alertData.sensor_type || alertData.category || 'unknown').toLowerCase();
    const level = normalizeAlertLevel(alertData.level || alertData.risk_level || 'WARNING');
    return `${stationId}_${sensorType}_${level}`;
}

function mapAlertCategoryToSensorType(category) {
    const cat = String(category || '').toLowerCase();
    if (cat === 'gnss_velocity') return 'gnss';
    if (cat === 'rainfall') return 'rain';
    if (cat === 'water_level') return 'water';
    if (cat === 'tilt' || cat === 'tilt_warning' || cat === 'tilt_critical' || cat === 'shock') return 'imu';
    return cat;
}

function isBannerSuppressed(stationId) {
    const until = Number(bannerSuppressedUntilByStation[stationId] || 0);
    return Date.now() < until;
}

function getAlertSeverity(rawLevel) {
    const normalized = normalizeAlertLevel(rawLevel);
    return normalized === 'CRITICAL' ? 2 : 1;
}

function updateAlertBannerTheme(rawLevel) {
    const banner = document.getElementById('alert-banner');
    if (!banner) return;

    const normalized = normalizeAlertLevel(rawLevel);
    banner.classList.remove('level-warning', 'level-critical');
    banner.classList.add(normalized === 'CRITICAL' ? 'level-critical' : 'level-warning');
    banner.dataset.alertLevel = normalized;
}

function getDefaultAlertMessageForStationStatus(riskUi) {
    if (riskUi?.normalized === 'CRITICAL') {
        return 'Critical risk detected from realtime station status.';
    }
    return 'Warning risk detected from realtime station status.';
}

function getImuCriticalThresholdDegFromCurrentStation() {
    const cfg = currentStationData?.config || {};
    const imuCfg = cfg.ImuAlerting || cfg.imu_alerting || {};
    const raw = parseFloat(imuCfg.tilt_critical_deg);
    return Number.isFinite(raw) && raw > 0 ? raw : 15.0;
}

function isImuCriticalAlertAlreadyKnown(stationId) {
    const latest = latestAlertByStation[stationId];
    if (latest && String(latest.sensor_type || '').toLowerCase() === 'imu') {
        const lv = normalizeAlertLevel(latest.level || latest.risk_level);
        if (lv === 'CRITICAL') return true;
    }

    const activeAlerts = currentStationData?.risk_assessment?.active_alerts || [];
    return activeAlerts.some(a => {
        const sensorType = mapAlertCategoryToSensorType(a.category);
        return sensorType === 'imu' && normalizeAlertLevel(a.level) === 'CRITICAL';
    });
}

function maybeTriggerLocalImuCriticalFallback(stationId, data) {
    if (!stationId || !data) return;
    if (isImuCriticalAlertAlreadyKnown(stationId)) return;

    const roll = parseFloat(data.roll);
    const pitch = parseFloat(data.pitch);
    if (!Number.isFinite(roll) || !Number.isFinite(pitch)) return;

    const deltaTiltDeg = Math.sqrt((roll * roll) + (pitch * pitch));
    const criticalDeg = getImuCriticalThresholdDegFromCurrentStation();
    if (deltaTiltDeg < criticalDeg) return;

    const now = Date.now();
    const nextAllowedAt = Number(localImuFallbackNextAllowedAtByStation[stationId] || 0);
    if (now < nextAllowedAt) return;
    localImuFallbackNextAllowedAtByStation[stationId] = now + 10000;

    const localAlert = {
        type: 'alert',
        station_id: stationId,
        sensor_type: 'imu',
        level: 'CRITICAL',
        category: 'tilt_critical',
        audio_code: 'imu_critical',
        message: `IMU local fallback: delta tilt ${deltaTiltDeg.toFixed(1)}° >= ${criticalDeg.toFixed(1)}°`
    };

    latestAlertByStation[stationId] = localAlert;
    showAlertBanner(localAlert);
    setMarkerAlert(stationId, true);
    setSensorCardAlert('imu', 'CRITICAL');
    playSiren();
}

// =====================================================
// MAIN INITIALIZATION
// =====================================================

runWhenDomReady(initialize);

function initialize() {
    console.log('✅ [MAP] DOM ready, initializing...');

    // Set global Chart.js animation defaults for smooth realtime updates
    if (window.Chart) {
        Chart.defaults.animation.duration = 300;
        Chart.defaults.animation.easing = 'easeOutQuart';
    }

    initMap();
    setupEventListeners();
    setupMarkerLayerControls();
    setupGuestRescueUI();
    loadStations();
    loadCorsBaseStations();
    loadRescueMarkers();
    setupWebSocket();

    const stationSidebar = document.getElementById('station-list-sidebar');
    if (stationSidebar) {
        stationSidebar.classList.add('hidden');
    }

    const toggleBtn = document.getElementById('toggle-list-btn');
    if (toggleBtn) {
        toggleBtn.innerHTML = '<i class="bi bi-list"></i>';
    }

    setInterval(loadStations, 30000);
    setInterval(loadCorsBaseStations, 300000);
    setInterval(loadRescueMarkers, 60000);

    // ✅ Refresh sensor online status of currently-viewed station every 30s
    // (handles case where a device goes offline while the sidebar is already open)
    setInterval(refreshCurrentStationDetail, 30000);

    console.log('✅ [MAP] Initialization complete!');
}

// =====================================================
// WEBSOCKET REALTIME CONNECTION
// =====================================================

function setupWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/updates`;

    console.log('🔌 [WS] Connecting to:', wsUrl);

    wsConnection = new WebSocket(wsUrl);

    wsConnection.onopen = () => {
        console.log('✅ [WS] Connected');
        gnssAdjustmentDebugState.wsStatus = 'CONNECTED';
        if (gnssAdjustmentDebugState.active) addGnssAdjustmentDebug('WS', 'WebSocket đã kết nối.', 'success');
        else refreshGnssAdjustmentDebugUi();
    };

    wsConnection.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            handleRealtimeUpdate(message);
        } catch (e) {
            console.error('❌ [WS] Parse error:', e);
        }
    };

    wsConnection.onerror = (error) => {
        console.error('❌ [WS] Error:', error);
        gnssAdjustmentDebugState.wsStatus = 'ERROR';
        if (gnssAdjustmentDebugState.active) addGnssAdjustmentDebug('WS', 'WebSocket gặp lỗi kết nối.', 'error');
        else refreshGnssAdjustmentDebugUi();
    };

    wsConnection.onclose = () => {
        console.warn('⚠️ [WS] Disconnected, reconnecting in 5s...');
        gnssAdjustmentDebugState.wsStatus = 'DISCONNECTED';
        if (gnssAdjustmentDebugState.active) addGnssAdjustmentDebug('WS', 'WebSocket bị ngắt; tự kết nối lại sau 5 giây.', 'warning');
        else refreshGnssAdjustmentDebugUi();
        setTimeout(setupWebSocket, 5000);
    };

    // Keepalive ping
    setInterval(() => {
        if (wsConnection.readyState === WebSocket.OPEN) {
            wsConnection.send('ping');
        }
    }, 30000);
}

function handleRealtimeUpdate(message) {
    //console.log('📡 [WS] Received:', message);

    if (message.type === 'sensor_data') {
        if (currentStationData && message.station_id === currentStationData.id) {
            updateRealtimeSensorValues(message);
        }
    }

    if (message.type === 'sensor_status') {
        if (
            currentStationData
            && message.station_id === currentStationData.id
            && message.sensor_type === 'gnss_adjusted'
        ) {
            updateRealtimeSensorValues(message);
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
                gnssAdjustmentDebugState.expectedStationIds = message.expected_station_ids;
            }
            setGnssAdjustmentPhase(message.phase, message.message || 'Server đã cập nhật phase.');
            if (String(message.phase || '').toUpperCase() === 'COMPLETED' && message.data) {
                updateRealtimeSensorValues({
                    sensor_type: 'gnss_adjusted',
                    timestamp: message.timestamp || message.data.computed_at || Math.floor(Date.now() / 1000),
                    data: message.data,
                });
                addGnssAdjustmentDebug('REPORT', 'Đã nhận liên kết tải JSON và XLSX.', 'success');
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
            gnssAdjustmentDebugState.baselineCount += 1;
            addGnssAdjustmentDebug(
                'BASELINE',
                `${message.rover_name}: dN=${Number(message.baseline_neu?.[0]).toFixed(4)}, dE=${Number(message.baseline_neu?.[1]).toFixed(4)}, dH=${Number(message.baseline_neu?.[2]).toFixed(4)}`,
                'success',
            );
        }
        if (belongsToActiveRun && window.gnssBoardState && window.gnssBoardState.ctx) {
            // Add Base Point at 0,0 for relative visualization
            window.gnssBoardState.addPoint("BASE", 0, 0, true);
            
            const relX = message.baseline_neu[1]; // dE
            const relY = message.baseline_neu[0]; // dN
            window.gnssBoardState.addPoint(message.rover_name, relX, relY, false);
            
            window.gnssBoardState.addBaseline("BASE", message.rover_name, {
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
        // success panel.  The project-level COMPLETED event will render it.
        if (gnssAdjustmentDebugState.phase !== 'COMPLETED') return false;
        const resultTimestamp = Number(timestamp || result.computed_at || result.epoch_ts || 0);
        const runStartedAt = Math.floor(Number(gnssAdjustmentDebugState.startedAt || 0) / 1000);
        if (runStartedAt && (!resultTimestamp || resultTimestamp < runStartedAt - 2)) {
            return false;
        }
    }
    return true;
}

function updateRealtimeSensorValues(message) {
    if (message.sensor_type === 'gnss_adjusted' && message.data) {
        if (!isGnssAdjustmentResultRelevant(message.data, message.timestamp)) return;
        window.gnssBoardState?.loadAdjustmentResult?.(message.data);
        const adjResultsSection = document.getElementById('adj-results-section');
        const adjStatusEl = document.getElementById('adj-process-status');
        const adjTimeEl = document.getElementById('adj-val-time');
        const adjPointsList = document.getElementById('adj-points-list');
        
        const ind = document.getElementById('gnss-phase-indicator');
        gnssAdjustmentDebugState.phase = 'COMPLETED';
        if (ind) {
            ind.textContent = `Phase: COMPLETED`;
            ind.className = 'ms-4 text-success fw-bold font-monospace';
        }

        if (adjStatusEl) {
            adjStatusEl.innerHTML = `<span class="text-success fw-bold"><i class="bi bi-check-circle-fill me-1"></i>Bình sai thành công</span>`;
        }
        if (adjTimeEl) {
            adjTimeEl.textContent = new Date(message.timestamp * 1000).toLocaleString();
        }
        if (adjResultsSection) {
            adjResultsSection.style.display = 'block';
        }
        if (adjPointsList) {
            adjPointsList.innerHTML = '';
            
            // Add download Excel workbook button
            if (message.data.excel_report_url) {
                const downloadXlsBtn = document.createElement('a');
                downloadXlsBtn.href = message.data.excel_report_url;
                downloadXlsBtn.target = '_blank';
                downloadXlsBtn.className = 'btn btn-sm btn-outline-success w-100 mb-2 py-1';
                downloadXlsBtn.style.fontSize = '0.72rem';
                downloadXlsBtn.innerHTML = '<i class="bi bi-file-earmark-spreadsheet me-1"></i> Tải báo cáo bình sai (Excel)';
                adjPointsList.appendChild(downloadXlsBtn);
            }
            // Add download report button
            if (message.data.report_file_url) {
                const downloadBtn = document.createElement('a');
                downloadBtn.href = message.data.report_file_url;
                downloadBtn.target = '_blank';
                downloadBtn.className = 'btn btn-sm btn-outline-info w-100 mb-2 py-1';
                downloadBtn.style.fontSize = '0.72rem';
                downloadBtn.innerHTML = '<i class="bi bi-download me-1"></i> Tải báo cáo bình sai (JSON)';
                adjPointsList.appendChild(downloadBtn);
            }
            
            if (message.data.points) {
                for (const [ptName, ptCoords] of Object.entries(message.data.points)) {
                    const coordinates = getAdjustedPointCoordinates(ptCoords);
                    const item = document.createElement('div');
                    item.className = 'list-group-item bg-transparent text-slate-300 py-1 px-0 d-flex justify-content-between align-items-center border-bottom border-secondary';
                    item.innerHTML = `
                        <span class="fw-semibold text-info font-monospace" style="font-size:0.75rem;">${ptName}</span>
                        <span class="text-light font-monospace text-end" style="font-size:0.68rem; line-height: 1.2;">
                            X: ${formatAdjustedCoordinate(coordinates[0])}<br>
                            Y: ${formatAdjustedCoordinate(coordinates[1])}<br>
                            Z: ${formatAdjustedCoordinate(coordinates[2])}
                        </span>
                    `;
                    adjPointsList.appendChild(item);
                }
            }
        }
    }
    const { sensor_type, data, timestamp, station_id } = message;
    const stationId = station_id || currentStationData?.id;

    if (stationId && sensor_type && timestamp) {
        latestRealtimeSensorTs[`${stationId}_${sensor_type}`] = Number(timestamp);
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

        if (charts['chart-gnss']) {
            const chart = charts['chart-gnss'];
            if (velocityMmS !== null) {
                chart.data.labels.push(new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
                chart.data.datasets[0].data.push(velocityMmS);

                if (chart.data.labels.length > 50) {
                    chart.data.labels.shift();
                    chart.data.datasets[0].data.shift();
                }

                chart.update();
            }
        }
    }

    if (sensor_type === 'rain' && data) {
        const intensity = data.intensity_mm_h || data.intensity || 0;
        animateValue('val-rain', intensity, 1, 'mm/h');

        if (charts['chart-rain']) {
            const chart = charts['chart-rain'];
            chart.data.labels.push(new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
            chart.data.datasets[0].data.push(intensity);

            if (chart.data.labels.length > 50) {
                chart.data.labels.shift();
                chart.data.datasets[0].data.shift();
            }

            chart.update();
        }
    }

    if (sensor_type === 'water' && data) {
        const level = data.water_level || data.level || data.processed_value_meters || 0;
        setHTML('val-water', formatWaterLevelDisplay(data));
        console.log('💧 [WATER] Level value:', level, 'from data:', data);
        if (charts['chart-water']) {
            const chart = charts['chart-water'];
            chart.data.labels.push(new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
            chart.data.datasets[0].data.push(level);

            if (chart.data.labels.length > 50) {
                chart.data.labels.shift();
                chart.data.datasets[0].data.shift();
            }

            chart.update();
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
        if (!charts['chart-imu'] && imuCanvas) {
            renderImuChart(currentStationData?.sensors?.imu?.history || []);
        }
        if (charts['chart-imu']) {
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

            chart.update();
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
                width: 18px; height: 18px; background: ${color};
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

// =====================================================
// MARKER ALERT STATE — Đỏ + nhấp nháy khi có cảnh báo
// =====================================================
let markerAlertState = {};

function setMarkerAlert(stationId, active) {
    const marker = markers[stationId];
    if (!marker) return;

    if (active) {
        markerAlertState[stationId] = true;

        const iconHtml = `<div class="marker-circle marker-device-alert" style="
                    width: 22px; height: 22px; background: #fa5252;
                    border-radius: 50%; border: 3px solid white;
                    box-shadow: 0 0 12px rgba(250, 82, 82, 0.8);
                "></div>`;

        const alertIcon = L.divIcon({
            className: 'custom-map-marker',
            html: iconHtml,
            iconSize: [22, 22],
            iconAnchor: [11, 11]
        });
        marker.setIcon(alertIcon);

        console.log(`🔴 [MARKER] Station ${stationId} → ĐỎ + nhấp nháy`);
    } else {
        clearMarkerAlert(stationId);
    }
}

function clearMarkerAlert(stationId) {
    delete markerAlertState[stationId];

    // Tìm station data để khôi phục màu gốc theo risk_level
    const station = allStations.find(s => s.id === stationId);
    if (station) {
        // Xóa cache để bắt buộc vẽ lại marker
        delete stationStateCache[stationId];
        updateMarker(station);
    }

    console.log(`🟢 [MARKER] Station ${stationId} → Khôi phục màu gốc`);
}

// (updateSidebarUI đã được chuyển xuống dưới — duy nhất 1 bản)

function setupGuestRescueUI() {
    const openBtn = document.getElementById('btn-guest-rescue');
    const modalEl = document.getElementById('guestRescueModal');
    if (!openBtn || !modalEl || !window.bootstrap) return;

    window.rescueFormModal = new bootstrap.Modal(modalEl);
    const locateBtn = document.getElementById('btn-guest-rescue-locate');
    const submitBtn = document.getElementById('btn-guest-rescue-submit');
    const imageInput = document.getElementById('guest-rescue-image');
    const imagePreviewWrap = document.getElementById('guest-rescue-image-preview-wrap');
    const imagePreview = document.getElementById('guest-rescue-image-preview');
    const clearImageBtn = document.getElementById('btn-guest-rescue-image-clear');

    const typeRadios = document.querySelectorAll('input[name="guest-rescue-type"]');
    const otherWrap = document.getElementById('guest-rescue-other-wrap');
    if (typeRadios && otherWrap) {
        typeRadios.forEach(radio => {
            radio.addEventListener('change', () => {
                if (radio.value === 'khac' && radio.checked) {
                    otherWrap.style.display = 'block';
                    setTimeout(() => {
                        otherWrap.style.opacity = '1';
                    }, 10);
                } else {
                    otherWrap.style.opacity = '0';
                    setTimeout(() => {
                        if (!document.getElementById('guest-rescue-type-other').checked) {
                            otherWrap.style.display = 'none';
                        }
                    }, 300);
                }
            });
        });
    }

    openBtn.addEventListener('click', () => {
        if (window.rescueFormModal) window.rescueFormModal.show();
        fillGuestRescueLocation();
    });

    if (locateBtn) {
        locateBtn.addEventListener('click', () => fillGuestRescueLocation(true));
    }

    if (submitBtn) {
        submitBtn.addEventListener('click', submitGuestRescueRequest);
    }

    if (imageInput) {
        imageInput.addEventListener('change', async () => {
            const file = imageInput.files?.[0];
            if (!file || !imagePreview || !imagePreviewWrap) {
                return;
            }

            try {
                const blob = await compressImageToBlob(file, 1280, 0.75);
                guestRescueImageBlob = blob;

                if (guestRescueImagePreviewUrl) {
                    URL.revokeObjectURL(guestRescueImagePreviewUrl);
                }
                guestRescueImagePreviewUrl = URL.createObjectURL(blob);
                imagePreview.src = guestRescueImagePreviewUrl;
                imagePreviewWrap.style.display = 'block';
            } catch (e) {
                console.error('compressImageToBlob error:', e);
                window.toast?.error('Không đọc được ảnh. Vui lòng thử ảnh khác.');
            }
        });
    }

    if (clearImageBtn) {
        clearImageBtn.addEventListener('click', () => {
            if (imageInput) {
                imageInput.value = '';
            }
            guestRescueImageBlob = null;
            if (imagePreview) {
                imagePreview.src = '';
            }
            if (guestRescueImagePreviewUrl) {
                URL.revokeObjectURL(guestRescueImagePreviewUrl);
                guestRescueImagePreviewUrl = null;
            }
            if (imagePreviewWrap) {
                imagePreviewWrap.style.display = 'none';
            }
        });
    }

    const searchActionBtn = document.getElementById('btn-guest-rescue-search-address-action');
    const searchInput = document.getElementById('guest-rescue-address-search');
    const searchResults = document.getElementById('guest-rescue-address-results');
    const latEl = document.getElementById('guest-rescue-lat');
    const lonEl = document.getElementById('guest-rescue-lon');

    if (searchActionBtn && searchInput && searchResults) {
        let isSearching = false;

        const performSearch = async () => {
            if (isSearching) return;
            const query = searchInput.value.trim();
            if (!query) return;

            isSearching = true;
            searchActionBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            searchResults.style.display = 'block';
            searchResults.innerHTML = '<div class="list-group-item text-muted small text-center"><span class="spinner-border spinner-border-sm me-2"></span>Đang tìm...</div>';

            try {
                const encodedQuery = encodeURIComponent(query + ', Vietnam');
                const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodedQuery}&limit=5`;
                const response = await fetch(url, {
                    headers: { 'Accept': 'application/json', 'User-Agent': 'LandslideRescueApp/1.0' }
                });
                if (!response.ok) throw new Error('Network response was not ok');
                const data = await response.json();

                if (data && data.length > 0) {
                    searchResults.innerHTML = '';
                    data.forEach(item => {
                        const btn = document.createElement('button');
                        btn.type = 'button';
                        btn.className = 'list-group-item list-group-item-action py-2';
                        btn.innerHTML = `<div class="d-flex align-items-center gap-2">
                                            <i class="bi bi-geo-alt-fill text-danger text-opacity-75"></i>
                                            <div style="font-size:0.8rem; line-height: 1.3; text-align: left;">
                                                <div class="fw-bold text-truncate" style="max-width: 250px;">${item.name || 'Địa điểm'}</div>
                                                <div class="text-muted text-truncate" style="font-size:0.75rem; max-width: 250px;">${item.display_name}</div>
                                            </div>
                                         </div>`;
                        btn.addEventListener('click', () => {
                            if (latEl) latEl.value = parseFloat(item.lat).toFixed(6);
                            if (lonEl) lonEl.value = parseFloat(item.lon).toFixed(6);
                            searchInput.value = item.display_name;
                            searchResults.style.display = 'none';
                            window.toast?.success('Đã ghim toạ độ từ địa chỉ!');

                            // Optional: Draw marker on map directly
                            if (window.map) {
                                const lat = parseFloat(item.lat);
                                const lon = parseFloat(item.lon);
                                if (window.userLocationMarker) {
                                    window.map.removeLayer(window.userLocationMarker);
                                }
                                if (window.userLocationCircle) {
                                    window.map.removeLayer(window.userLocationCircle);
                                }
                                window.userLocationMarker = L.marker([lat, lon], {
                                    icon: L.divIcon({
                                        className: 'user-location-marker',
                                        html: '<div style="width: 18px; height: 18px; background: #0d6efd; border-radius: 50%; border: 3px solid white; box-shadow: 0 0 15px rgba(13,110,253,0.8); animation: guestRescuePulse 1.5s infinite;"></div>',
                                        iconSize: [18, 18],
                                        iconAnchor: [9, 9]
                                    })
                                }).addTo(window.map).bindPopup('Vị trí đã chọn từ địa chỉ');
                                window.map.setView([lat, lon], 14, { animate: true });
                            }
                        });
                        searchResults.appendChild(btn);
                    });
                } else {
                    searchResults.innerHTML = '<div class="list-group-item text-danger small text-center">Không tìm thấy địa điểm này.</div>';
                }
            } catch (error) {
                console.error('Nominatim search error:', error);
                searchResults.innerHTML = '<div class="list-group-item text-danger small text-center">Lỗi mạng, kiểm tra kết nối internet.</div>';
            } finally {
                isSearching = false;
                searchActionBtn.innerHTML = '<i class="bi bi-search d-none d-sm-inline"></i> Tìm toạ độ';
            }
        };

        searchActionBtn.addEventListener('click', performSearch);
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                performSearch();
            }
        });

        // Hide results if click outside
        document.addEventListener('click', (e) => {
            if (!searchInput.contains(e.target) && !searchResults.contains(e.target) && !searchActionBtn.contains(e.target)) {
                searchResults.style.display = 'none';
            }
        });
    }
}

async function compressImageToBlob(file, maxWidth = 1280, jpegQuality = 0.75) {
    const fileDataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });

    const img = await new Promise((resolve, reject) => {
        const el = new Image();
        el.onload = () => resolve(el);
        el.onerror = reject;
        el.src = fileDataUrl;
    });

    let targetWidth = img.width;
    let targetHeight = img.height;
    if (img.width > maxWidth) {
        const ratio = maxWidth / img.width;
        targetWidth = maxWidth;
        targetHeight = Math.round(img.height * ratio);
    }

    const canvas = document.createElement('canvas');
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) {
        throw new Error('Canvas context unavailable');
    }

    ctx.drawImage(img, 0, 0, targetWidth, targetHeight);
    return await new Promise((resolve, reject) => {
        canvas.toBlob((blob) => {
            if (!blob) {
                reject(new Error('Canvas toBlob failed'));
                return;
            }
            resolve(blob);
        }, 'image/jpeg', jpegQuality);
    });
}

function fillGuestRescueLocation(showToast = false) {
    const latEl = document.getElementById('guest-rescue-lat');
    const lonEl = document.getElementById('guest-rescue-lon');
    if (!latEl || !lonEl) return;

    if (!navigator.geolocation) {
        if (showToast) window.toast?.warning('Thiết bị không hỗ trợ GPS');
        return;
    }

    navigator.geolocation.getCurrentPosition(
        (pos) => {
            const lat = pos.coords.latitude;
            const lon = pos.coords.longitude;
            latEl.value = Number(lat).toFixed(7);
            lonEl.value = Number(lon).toFixed(7);
            latEl.dataset.accuracy = Number(pos.coords.accuracy || 0).toFixed(1);
            if (showToast) {
                window.toast?.success(`Đã lấy vị trí (±${latEl.dataset.accuracy}m)`);
            }

            // Vẽ marker cho user location
            if (window.userLocationMarker && window.map) {
                window.map.removeLayer(window.userLocationMarker);
            }
            if (window.userLocationCircle && window.map) {
                window.map.removeLayer(window.userLocationCircle);
            }
            if (window.map) {
                window.userLocationMarker = L.marker([lat, lon], {
                    icon: L.divIcon({
                        className: 'user-location-marker',
                        html: '<div style="width: 18px; height: 18px; background: #0d6efd; border-radius: 50%; border: 3px solid white; box-shadow: 0 0 15px rgba(13,110,253,0.8); animation: guestRescuePulse 1.5s infinite;"></div>',
                        iconSize: [18, 18],
                        iconAnchor: [9, 9]
                    })
                }).addTo(window.map).bindPopup('Vị trí hiện tại của bạn');

                window.userLocationCircle = L.circle([lat, lon], {
                    radius: pos.coords.accuracy,
                    color: '#0d6efd',
                    fillColor: '#0d6efd',
                    fillOpacity: 0.15,
                    weight: 1
                }).addTo(window.map);

                window.map.setView([lat, lon], 14, { animate: true });
            }
        },
        (err) => {
            console.warn('Geolocation error:', err);
            if (showToast) window.toast?.error('Không lấy được vị trí. Hãy bật GPS/quyền vị trí.');
        },
        {
            enableHighAccuracy: true,
            timeout: 12000,
            maximumAge: 15000,
        }
    );
}

async function submitGuestRescueRequest() {
    const nameEl = document.getElementById('guest-rescue-name');
    const phoneEl = document.getElementById('guest-rescue-phone');
    const noteEl = document.getElementById('guest-rescue-note');
    const typeEl = document.querySelector('input[name="guest-rescue-type"]:checked');
    const provinceEl = document.getElementById('guest-rescue-province');
    const sourceLinkEl = document.getElementById('guest-rescue-source-link');
    const imagePreview = document.getElementById('guest-rescue-image-preview');
    const imagePreviewWrap = document.getElementById('guest-rescue-image-preview-wrap');
    const imageInput = document.getElementById('guest-rescue-image');
    const latEl = document.getElementById('guest-rescue-lat');
    const lonEl = document.getElementById('guest-rescue-lon');
    const submitBtn = document.getElementById('btn-guest-rescue-submit');
    if (!nameEl || !phoneEl || !noteEl || !latEl || !lonEl || !submitBtn) return;

    const latitude = parseFloat(latEl.value);
    const longitude = parseFloat(lonEl.value);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
        window.toast?.warning('Vui lòng bấm "Lấy vị trí hiện tại" trước khi gửi');
        return;
    }

    let message = String(noteEl.value || '').trim();
    const requesterName = String(nameEl.value || '').trim();
    const phone = String(phoneEl.value || '').trim();
    let rescueType = String(typeEl?.value || 'can_cuu_ho');
    if (rescueType === 'khac') {
        const otherInput = document.getElementById('guest-rescue-other-input');
        if (otherInput && otherInput.value.trim() !== '') {
            rescueType = `Khác: ${otherInput.value.trim()}`;
        }
    }
    const provinceCity = String(provinceEl?.value || '').trim();
    const sourceLink = String(sourceLinkEl?.value || '').trim();

    const searchAddressEl = document.getElementById('guest-rescue-address-search');
    const manualAddressEl = document.getElementById('guest-rescue-address-manual');
    const typedAddress = String(searchAddressEl?.value || '').trim();
    const manualAddress = String(manualAddressEl?.value || '').trim();

    if (manualAddress) {
        message = `[Địa chỉ chi tiết]: ${manualAddress}\n\n${message}`;
    }
    if (typedAddress) {
        message = `[Khu vực vị trí Map]: ${typedAddress}\n${message}`;
    }

    if (!message) {
        window.toast?.warning('Hãy nhập mô tả ngắn tình trạng cần cứu hộ');
        return;
    }

    const oldHtml = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Đang gửi...';

    try {
        const formData = new FormData();
        formData.append('requester_name', requesterName);
        formData.append('phone', phone);
        formData.append('message', message);
        formData.append('latitude', String(latitude));
        formData.append('longitude', String(longitude));
        formData.append('accuracy_m', String(Number(latEl.dataset.accuracy || 0) || ''));
        formData.append('rescue_type', rescueType);
        formData.append('province_city', provinceCity);
        formData.append('source_link', sourceLink);
        if (guestRescueImageBlob) {
            formData.append('image_file', guestRescueImageBlob, 'rescue.jpg');
        }

        const res = await fetch('/api/public/rescue-requests', {
            method: 'POST',
            body: formData,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        window.toast?.success('Đã gửi yêu cầu cứu hộ thành công. Admin sẽ kiểm tra ngay.');
        if (window.rescueFormModal) window.rescueFormModal.hide();
        nameEl.value = '';
        phoneEl.value = '';
        noteEl.value = '';
        if (provinceEl) provinceEl.value = '';
        if (sourceLinkEl) sourceLinkEl.value = '';
        const defaultTypeEl = document.getElementById('guest-rescue-type-emergency');
        if (defaultTypeEl) {
            defaultTypeEl.checked = true;
            defaultTypeEl.dispatchEvent(new Event('change'));
        }
        const otherInput = document.getElementById('guest-rescue-other-input');
        if (otherInput) otherInput.value = '';
        if (searchAddressEl) searchAddressEl.value = '';
        const manualAddressEl = document.getElementById('guest-rescue-address-manual');
        if (manualAddressEl) manualAddressEl.value = '';
        guestRescueImageBlob = null;
        if (imagePreview) {
            imagePreview.src = '';
        }
        if (guestRescueImagePreviewUrl) {
            URL.revokeObjectURL(guestRescueImagePreviewUrl);
            guestRescueImagePreviewUrl = null;
        }
        if (imagePreviewWrap) {
            imagePreviewWrap.style.display = 'none';
        }
        if (imageInput) {
            imageInput.value = '';
        }
    } catch (e) {
        console.error('submitGuestRescueRequest error:', e);
        window.toast?.error('Gửi yêu cầu thất bại, vui lòng thử lại.');
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = oldHtml;
    }
}

// =====================================================
// RESCUE MARKER MANAGEMENT
// =====================================================

function setupMarkerLayerControls() {
    const layerStation = document.getElementById('layer-station');
    const layerRescue = document.getElementById('layer-rescue');

    if (layerStation) {
        layerStation.addEventListener('change', () => {
            showStationMarkers = layerStation.checked;
            toggleStationMarkersDisplay();
            updateUIVisibilityBasedOnLayers();
        });
    }

    if (layerRescue) {
        layerRescue.addEventListener('change', () => {
            showRescueMarkers = layerRescue.checked;
            toggleRescueMarkersDisplay();
            updateUIVisibilityBasedOnLayers();
        });
    }

    // Mặc định bật cả 2
    showStationMarkers = true;
    showRescueMarkers = true;
    if (layerStation) layerStation.checked = true;
    if (layerRescue) layerRescue.checked = true;

    toggleStationMarkersDisplay();
    toggleRescueMarkersDisplay();
    updateUIVisibilityBasedOnLayers();
}

function updateUIVisibilityBasedOnLayers() {
    const stationSidebar = document.getElementById('station-list-sidebar');
    const detailSidebar = document.getElementById('detail-sidebar');
    const chartsPanel = document.getElementById('charts-panel');
    const longtermOverlay = document.getElementById('longterm-overlay');
    const alertBanner = document.getElementById('alert-banner');

    // Nếu chỉ xem phần cứu hộ, ẩn các info trạm
    if (!showStationMarkers && showRescueMarkers) {
        if (stationSidebar) {
            stationSidebar.classList.add('hidden');
            stationSidebar.classList.add('force-hidden');
        }

        if (detailSidebar) detailSidebar.classList.remove('active');
        if (chartsPanel) chartsPanel.classList.remove('active');
        if (longtermOverlay) longtermOverlay.classList.remove('active');
        if (alertBanner) alertBanner.classList.remove('show', 'level-warning', 'level-critical');

        document.body.classList.add('rescue-mode-active');
    } else {
        if (stationSidebar) {
            stationSidebar.classList.remove('force-hidden');
        }
        document.body.classList.remove('rescue-mode-active');
    }
}

function getLeafletMap() {
    if (map && typeof map.addLayer === 'function') return map;
    if (window.map && typeof window.map.addLayer === 'function') return window.map;
    return null;
}

function toggleStationMarkersDisplay() {
    Object.values(markers).forEach(marker => {
        const leafletMap = getLeafletMap();
        if (leafletMap) {
            if (showStationMarkers) {
                marker.addTo(leafletMap);
            } else {
                leafletMap.removeLayer(marker);
            }
        }
    });

    Object.values(corsBaseMarkers).forEach(marker => {
        const leafletMap = getLeafletMap();
        if (leafletMap) {
            if (showStationMarkers) {
                marker.addTo(leafletMap);
            } else {
                leafletMap.removeLayer(marker);
            }
        }
    });
}

function toggleRescueMarkersDisplay() {
    Object.values(rescueMarkers).forEach(marker => {
        const leafletMap = getLeafletMap();
        if (leafletMap) {
            if (showRescueMarkers) {
                marker.addTo(leafletMap);
            } else {
                leafletMap.removeLayer(marker);
            }
        }
    });
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function normalizeCorsBaseStations(payload) {
    const rawStations = Array.isArray(payload)
        ? payload
        : (Array.isArray(payload?.value) ? payload.value : []);

    // Base stations: show all valid ones from CORS API
    return rawStations
        .filter(st => st && typeof st === "object" && String(st.name || '').trim())
        .map(st => ({
            ...st,
            name: String(st.name || '').trim(),
            lat: Number(st.lat),
            lon: Number(st.lon),
        }))
        .filter(st => Number.isFinite(st.lat) && Number.isFinite(st.lon));
}

async function loadCorsBaseStations() {
    try {
        const res = await fetch('/api/public/cors-base-stations', { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const payload = await res.json();
        const stations = normalizeCorsBaseStations(payload);
        const activeNames = new Set(stations.map(st => st.name));

        Object.entries(corsBaseMarkers).forEach(([name, marker]) => {
            if (!activeNames.has(name)) {
                const leafletMap = getLeafletMap();
                if (leafletMap) leafletMap.removeLayer(marker);
                delete corsBaseMarkers[name];
            }
        });

        stations.forEach(addOrUpdateCorsBaseMarker);
        console.log(`[CORS-BASE] Loaded ${stations.length} base station marker(s)`, stations.map(st => st.name));
    } catch (error) {
        console.warn('[CORS-BASE] load error:', error);
    }
}

function addOrUpdateCorsBaseMarker(station) {
    if (!station?.name || !Number.isFinite(station.lat) || !Number.isFinite(station.lon)) return;

    const isConnected = station.ntrip_connected || station.stream_active;
    const fill = isConnected ? '#0ea5e9' : '#64748b';
    const glow = isConnected ? 'rgba(14, 165, 233, 0.55)' : 'rgba(100, 116, 139, 0.45)';
    const safeName = escapeHtml(station.name);
    const safeStatus = escapeHtml(station.status || 'unknown');
    const safeMountpoint = escapeHtml(station.mountpoint || station.name);

    const icon = L.divIcon({
        className: 'custom-cors-base-marker',
        html: `
            <div title="${safeName}" style="
                width: 0;
                height: 0;
                border-left: 13px solid transparent;
                border-right: 13px solid transparent;
                border-bottom: 24px solid ${fill};
                filter: drop-shadow(0 0 8px ${glow});
                position: relative;
            ">
                <div style="
                    position: absolute;
                    left: -9px;
                    top: 8px;
                    width: 18px;
                    height: 18px;
                    color: white;
                    font-size: 11px;
                    font-weight: 800;
                    line-height: 18px;
                    text-align: center;
                ">B</div>
            </div>
        `,
        iconSize: [26, 24],
        iconAnchor: [13, 18],
        popupAnchor: [0, -18],
    });

    const popupContent = `
        <div style="
            min-width: 230px;
            overflow: hidden;
            border-radius: 10px;
            background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
            color: #0f172a;
            font-size: 13px;
            line-height: 1.45;
            box-shadow: 0 12px 28px rgba(15, 23, 42, 0.18);
        ">
            <div style="
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 10px 12px;
                color: #0369a1;
                font-weight: 800;
                border-bottom: 1px solid #e2e8f0;
            ">
                <span style="color:#0ea5e9;"><i class="bi bi-triangle-fill"></i></span>
                <span>${safeName}</span>
            </div>
            <div style="padding: 10px 12px; display: grid; gap: 7px;">
                <div style="display:flex;justify-content:space-between;gap:14px;">
                    <span style="color:#64748b;">Name</span><strong>${safeName}</strong>
                </div>
                <div style="display:flex;justify-content:space-between;gap:14px;">
                    <span style="color:#64748b;">Lat</span><code style="color:#0f172a;">${station.lat.toFixed(9)}</code>
                </div>
                <div style="display:flex;justify-content:space-between;gap:14px;">
                    <span style="color:#64748b;">Lon</span><code style="color:#0f172a;">${station.lon.toFixed(9)}</code>
                </div>
                <div style="display:flex;justify-content:space-between;gap:14px;">
                    <span style="color:#64748b;">Mountpoint</span><strong>${safeMountpoint}</strong>
                </div>
                <div style="display:flex;justify-content:space-between;gap:14px;align-items:center;">
                    <span style="color:#64748b;">NTRIP</span>
                    <span style="
                        padding: 2px 8px;
                        border-radius: 999px;
                        background: ${isConnected ? '#dcfce7' : '#f1f5f9'};
                        color: ${isConnected ? '#166534' : '#475569'};
                        font-weight: 700;
                    ">${isConnected ? 'connected' : safeStatus}</span>
                </div>
            </div>
        </div>
    `;

    if (corsBaseMarkers[station.name]) {
        corsBaseMarkers[station.name]
            .setLatLng([station.lat, station.lon])
            .setIcon(icon)
            .bindTooltip(safeName, { direction: 'top', offset: [0, -18] })
            .bindPopup(popupContent, { maxWidth: 300 });
        return;
    }

    const marker = L.marker([station.lat, station.lon], { icon, zIndexOffset: 300 })
        .bindTooltip(safeName, { direction: 'top', offset: [0, -18] })
        .bindPopup(popupContent, { maxWidth: 300 });

    const leafletMap = getLeafletMap();
    if (showStationMarkers && leafletMap) {
        marker.addTo(leafletMap);
    }

    corsBaseMarkers[station.name] = marker;
}

async function loadRescueMarkers() {
    try {
        const userRole = window.authManager?.getUserInfo?.()?.role;
        if (!window.authManager || !window.authManager.isAuthenticated() || userRole !== 'admin') {
            Object.values(rescueMarkers).forEach(marker => {
                const leafletMap = getLeafletMap();
                if (leafletMap) leafletMap.removeLayer(marker);
            });
            rescueMarkers = {};
            rescueRequestsData = [];
            return; // Rescue markers are admin-only
        }

        const res = await window.authManager.apiFetch('/api/admin/rescue-requests?limit=100');
        if (!res || !res.ok) return;

        const requests = await res.json();
        if (!Array.isArray(requests)) return;

        rescueRequestsData = requests;
        // Remove old markers
        Object.values(rescueMarkers).forEach(marker => {
            if (window.map) window.map.removeLayer(marker);
        });
        rescueMarkers = {};

        // Add new markers for each rescue request
        requests.forEach(req => {
            if (req.latitude && req.longitude && req.status === 'pending') {
                addRescueMarker(req);
            }
        });
    } catch (error) {
        console.warn('[MAP] loadRescueMarkers error:', error);
    }
}

function addRescueMarker(rescueRequest) {
    const {
        id,
        latitude,
        longitude,
        requester_name,
        phone,
        message,
        accuracy_m,
        created_at,
        rescue_type,
        province_city,
        source_link,
        image_url,
        image_data_url,
    } = rescueRequest;
    if (!id || !latitude || !longitude) return;

    const safeSourceLink = /^https?:\/\//i.test(String(source_link || '').trim())
        ? String(source_link).trim()
        : '';

    const icon = L.divIcon({
        className: 'custom-rescue-marker',
        html: `<div style="
            width: 24px; height: 24px;
            background: #dc3545;
            border-radius: 50%;
            border: 3px solid white;
            box-shadow: 0 0 12px rgba(220, 53, 69, 0.7);
            display: flex; align-items: center; justify-content: center;
            font-size: 14px; color: white; font-weight: bold;
        "><i class="bi bi-exclamation-fill" style="font-size: 12px;"></i></div>`,
        iconSize: [24, 24],
        iconAnchor: [12, 12]
    });

    const marker = L.marker([latitude, longitude], { icon })
        .bindTooltip(`${requester_name || 'SOS'} - ${phone || 'N/A'}`, {
            direction: 'top',
            offset: [0, -15],
            permanent: false
        });

    // An toàn thêm marker thay vì addLayer(null)
    const leafletMap = getLeafletMap();
    if (showRescueMarkers && leafletMap) {
        marker.addTo(leafletMap);
    }

    const popupContent = `
        <div class="rescue-popup" style="min-width: 280px;">
            <h6 style="margin: 0 0 10px 0; color: #dc3545;">
                <i class="bi bi-exclamation-circle me-1"></i>Yêu cầu cứu hộ
            </h6>
            <div style="font-size: 13px; line-height: 1.6;">
                <div><strong>ID:</strong> #${id}</div>
                <div><strong>Người yêu cầu:</strong> ${requester_name || '(Không có)'}</div>
                <div><strong>Số điện thoại:</strong> ${phone || '(Không có)'}</div>
                <div><strong>Phân loại:</strong> ${rescue_type || '(Không có)'}</div>
                <div><strong>Tỉnh/TP:</strong> ${province_city || '(Không có)'}</div>
                <div><strong>Vị trí:</strong> ${latitude.toFixed(6)}, ${longitude.toFixed(6)}</div>
                ${accuracy_m ? `<div><strong>Độ chính xác:</strong> ±${accuracy_m}m</div>` : ''}
                <div><strong>Thời gian:</strong> ${new Date(created_at).toLocaleString('vi-VN')}</div>
                ${safeSourceLink ? `<div><strong>Nguồn:</strong> <a href="${safeSourceLink}" target="_blank" rel="noopener">Mở link</a></div>` : ''}
                <div style="margin-top: 8px; padding: 8px; background: #f8f9fa; border-radius: 4px;">
                    <strong style="font-size: 12px;">Tình trạng:</strong>
                    <div style="font-size: 13px; margin-top: 4px; word-wrap: break-word;">
                        ${message || '(Không có mô tả)'}
                    </div>
                </div>
                ${(image_url || image_data_url) ? `<div style="margin-top:8px;"><img src="${image_url || image_data_url}" alt="evidence" style="width:100%;max-height:180px;object-fit:cover;border-radius:6px;border:1px solid #ddd;"></div>` : ''}
                <div style="margin-top: 15px;">
                    <a href="https://www.google.com/maps/dir/?api=1&destination=${latitude},${longitude}"
                       target="_blank" rel="noopener"
                       class="btn btn-sm btn-primary w-100 shadow-sm" style="font-size: 13px; font-weight: 600; border-radius: 6px;">
                       <i class="bi bi-geo-alt-fill me-1"></i>Chỉ đường (Google Maps)
                    </a>
                </div>
            </div>
        </div>
    `;

    marker.bindPopup(popupContent, { maxWidth: 300, maxHeight: 400 });
    marker.on('click', () => {
        marker.openPopup();
    });

    rescueMarkers[id] = marker;
}

function updateRescueMarkerFromWebSocket(message) {
    if (message.type !== 'rescue_request') return;

    if (message.status === 'pending') {
        addRescueMarker(message);
        // Only push to data array if it doesn't exist
        if (!rescueRequestsData.some(r => r.id === message.id)) {
            rescueRequestsData.push(message);
        }
    } else {
        if (message.id && rescueMarkers[message.id]) {
            const leafletMap = getLeafletMap();
            if (leafletMap) leafletMap.removeLayer(rescueMarkers[message.id]);
            delete rescueMarkers[message.id];
        }
    }
}

function setupEventListeners() {
    console.log('🔧 [MAP] Setting up event listeners...');

    const hamburgerBtn = document.getElementById('navbar-hamburger-btn');
    const sidebarCloseTab = document.getElementById('sidebar-close-tab');
    const stationSidebar = document.getElementById('station-list-sidebar');

    // Hamburger → Toggle sidebar trái
    if (hamburgerBtn && stationSidebar) {
        hamburgerBtn.addEventListener('click', () => {
            if (currentMapMode === 'rescue') return;
            const isHidden = stationSidebar.classList.contains('hidden') || stationSidebar.classList.contains('force-hidden');
            if (isHidden) {
                stationSidebar.classList.remove('hidden');
                stationSidebar.classList.remove('force-hidden');
            } else {
                stationSidebar.classList.add('hidden');
            }
        });
    }

    if (sidebarCloseTab && stationSidebar) {
        sidebarCloseTab.addEventListener('click', () => {
            stationSidebar.classList.add('hidden');
        });
    }

    // === Layer Toggle Switch Logic ===
    const layerModeToggle = document.getElementById('layer-mode-toggle');
    const layerStationCb = document.getElementById('layer-station');
    const layerRescueCb = document.getElementById('layer-rescue');
    if (layerModeToggle && layerStationCb && layerRescueCb) {
        layerModeToggle.addEventListener('change', () => {
            if (layerModeToggle.checked) {
                // Rescue-only mode
                layerStationCb.checked = false;
                layerRescueCb.checked = true;
            } else {
                // Station mode (default: both on)
                layerStationCb.checked = true;
                layerRescueCb.checked = true;
            }
            layerStationCb.dispatchEvent(new Event('change'));
            layerRescueCb.dispatchEvent(new Event('change'));
        });
    }

    // === Custom Glass Zoom Controls ===
    const zoomInBtn = document.getElementById('map-zoom-in');
    const zoomOutBtn = document.getElementById('map-zoom-out');
    if (zoomInBtn && map) {
        zoomInBtn.addEventListener('click', () => map.zoomIn());
    }
    if (zoomOutBtn && map) {
        zoomOutBtn.addEventListener('click', () => map.zoomOut());
    }

    // Đóng detailed sidebar
    const closeDetailBtn = document.getElementById('close-btn');
    const detailSidebar = document.getElementById('detail-sidebar');

    if (closeDetailBtn && detailSidebar) {
        closeDetailBtn.addEventListener('click', () => {
            detailSidebar.classList.remove('active');

            // Đóng tất cả panels
            const chartsPanel = document.getElementById('charts-panel');
            const longtermOverlay = document.getElementById('longterm-overlay');
            const advSidepanel = document.getElementById('gnss-advanced-sidepanel');
            if (chartsPanel) chartsPanel.classList.remove('active');
            if (longtermOverlay) longtermOverlay.classList.remove('active');
            if (advSidepanel) advSidepanel.classList.remove('active');

            // Mở lại sidebar trái
            if (stationSidebar && currentMapMode !== 'rescue') {
                stationSidebar.classList.remove('hidden');
                stationSidebar.classList.remove('force-hidden');
            }
        });
    }

    // Theme toggle - handled by theme-manager.js (do NOT add duplicate listener)

    // Search
    const searchInput = document.getElementById('search-station');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            filterStations(e.target.value);
        });
    }

    // ✅ NEW: Xem biểu đồ - Mở panel giữa màn hình
    const btnShowCharts = document.getElementById('btn-show-charts');
    const chartsPanel = document.getElementById('charts-panel');
    const closeChartsBtn = document.getElementById('close-charts-btn');

    if (btnShowCharts && chartsPanel) {
        btnShowCharts.addEventListener('click', () => {
            chartsPanel.classList.add('active');

            // Close advanced gnss panel if open
            const advSidepanel = document.getElementById('gnss-advanced-sidepanel');
            if (advSidepanel) advSidepanel.classList.remove('active');

            // Đóng sidebar trái khi mở biểu đồ
            if (stationSidebar) {
                stationSidebar.classList.add('hidden');
                stationSidebar.classList.add('force-hidden');
            }

            console.log('📊 [CHARTS] Charts panel opened');

            if (currentStationData) {
                renderCharts(currentStationData);
            }
        });
    }



    // ✅ NEW: Mở Digital Twin 3D
    const btnDigitalTwin = document.getElementById('btn-digital-twin');
    if (btnDigitalTwin) {
        btnDigitalTwin.addEventListener('click', () => {
            if (currentStationData) {
                console.log('🌋 [DIGITAL TWIN] Opening for station:', currentStationData.id);
                const rainData = currentStationData.sensors && currentStationData.sensors.rain && currentStationData.sensors.rain.latest ? currentStationData.sensors.rain.latest.data : null;
                const h24 = rainData ? (rainData.rain_24h || rainData.rain_last_24h || rainData.value || 0) : 0;
                window.openDigitalTwin({
                    id: currentStationData.id,
                    rain: { h24: parseFloat(h24) }
                });
            } else {
                window.openDigitalTwin(null);
            }
        });
    }

    // Advanced GNSS Sidepanel
    const gnssCard = document.getElementById('sensor-card-gnss');
    const advSidepanel = document.getElementById('gnss-advanced-sidepanel');
    const advCloseBtn = document.getElementById('gnss-sidepanel-close');

    if (gnssCard && advSidepanel) {
        console.log('✅ [GNSS] Advanced sidepanel listener attached');
        gnssCard.addEventListener('click', (e) => {
            e.stopPropagation();
            console.log('👆 [GNSS] GNSS Velocity card clicked');
            // Remove expanded mode when just opening from card
            advSidepanel.classList.remove('expanded');
            advSidepanel.classList.toggle('active');
            const isActive = advSidepanel.classList.contains('active');

            // ✅ ĐỒNG BỘ: Đóng Station Sidebar khi mở Advanced GNSS
            if (isActive && stationSidebar) {
                stationSidebar.classList.add('hidden');
                loadLongTermAnalysis(); // Tải Theil-Sen vào cột trái
            }

            console.log('✨ [GNSS] Sidepanel active:', isActive);
        });
    } else {
        console.warn('⚠️ [GNSS] Could not find gnssCard or advSidepanel', { gnssCard: !!gnssCard, advSidepanel: !!advSidepanel });
    }

    if (advCloseBtn && advSidepanel) {
        advCloseBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            advSidepanel.classList.remove('active');
            advSidepanel.classList.remove('expanded');
            const advColRight = advSidepanel.querySelector('.adv-column-right');
            if (advColRight) advColRight.style.display = 'none';
        });
    }

    if (closeChartsBtn && chartsPanel) {
        closeChartsBtn.addEventListener('click', () => {
            chartsPanel.classList.remove('active');

            // Chỉ bỏ force-hidden, giữ hidden (sidebar vẫn đóng)
            if (stationSidebar && currentMapMode !== 'rescue') {
                stationSidebar.classList.remove('force-hidden');
            }

            console.log('📊 [CHARTS] Charts panel closed');
        });
    }

    const btnToggleImu3d = document.getElementById('btn-toggle-imu-3d');
    const chartImuWrapper = document.getElementById('chart-imu-wrapper');
    const realtimeImu3dWrapper = document.getElementById('realtime-imu-3d-wrapper');

    if (btnToggleImu3d && chartImuWrapper && realtimeImu3dWrapper) {
        btnToggleImu3d.addEventListener('click', () => {
            realtimeImuActive = !realtimeImuActive;
            if (realtimeImuActive) {
                chartImuWrapper.style.display = 'none';
                realtimeImu3dWrapper.style.display = 'block';
                btnToggleImu3d.innerHTML = '<i class="bi bi-graph-up me-1"></i>2D Chart';
                // Always re-init 3D scene when toggling on to ensure proper sizing
                if (currentStationData && currentStationData.sensors && currentStationData.sensors.imu) {
                    const latest = currentStationData.sensors.imu.latest;
                    if (latest) {
                        // Small delay to let display:block take effect
                        setTimeout(() => {
                            initRealtimeIMU3D(latest.roll || 0, latest.pitch || 0);
                        }, 50);
                    }
                }
            } else {
                realtimeImu3dWrapper.style.display = 'none';
                chartImuWrapper.style.display = 'block';
                btnToggleImu3d.innerHTML = '<i class="bi bi-box me-1"></i>3D View';
                // Cleanup realtime scene on hide
                if (realtimeImuAnimationId) cancelAnimationFrame(realtimeImuAnimationId);
                realtimeImuScene = null;
                realtimeImuRenderer = null;
            }
        });
    }

    // Analysis / Theil-Sen button -> Mở Advanced tab (Chỉ hiển thị Theil-sen, ẩn Bình sai)
    const btnLongTerm = document.getElementById('btn-long-term');
    const longtermOverlay = document.getElementById('longterm-overlay');
    const closeLongtermBtn = document.getElementById('close-longterm-btn');

    if (btnLongTerm && advSidepanel) {
        btnLongTerm.addEventListener('click', () => {
            advSidepanel.classList.remove('expanded');
            advSidepanel.classList.add('active');

            // Đóng sidebar trái
            if (stationSidebar) {
                stationSidebar.classList.add('hidden');
                stationSidebar.classList.add('force-hidden');
            }

            // Cập nhật tên trạm
            const longtermStationName = document.getElementById('longterm-station-name');
            if (longtermStationName && currentStationData) {
                longtermStationName.textContent = `${currentStationData.name} (${currentStationData.station_code})`;
            }

            console.log('📊 [LONGTERM] Analysis overlay opened');

            loadLongTermAnalysis();
        });
    }

    const btnNetworkAdj = document.getElementById('btn-network-adj');
    if (btnNetworkAdj && advSidepanel) {
        btnNetworkAdj.addEventListener('click', () => {
            // Check for offline rovers
            let hasOffline = false;
            if (typeof stationsData !== 'undefined' && Array.isArray(stationsData)) {
                hasOffline = stationsData.some(st => st.status === 'offline' || st.is_offline);
            }
            
            if (hasOffline) {
                const proceed = confirm("Có trạm rover offline, bạn có muốn tiếp tục bình sai không? (Có/Không)");
                if (!proceed) return;
            }

            // Open and Expand Advanced Sidepanel
            advSidepanel.classList.add('active');
            
            // Expand to show right column
            const advColRight = advSidepanel.querySelector('.adv-column-right');
            if (advColRight) {
                advColRight.style.display = 'flex';
                advSidepanel.classList.add('expanded');
            }

            
            // Close left sidebar
            if (stationSidebar) {
                stationSidebar.classList.add('hidden');
                stationSidebar.classList.add('force-hidden');
            }
            
            // Trigger adjustment request
            if (typeof requestGnssAdjustment === 'function') {
                requestGnssAdjustment(currentStationData?.project_id);
            }
        });
    }

    // Quản lý trạng thái vẽ Canvas
    window.gnssBoardState = {
        canvas: null,
        ctx: null,
        points: {},
        baselines: [],
        basePoint: null,
        init() {
            this.canvas = document.getElementById('gnss-board-canvas');
            if (!this.canvas) return;
            const container = document.getElementById('gnss-board-container');
            this.canvas.width = container.clientWidth;
            this.canvas.height = container.clientHeight;
            this.ctx = this.canvas.getContext('2d');
            this.points = {};
            this.baselines = [];
            this.basePoint = null;
            document.getElementById('gnss-baseline-table-body').innerHTML = '';
            if (!gnssAdjustmentDebugState.active) {
                gnssAdjustmentDebugState.phase = 'WAITING';
            }
            refreshGnssAdjustmentDebugUi();
            document.getElementById('adj-results-section').style.display = 'none';
            document.getElementById('gnss-board-tooltips').innerHTML = '';
            this.draw();
        },
        addPoint(name, relX, relY, isBase = false) {
            if (!this.points[name]) {
                this.points[name] = { name, x: relX, y: relY, isBase };
                if (isBase) this.basePoint = this.points[name];
                this.draw();
            }
        },
        addBaseline(from, to, data) {
            this.baselines.push({ from, to, data });
            this.draw();
            
            // Add row to table
            const tbody = document.getElementById('gnss-baseline-table-body');
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${this.baselines.length}</td>
                <td class="text-info">${from}</td>
                <td class="text-warning">${to}</td>
                <td>${data.dn.toFixed(4)}</td>
                <td>${data.de.toFixed(4)}</td>
                <td>${data.dh.toFixed(4)}</td>
                <td><button class="btn btn-xs btn-outline-secondary py-0 view-adv-btn" data-json='${JSON.stringify(data.full_data || {}).replace(/'/g, "&#39;")}'>Chi tiết</button></td>
            `;
            tbody.appendChild(row);
            
            // Rebind advanced view buttons
            document.querySelectorAll('.view-adv-btn').forEach(btn => {
                btn.onclick = function() {
                    const jsonStr = this.getAttribute('data-json');
                    try {
                        const jsonObj = JSON.parse(jsonStr);
                        document.getElementById('gnss-advanced-data-json').textContent = JSON.stringify(jsonObj, null, 2);
                        new bootstrap.Modal(document.getElementById('gnssAdvancedDataModal')).show();
                    } catch(e) {}
                };
            });
            
            // Add tooltip
            if (this.points[from] && this.points[to]) {
                const pt1 = this.getScreenCoords(this.points[from]);
                const pt2 = this.getScreenCoords(this.points[to]);
                const midX = (pt1.x + pt2.x) / 2;
                const midY = (pt1.y + pt2.y) / 2;
                const tooltipsContainer = document.getElementById('gnss-board-tooltips');
                const t = document.createElement('div');
                t.style.position = 'absolute';
                t.style.left = (midX + 5) + 'px';
                t.style.top = (midY - 10) + 'px';
                t.style.backgroundColor = 'rgba(0,0,0,0.7)';
                t.style.color = '#fff';
                t.style.padding = '2px 6px';
                t.style.fontSize = '10px';
                t.style.borderRadius = '3px';
                t.style.fontFamily = 'monospace';
                t.innerHTML = `dN:${data.dn.toFixed(3)}<br>dE:${data.de.toFixed(3)}`;
                tooltipsContainer.appendChild(t);
            }
        },
        getScreenCoords(pt) {
            const values = Object.values(this.points);
            const minX = Math.min(...values.map(item => item.x), 0);
            const maxX = Math.max(...values.map(item => item.x), 0);
            const minY = Math.min(...values.map(item => item.y), 0);
            const maxY = Math.max(...values.map(item => item.y), 0);
            const padding = 70;
            const rangeX = Math.max(maxX - minX, 1);
            const rangeY = Math.max(maxY - minY, 1);
            const scale = Math.max(0.01, Math.min(
                (this.canvas.width - padding * 2) / rangeX,
                (this.canvas.height - padding * 2) / rangeY,
            ));
            const centerX = this.canvas.width / 2 - ((minX + maxX) / 2) * scale;
            const centerY = this.canvas.height / 2 + ((minY + maxY) / 2) * scale;
            return {
                x: centerX + (pt.x * scale),
                y: centerY - (pt.y * scale),
            };
        },
        loadAdjustmentResult(result) {
            if (!this.ctx || !result?.points) return;
            this.points = {};
            this.baselines = [];
            this.basePoint = null;
            const tbody = document.getElementById('gnss-baseline-table-body');
            const tooltips = document.getElementById('gnss-board-tooltips');
            if (tbody) tbody.innerHTML = '';
            if (tooltips) tooltips.innerHTML = '';

            const resultBaselines = Array.isArray(result.baselines) ? result.baselines : [];
            let baseXYZ = result.base?.ecef_xyz;
            if (!Array.isArray(baseXYZ)) {
                const seed = resultBaselines.find(item => item.from === 'BASE' && result.points[item.to]);
                const target = seed ? getAdjustedPointCoordinates(result.points[seed.to]) : null;
                const vector = seed?.adjusted_xyz || seed?.adjusted_neu || seed?.observed_xyz || seed?.observed_neu;
                if (target?.length >= 3 && Array.isArray(vector)) {
                    baseXYZ = target.map((value, index) => Number(value) - Number(vector[index] || 0));
                }
            }
            if (!Array.isArray(baseXYZ)) {
                baseXYZ = getAdjustedPointCoordinates(Object.values(result.points)[0]);
            }
            baseXYZ = Array.isArray(baseXYZ) ? baseXYZ.map(Number) : [0, 0, 0];
            this.addPoint('BASE', 0, 0, true);
            Object.entries(result.points).forEach(([name, point]) => {
                const coordinate = getAdjustedPointCoordinates(point).map(Number);
                if (coordinate.length >= 2 && coordinate.every(Number.isFinite)) {
                    this.addPoint(name, coordinate[1] - baseXYZ[1], coordinate[0] - baseXYZ[0], false);
                }
            });
            resultBaselines.forEach(item => {
                const vector = item.adjusted_xyz || item.adjusted_neu || item.observed_xyz || item.observed_neu;
                if (!Array.isArray(vector) || vector.length < 3) return;
                this.addBaseline(item.from, item.to, {
                    dn: Number(vector[0]) || 0,
                    de: Number(vector[1]) || 0,
                    dh: Number(vector[2]) || 0,
                    full_data: item,
                });
            });
            this.draw();
        },
        draw() {
            if (!this.ctx) return;
            this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
            
            // Draw grid
            this.ctx.strokeStyle = '#e0e0e0';
            this.ctx.lineWidth = 1;
            for(let i=0; i<this.canvas.width; i+=50) {
                this.ctx.beginPath(); this.ctx.moveTo(i, 0); this.ctx.lineTo(i, this.canvas.height); this.ctx.stroke();
            }
            for(let i=0; i<this.canvas.height; i+=50) {
                this.ctx.beginPath(); this.ctx.moveTo(0, i); this.ctx.lineTo(this.canvas.width, i); this.ctx.stroke();
            }

            if (Object.keys(this.points).length === 0) {
                this.ctx.fillStyle = '#64748b';
                this.ctx.font = '16px monospace';
                this.ctx.textAlign = 'center';
                this.ctx.fillText('Đang chờ dữ liệu baseline để dựng mạng GNSS…', this.canvas.width / 2, this.canvas.height / 2);
                this.ctx.textAlign = 'start';
                return;
            }

            // Draw baselines
            this.baselines.forEach(b => {
                const p1 = this.points[b.from];
                const p2 = this.points[b.to];
                if (p1 && p2) {
                    const sp1 = this.getScreenCoords(p1);
                    const sp2 = this.getScreenCoords(p2);
                    this.ctx.beginPath();
                    this.ctx.moveTo(sp1.x, sp1.y);
                    this.ctx.lineTo(sp2.x, sp2.y);
                    this.ctx.strokeStyle = '#0d6efd';
                    this.ctx.lineWidth = 2;
                    this.ctx.stroke();
                }
            });

            // Draw points
            Object.values(this.points).forEach(pt => {
                const sp = this.getScreenCoords(pt);
                this.ctx.beginPath();
                this.ctx.arc(sp.x, sp.y, pt.isBase ? 8 : 6, 0, 2 * Math.PI);
                this.ctx.fillStyle = pt.isBase ? '#dc3545' : '#198754';
                this.ctx.fill();
                this.ctx.strokeStyle = '#fff';
                this.ctx.lineWidth = 2;
                this.ctx.stroke();
                
                this.ctx.fillStyle = '#000';
                this.ctx.font = 'bold 12px Arial';
                this.ctx.fillText(pt.name, sp.x + 10, sp.y - 10);
            });
        }
    };

    // Lệnh Bình sai - Trigger API start gnss adjustment
    function ensureGnssTerminalModal() {
        let modal = document.getElementById('gnssTerminalModal');
        if (modal) return modal;

        const wrapper = document.createElement('div');
        wrapper.innerHTML = `
            <div class="modal fade" id="gnssTerminalModal" tabindex="-1">
                <div class="modal-dialog modal-xl modal-dialog-centered" style="max-width: 95vw;">
                    <div class="modal-content bg-dark text-light border-primary" style="height: 85vh;">
                        <div class="modal-header border-bottom border-secondary py-2">
                            <h5 class="modal-title text-primary font-monospace" style="font-size: 1.1rem;">
                                <i class="bi bi-cpu me-2"></i>GNSS Agent Calculation Board (Real-time)
                            </h5>
                            <div id="gnss-phase-indicator" class="ms-4 text-warning fw-bold font-monospace">Phase: WAITING</div>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body p-0 d-flex flex-row" style="height: calc(100% - 60px); overflow: hidden;">
                            <div class="position-relative" style="background-color: #f8f9fa; overflow: hidden; min-width: 280px; width: 0; flex: 1 1 0;" id="gnss-board-container">
                                <canvas id="gnss-board-canvas" style="width: 100%; height: 100%; display: block;"></canvas>
                                <div id="gnss-board-tooltips" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;"></div>
                            </div>
                            <div id="gnss-column-resizer" title="Kéo để đổi chiều rộng bảng dữ liệu" style="flex: 0 0 7px; cursor: col-resize; background: #374151; border-left: 1px solid #111827; border-right: 1px solid #64748b; touch-action: none;"></div>
                            <div id="gnss-data-column" class="d-flex flex-column" style="width: 520px; flex: 0 0 520px; min-width: 380px; max-width: 75vw; background-color: #1e1e1e; overflow: hidden;">
                                <div class="p-2 border-bottom border-secondary bg-black">
                                    <h6 class="mb-0 text-info font-monospace"><i class="bi bi-table me-1"></i>Baseline Vectors</h6>
                                </div>
                                 <div class="flex-grow-1" style="overflow: auto; min-height: 100px;" id="gnss-data-panel">
                                    <table class="table table-dark table-sm table-hover font-monospace mb-0" style="font-size: 0.75rem; white-space: nowrap;">
                                        <thead>
                                            <tr class="text-secondary">
                                                <th>#</th>
                                                <th>From</th>
                                                <th>To</th>
                                                <th>dN(m)</th>
                                                <th>dE(m)</th>
                                                <th>dH(m)</th>
                                                <th></th>
                                            </tr>
                                        </thead>
                                        <tbody id="gnss-baseline-table-body"></tbody>
                                     </table>
                                 </div>
                                <div id="gnss-debug-resizer" title="Kéo để đổi chiều cao Live Debug" style="height: 7px; flex: 0 0 7px; cursor: row-resize; background: #374151; border-top: 1px solid #64748b; border-bottom: 1px solid #111827; touch-action: none;"></div>
                                <div id="gnss-debug-section" class="bg-black d-flex flex-column" style="height: 280px; flex: 0 0 280px; min-height: 160px; overflow: hidden;">
                                    <div class="d-flex justify-content-between align-items-center px-2 py-1 border-bottom border-secondary">
                                        <h6 class="mb-0 text-warning font-monospace" style="font-size: 0.75rem;"><i class="bi bi-bug me-1"></i>Live Debug</h6>
                                        <div class="d-flex gap-1">
                                            <button id="gnss-debug-copy" type="button" class="btn btn-sm btn-outline-info py-0 px-1" style="font-size: 0.65rem;" title="Sao chép toàn bộ log">Sao chép</button>
                                            <button id="gnss-debug-follow" type="button" class="btn btn-sm btn-outline-secondary py-0 px-1" style="font-size: 0.65rem;" title="Xuống cuối và tiếp tục tự cuộn">↓ Cuối</button>
                                            <button id="gnss-debug-clear" type="button" class="btn btn-sm btn-outline-secondary py-0 px-1" style="font-size: 0.65rem;">Xóa log</button>
                                        </div>
                                    </div>
                                    <div id="gnss-debug-summary" class="px-2 py-1 text-secondary font-monospace border-bottom border-secondary" style="font-size: 0.72rem; white-space: nowrap; overflow-x: auto; overflow-y: hidden; flex: 0 0 auto;">WS: CONNECTING</div>
                                    <div id="gnss-debug-log" class="p-2 font-monospace flex-grow-1" tabindex="0" style="min-height: 0; overflow: auto; scrollbar-gutter: stable; user-select: text; cursor: text; white-space: pre-wrap; overflow-wrap: break-word; word-break: normal; font-size: 0.76rem; line-height: 1.45;"></div>
                                </div>
                                <div id="adj-results-section" class="p-3 border-top border-secondary bg-black" style="display: none;">
                                    <h6 id="adj-process-status" class="mb-2"></h6>
                                    <div class="text-secondary font-monospace" style="font-size: 0.7rem;">Time: <span id="adj-val-time"></span></div>
                                    <div id="adj-points-list" class="mt-2"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `.trim();
        modal = wrapper.firstElementChild;
        document.body.appendChild(modal);
        const dataColumn = modal.querySelector('#gnss-data-column');
        const debugSection = modal.querySelector('#gnss-debug-section');
        const savedColumnWidth = Number(localStorage.getItem('gnssDataColumnWidth'));
        const savedDebugHeight = Number(localStorage.getItem('gnssDebugHeight'));
        if (savedColumnWidth >= 380) {
            dataColumn.style.width = `${savedColumnWidth}px`;
            dataColumn.style.flexBasis = `${savedColumnWidth}px`;
        }
        if (savedDebugHeight >= 160) {
            debugSection.style.height = `${savedDebugHeight}px`;
            debugSection.style.flexBasis = `${savedDebugHeight}px`;
        }

        const redrawGnssBoard = () => {
            const board = window.gnssBoardState;
            const container = modal.querySelector('#gnss-board-container');
            if (!board?.canvas || !container) return;
            board.canvas.width = container.clientWidth;
            board.canvas.height = container.clientHeight;
            board.draw?.();
        };
        const installResizer = (handle, onMove, onEnd) => {
            handle?.addEventListener('pointerdown', event => {
                event.preventDefault();
                handle.setPointerCapture?.(event.pointerId);
                document.body.style.userSelect = 'none';
                const move = moveEvent => onMove(moveEvent);
                const end = () => {
                    handle.removeEventListener('pointermove', move);
                    handle.removeEventListener('pointerup', end);
                    handle.removeEventListener('pointercancel', end);
                    document.body.style.userSelect = '';
                    onEnd?.();
                };
                handle.addEventListener('pointermove', move);
                handle.addEventListener('pointerup', end);
                handle.addEventListener('pointercancel', end);
            });
        };
        installResizer(modal.querySelector('#gnss-column-resizer'), event => {
            const bodyRect = modal.querySelector('.modal-body').getBoundingClientRect();
            const width = Math.max(380, Math.min(bodyRect.right - event.clientX, bodyRect.width * 0.75));
            dataColumn.style.width = `${width}px`;
            dataColumn.style.flexBasis = `${width}px`;
            redrawGnssBoard();
        }, () => localStorage.setItem('gnssDataColumnWidth', String(Math.round(dataColumn.getBoundingClientRect().width))));
        installResizer(modal.querySelector('#gnss-debug-resizer'), event => {
            const columnRect = dataColumn.getBoundingClientRect();
            const resultsHeight = modal.querySelector('#adj-results-section')?.offsetHeight || 0;
            const height = Math.max(160, Math.min(columnRect.bottom - event.clientY - resultsHeight, columnRect.height - 150));
            debugSection.style.height = `${height}px`;
            debugSection.style.flexBasis = `${height}px`;
        }, () => localStorage.setItem('gnssDebugHeight', String(Math.round(debugSection.getBoundingClientRect().height))));
        const debugLog = modal.querySelector('#gnss-debug-log');
        debugLog?.addEventListener('scroll', () => {
            const distanceFromBottom = debugLog.scrollHeight - debugLog.scrollTop - debugLog.clientHeight;
            gnssAdjustmentDebugState.autoScroll = distanceFromBottom <= 24;
            const followButton = modal.querySelector('#gnss-debug-follow');
            followButton?.classList.toggle('btn-warning', !gnssAdjustmentDebugState.autoScroll);
            followButton?.classList.toggle('btn-outline-secondary', gnssAdjustmentDebugState.autoScroll);
        }, { passive: true });
        modal.querySelector('#gnss-debug-copy')?.addEventListener('click', event => {
            copyGnssAdjustmentDebugOutput(event.currentTarget);
        });
        modal.querySelector('#gnss-debug-follow')?.addEventListener('click', () => {
            scrollGnssAdjustmentDebugToBottom();
        });
        modal.querySelector('#gnss-debug-clear')?.addEventListener('click', () => {
            gnssAdjustmentDebugState.entries = [];
            gnssAdjustmentDebugState.entriesRevision += 1;
            gnssAdjustmentDebugState.autoScroll = true;
            addGnssAdjustmentDebug('UI', 'Đã xóa nhật ký debug.', 'info');
        });
        refreshGnssAdjustmentDebugUi();
        return modal;
    }

    function showAdjustmentError(title, message) {
        if (window.Swal?.fire) {
            window.Swal.fire({ icon: 'error', title, text: message });
            return;
        }
        window.toast?.error?.(message);
        alert(`${title}: ${message}`);
    }

    if (!window.Swal?.fire) {
        window.Swal = {
            fire(...args) {
                const config = typeof args[0] === 'object'
                    ? args[0]
                    : { title: args[0], text: args[1] };
                const title = config.title || 'Thong bao';
                const text = config.text || config.html || '';
                window.toast?.error?.(text || title);
                alert(text ? `${title}: ${text}` : title);
            }
        };
    }

    async function readApiError(response) {
        if (!response) return 'Khong nhan duoc phan hoi tu may chu';
        try {
            const data = await response.clone().json();
            return data.detail || data.message || data.error || `HTTP ${response.status}`;
        } catch (_) {
            try {
                const text = await response.text();
                return text || `HTTP ${response.status}`;
            } catch (__) {
                return `HTTP ${response.status}`;
            }
        }
    }

        window.requestGnssAdjustment = async function(projectId, stationIds) {
        // The advanced-panel action operates on the currently selected station,
        // while the map-cluster action passes the project explicitly.
        projectId = projectId || currentStationData?.project_id;
        if (!projectId) {
            showAdjustmentError('Loi', 'Khong xac dinh duoc du an de binh sai');
            return;
        }
        
        let terminalModal;
        try {
            // Mở modal tiến trình
            const terminalModalEl = ensureGnssTerminalModal();
            if (!window.bootstrap?.Modal) {
                throw new Error('Bootstrap Modal chua san sang');
            }
            terminalModal = bootstrap.Modal.getOrCreateInstance(terminalModalEl);
            terminalModal.show();
            resetGnssAdjustmentDebug({ projectId, stationIds });
            addGnssAdjustmentDebug('API', `Đang gọi API khởi động cho dự án #${projectId}.`, 'info');
            
            // Initialize before calling the API, otherwise a very fast WebSocket
            // baseline can arrive before the canvas has a rendering context.
            await new Promise(resolve => setTimeout(resolve, 300));
            window.gnssBoardState?.init?.();

            const payload = {
                project_id: projectId,
                base_mountpoint: '',
                selected_clusters: stationIds ? [stationIds] : null
            };
            
            let res;
            if (window.authManager && window.authManager.token) {
                res = await window.authManager.apiFetch('/api/admin/gnss/adjustment/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
            } else {
                res = await fetch('/api/admin/gnss/adjustment/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!res.ok) throw new Error('Bạn cần đăng nhập với quyền Quản trị viên để thực hiện tính năng này');
            }

            if (res && !res.ok) throw new Error(await readApiError(res));
            if (!res) throw new Error('Không nhận được phản hồi từ API khởi động Bình sai');

            let startResult = {};
            try {
                startResult = await res.json();
            } catch (_) {
                startResult = {};
            }
            if (Array.isArray(startResult.expected_station_ids)) {
                gnssAdjustmentDebugState.expectedStationIds = startResult.expected_station_ids;
            }
            setGnssAdjustmentPhase(startResult.phase || 'COLLECTING_BASELINE', startResult.message || 'API đã khởi động phiên Bình sai.');
            addGnssAdjustmentDebug(
                'API',
                `HTTP ${res.status}: đang chờ ${gnssAdjustmentDebugState.expectedStationIds.length || 'các'} trạm gửi #AGRICA hợp lệ.`,
                'success',
            );
            
        } catch (error) {
            console.error('Adjustment trigger error:', error);
            setGnssAdjustmentPhase('ERROR', error.message || 'Không thể khởi động Bình sai.');
            addGnssAdjustmentDebug('API', error.message || 'Không thể khởi động Bình sai.', 'error');
            Swal.fire({
                icon: 'error',
                title: 'Lỗi khởi chạy Bình sai',
                text: error.message
            });
        }
    };

    if (closeLongtermBtn && longtermOverlay) {
        closeLongtermBtn.addEventListener('click', () => {
            longtermOverlay.classList.remove('active');
            rainCorrelationAiRunning = false;
            closeSlideModelResultPopup();

            // Chỉ bỏ force-hidden, giữ hidden (sidebar vẫn đóng)
            if (stationSidebar && currentMapMode !== 'rescue') {
                stationSidebar.classList.remove('force-hidden');
            }

            console.log('📊 [LONGTERM] Analysis overlay closed');
        });
    }

    // Time range selector buttons for long-term analysis
    const rangeSelector = document.getElementById('longterm-range-selector');
    if (rangeSelector) {
        rangeSelector.querySelectorAll('.btn').forEach(btn => {
            btn.addEventListener('click', () => {
                rangeSelector.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                loadLongTermAnalysis({ includeCorrelation: isRainCorrelationAiEnabled });
            });
        });
    }

    const runRainCorrBtn = document.getElementById('btn-run-rain-correlation');
    if (runRainCorrBtn) {
        runRainCorrBtn.addEventListener('click', async () => {
            if (rainCorrelationAiRunning) return;
            isRainCorrelationAiEnabled = true;
            rainCorrelationAiRunning = true;
            updateRainCorrelationAiControls();
            const analysisData = await loadLongTermAnalysis({ includeCorrelation: true });
            showSlideModelResultPopup(analysisData?.rainfall_correlation || null);
        });
    }

    const smModelPopupOverlay = document.getElementById('sm-model-popup-overlay');
    const smModelPopupClose = document.getElementById('sm-model-popup-close');
    const smModelPopupCloseBtn = document.getElementById('sm-model-popup-close-btn');
    const smModelPopupOkBtn = document.getElementById('sm-model-popup-ok-btn');

    [smModelPopupClose, smModelPopupCloseBtn, smModelPopupOkBtn].forEach(btn => {
        if (btn) btn.addEventListener('click', closeSlideModelResultPopup);
    });

    if (smModelPopupOverlay) {
        smModelPopupOverlay.addEventListener('click', (event) => {
            if (event.target === smModelPopupOverlay) {
                closeSlideModelResultPopup();
            }
        });
    }

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeSlideModelResultPopup();
        }
    });

    // Nút tắt/bật còi trong sidebar
    const sirenToggleBtns = document.querySelectorAll('.btn-siren-toggle');
    sirenToggleBtns.forEach(sirenToggleBtn => {
        sirenToggleBtn.addEventListener('click', async () => {
            if (!currentAlertStationId) return;
            const state = sirenToggleBtn.getAttribute('data-siren-state');
            const target = sirenToggleBtn.getAttribute('data-target') || 'all';
            if (state === 'idle') return; // disabled, không làm gì

            try {
                const iconBase = target === 'pi_center' ? 'Center' : 'Point';
                sirenToggleBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>`;

                if (state === 'alerting') {
                    // Đang kêu → Tắt còi
                    const response = await window.authManager.apiFetch(`/api/field/stations/${currentAlertStationId}/stop-siren?target=${target}`, {
                        method: 'POST'
                    });
                    if (response && response.ok) {
                        window.toast?.success(`Mute command sent (${iconBase})`);
                        setSirenButtonState('muted', target);
                        // Tắt âm thanh trên trình duyệt web khi user nhấn Mute
                        AlertSoundManager.mute();
                    } else {
                        window.toast?.error(`Failed to mute (${iconBase})`);
                        setSirenButtonState('alerting', target);
                    }
                } else if (state === 'muted') {
                    // Đã tắt → Bật lại còi
                    const response = await window.authManager.apiFetch(`/api/field/stations/${currentAlertStationId}/enable-siren?target=${target}`, {
                        method: 'POST'
                    });
                    if (response && response.ok) {
                        window.toast?.success(`Alarm re-enabled (${iconBase})`);
                        setSirenButtonState('alerting', target);
                    } else {
                        window.toast?.error(`Failed to enable (${iconBase})`);
                        setSirenButtonState('muted', target);
                    }
                }
            } catch (error) {
                console.error('Error toggling siren:', error);
                window.toast?.error('Cannot connect to server');
                // Khôi phục trạng thái cũ
                const target = sirenToggleBtn.getAttribute('data-target') || 'all';
                setSirenButtonState(state, target);
            }
        });
    });

    console.log('✅ [MAP] All event listeners setup complete');
}

// =====================================================
// OTHER FUNCTIONS
// =====================================================

function switchMapTiles(theme) {
    if (!map) return;
    const key = theme === 'dark' ? 'dark' : 'light';
    if (currentTileLayer) {
        map.removeLayer(currentTileLayer);
    }
    currentTileLayer = L.tileLayer(TILE_URLS[key], TILE_OPTIONS[key]).addTo(map);
}

function createStationClusterGroup() {
    return L.layerGroup();
}

function initMap() {
    try {
        map = L.map('map', { zoomControl: false, attributionControl: false, maxZoom: 18 }).setView([16.047079, 108.206230], 6);
        window.map = map;

        stationClusterGroup = createStationClusterGroup();
        map.addLayer(stationClusterGroup);

        const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
        switchMapTiles(currentTheme);

        // Auto-switch tiles on theme change
        window.addEventListener('themeChanged', (e) => {
            switchMapTiles(e.detail?.theme || document.documentElement.getAttribute('data-theme'));
        });

        console.log('✅ [MAP] Leaflet map initialized');
    } catch (error) {
        console.error('❌ [MAP] Failed to initialize map:', error);
    }
}

function getClusterStationTokens(clusterConfig) {
    if (Array.isArray(clusterConfig)) return clusterConfig;
    if (clusterConfig && Array.isArray(clusterConfig.stations)) return clusterConfig.stations;
    return [];
}

function findStationByClusterToken(token) {
    const tokenText = String(token).trim();
    return allStations.find(station => (
        String(station.id) === tokenText ||
        String(station.station_code || '').trim() === tokenText ||
        String(station.name || '').trim() === tokenText
    ));
}

function hasValidLatLon(location) {
    return Number.isFinite(Number(location?.lat)) && Number.isFinite(Number(location?.lon));
}

async function loadProjectsAndClusters() {
    try {
        const res = window.authManager?.isAuthenticated?.()
            ? await window.authManager.apiFetch('/api/projects')
            : await fetch('/api/projects');
        if (!res.ok) return;
        const projects = await res.json();
        
        const leafletMap = getLeafletMap();
        if (leafletMap) {
            clusterPolylines.forEach(p => leafletMap.removeLayer(p));
        }
        clusterPolylines = [];
        
        const colors = ['#10b981', '#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b'];
        let colorIdx = 0;

        projects.forEach(proj => {
            if (!proj.gnss_clusters || !Array.isArray(proj.gnss_clusters)) return;
            
            proj.gnss_clusters.forEach(c => {
                const stationTokens = getClusterStationTokens(c);
                const clusterMembers = stationTokens
                    .map(findStationByClusterToken)
                    .filter(station => station && hasValidLatLon(station.location));
                const stationIds = clusterMembers.map(station => station.id);
                
                if (clusterMembers.length < 2) return;
                
                const latlngs = [];
                const clusterStations = [];
                clusterMembers.forEach(st => {
                    latlngs.push([Number(st.location.lat), Number(st.location.lon)]);
                    clusterStations.push(st.name || st.station_code || String(st.id));
                });
                
                if (latlngs.length >= 2) {
                    const multiLatLngs = []; for (let i = 0; i < latlngs.length; i++) { for (let j = i + 1; j < latlngs.length; j++) { multiLatLngs.push([latlngs[i], latlngs[j]]); } } const polyline = L.polyline(multiLatLngs, {
                        color: colors[colorIdx % colors.length],
                        weight: 3,
                        opacity: 0.7,
                        dashArray: '5, 10'
                    });
                    
                    polyline.on('click', (e) => {
                        showAdjustmentPopup(proj.id, proj.name, stationIds, clusterStations, e.latlng);
                    });
                    
                    if (leafletMap) polyline.addTo(leafletMap);
                    clusterPolylines.push(polyline);
                    colorIdx++;
                }
            });
        });
    } catch (e) {
        console.error('Error loading projects and clusters:', e);
    }
}

function showAdjustmentPopup(projectId, projectName, stationIds, clusterStations, latlng) {
    const leafletMap = getLeafletMap();
    if (!leafletMap) return;
    
    const popupContent = document.createElement('div');
    popupContent.className = 'text-center p-2';
    popupContent.innerHTML = `
        <h6 class="mb-2 fw-bold" style="color: #10b981;">${projectName}</h6>
        <div class="small mb-3 text-secondary">Cụm: ${clusterStations.join(', ')}</div>
        <button class="btn btn-sm btn-success w-100" id="btn-start-adjustment-${projectId}">
            <i class="bi bi-play-fill"></i> Bắt đầu Bình sai
        </button>
    `;
    
    const popup = L.popup()
        .setLatLng(latlng)
        .setContent(popupContent)
        .openOn(leafletMap);
        
    setTimeout(() => {
        const btn = document.getElementById(`btn-start-adjustment-${projectId}`);
        if (btn) {
            btn.addEventListener('click', () => {
                leafletMap.closePopup(popup);
                requestGnssAdjustment(projectId, stationIds);
            });
        }
    }, 100);
}

async function loadStations() {
    try {
        const res = window.authManager?.isAuthenticated?.()
            ? await window.authManager.apiFetch('/api/stations')
            : await fetch('/api/stations');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const stations = await res.json();
        allStations = stations;

        stations.forEach(station => {
            if (station.location && station.location.lat && station.location.lon) {
                updateMarker(station);
            }

            // ✅ Sync marker blinking state từ risk_level API (restore sau reload)
            const _isAlertingRisk = normalizeRiskLevel(station.risk_level, station.status) === 'CRITICAL'
                && station.status !== 'offline';
            if (_isAlertingRisk && !markerAlertState[station.id]) {
                setMarkerAlert(station.id, true);
            } else if (!_isAlertingRisk && markerAlertState[station.id]) {
                clearMarkerAlert(station.id);
            }

            // ✅ THÊM: Nếu trạm đang xem bị đổi status (ví dụ offline/online, hoặc đổi risk_level)
            if (currentStationData && currentStationData.id === station.id) {
                if (currentStationData.status !== station.status || currentStationData.risk_level !== station.risk_level) {
                    console.log(`🔄 [STATE] Station ${station.id} changed state: ${currentStationData.status}->${station.status}, updating UI...`);
                    currentStationData.status = station.status;
                    currentStationData.risk_level = station.risk_level;
                    if (currentStationData.risk_assessment) {
                        currentStationData.risk_assessment.overall_risk = station.risk_level;
                    }
                    updateSidebarUI(currentStationData);
                }
            }
        });

        renderStationList(stations);
        ensureGlobalAlertBannerFromStations(stations);
        loadProjectsAndClusters();

    } catch (e) {
        console.error('❌ [MAP] Error loading stations:', e);
    }
}

function ensureGlobalAlertBannerFromStations(stations) {
    const banner = document.getElementById('alert-banner');
    if (!banner || banner.classList.contains('show')) return;
    if (!Array.isArray(stations) || stations.length === 0) return;

    const candidates = stations
        .map(st => {
            const riskUi = getRiskPresentation(st.risk_level, st.status);
            return { station: st, riskUi };
        })
        .filter(item => item.riskUi.normalized === 'CRITICAL' || item.riskUi.normalized === 'MEDIUM')
        .sort((a, b) => (a.riskUi.normalized === 'CRITICAL' ? -1 : 1));

    if (candidates.length === 0) return;

    const chosen = candidates[0];
    const stationId = chosen.station.id;
    const snoozeUntil = Number(alertBannerSnoozeUntil[stationId] || 0);
    if (Date.now() < snoozeUntil) return;
    if (isBannerSuppressed(stationId)) return;

    const level = chosen.riskUi.normalized === 'CRITICAL' ? 'CRITICAL' : 'WARNING';
    const cachedAlert = latestAlertByStation[stationId];
    const candidateAlert = cachedAlert ? { ...cachedAlert, level } : {
        station_id: stationId,
        level,
        message: chosen.riskUi.normalized === 'CRITICAL'
            ? 'Critical risk detected from station state. Press Track to monitor now.'
            : 'Warning risk detected from station state. Press Track to monitor now.'
    };
    const candidateKey = buildAlertKey(candidateAlert);
    if (candidateKey && acknowledgedAlertKeyByStation[stationId] === candidateKey) return;

    showAlertBanner(candidateAlert, { silent: true });
}

// ✅ Silently re-fetch current station detail to refresh per-sensor is_online status
async function refreshCurrentStationDetail() {
    if (!currentStationData) return;
    const sidebar = document.getElementById('detail-sidebar');
    if (!sidebar || !sidebar.classList.contains('active')) return;

    try {
        const res = window.authManager?.isAuthenticated?.()
            ? await window.authManager.apiFetch(`/api/stations/${currentStationData.id}/detail`)
            : await fetch(`/api/stations/${currentStationData.id}/detail`);
        if (!res.ok) return;
        const data = await res.json();
        const stationId = data.id;
        const apiImuTs = Number(data.sensors?.imu?.latest_timestamp || 0);
        const wsImuTs = Number(latestRealtimeSensorTs[`${stationId}_imu`] || 0);
        console.debug(`🔍 [IMU][REFRESH] station=${stationId} api_ts=${apiImuTs || 'none'} ws_ts=${wsImuTs || 'none'}`);
        currentStationData = data;
        updateSidebarUI(currentStationData);
        console.log(`🔄 [MAP] Refreshed detail for station ${currentStationData.id}`);
    } catch (e) {
        console.warn('⚠️ [MAP] Silent detail refresh failed:', e);
    }
}

function renderStationList(stations) {
    const container = document.getElementById('station-list-container');
    if (!container) return;

    if (stations.length === 0) {
        container.innerHTML = `
                    <div class="text-center text-muted mt-4">
                        <i class="bi bi-inbox fs-1"></i>
                        <p class="mt-2">Chưa có trạm nào</p>
                    </div>
                `;
        return;
    }

    const currentIds = new Set(stations.map(st => st.id.toString()));
    
    Array.from(container.children).forEach(child => {
        if (child.dataset && child.dataset.stationId && !currentIds.has(child.dataset.stationId)) {
            container.removeChild(child);
        }
    });

    const emptyPlaceholder = container.querySelector('.text-center.text-muted');
    if (emptyPlaceholder) emptyPlaceholder.remove();

    stations.forEach(st => {
        const riskUi = getRiskPresentation(st.risk_level, st.status);
        const badgeClass = getRiskBadgeClass(riskUi.className);
        
        let div = container.querySelector(`div[data-station-id="${st.id}"]`);
        
        if (div) {
            const badge = div.querySelector('.badge');
            if (badge) {
                const targetClass = `badge ${badgeClass}`;
                if (badge.className !== targetClass) badge.className = targetClass;
                if (badge.textContent.trim() !== riskUi.display) badge.textContent = riskUi.display;
            }
        } else {
            div = document.createElement('div');
            div.className = 'station-item';
            div.dataset.stationId = st.id;
            div.innerHTML = `
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <div class="fw-bold" style="color: var(--text-primary)">${st.name}</div>
                        <small style="color: var(--text-secondary)">${st.station_code}</small>
                    </div>
                    <span id="list-badge-${st.id}" class="badge ${badgeClass}">
                        ${riskUi.display}
                    </span>
                </div>
            `;
            div.addEventListener('click', () => {
                selectStation(st.id);
                if (window.innerWidth < 768) {
                    const sidebar = document.getElementById('station-list-sidebar');
                    if (sidebar) sidebar.classList.add('hidden');
                }
            });
            container.appendChild(div);
        }
    });
}

function getRiskBadgeClass(level) {
    const classes = {
        'CRITICAL': 'bg-danger',
        'EXTREME': 'bg-danger',
        'MEDIUM': 'bg-warning text-dark',
        'HIGH': 'bg-warning text-dark',
        'WARNING': 'bg-warning text-dark',
        'STALE': 'bg-warning text-dark',
        'LOW': 'bg-success',
        'OFFLINE': 'bg-secondary'
    };
    return classes[level] || 'bg-success';
}

// ✅ BOOST 3: Cache trạng thái marker để tránh vẽ lại không cần thiết
let stationStateCache = {};

function updateMarker(station) {
    const colors = {
        'CRITICAL': '#fa5252',
        'MEDIUM': '#ffd43b',
        'STALE': '#f59e0b',
        'LOW': '#51cf66',
        'OFFLINE': '#6c757d'
    };

    let currentLevel = normalizeRiskLevel(station.risk_level, station.status);
    if (!colors[currentLevel]) currentLevel = 'LOW';

    const color = colors[currentLevel] || '#adb5bd';
    const shouldPulse = currentLevel === 'CRITICAL';

    // ✅ KIỂM TRA CACHE: Nếu trạng thái không đổi thì KHÔNG LÀM GÌ CẢ
    const cacheKey = `${station.id}_${currentLevel}_${station.status}_${station.location.lat}_${station.location.lon}`;
    if (stationStateCache[station.id] === cacheKey) {
        return; // Dữ liệu y hệt cũ -> Bỏ qua, không vẽ lại (Giảm tải CPU)
    }

    // Cập nhật Cache mới
    stationStateCache[station.id] = cacheKey;

    // ✅ Tạo HTML string cho divIcon (giúp Leaflet giữ nguyên class khi re-render)
    const pulseClass = shouldPulse ? ' marker-alert-pulse' : '';
    const iconHtml = `<div class="marker-circle${pulseClass}" style="
                width: 18px; height: 18px; background: ${color};
                border-radius: 50%; border: 2px solid white;
                box-shadow: 0 0 8px rgba(0,0,0,0.5);
                transition: background 0.3s ease;
            "></div>`;

    if (markers[station.id]) {
        markers[station.id].setLatLng([station.location.lat, station.location.lon]);

        // ✅ Cập nhật icon mới với HTML string (giữ pulse class)
        const newIcon = L.divIcon({
            className: 'custom-map-marker',
            html: iconHtml,
            iconSize: [18, 18],
            iconAnchor: [9, 9]
        });
        markers[station.id].setIcon(newIcon);
    } else {
        const icon = L.divIcon({
            className: 'custom-map-marker',
            html: iconHtml,
            iconSize: [18, 18],
            iconAnchor: [9, 9]
        });

        const marker = L.marker([station.location.lat, station.location.lon], { icon })
            .bindTooltip(station.name, { direction: 'top', offset: [0, -10] });

        if (stationClusterGroup) {
            stationClusterGroup.addLayer(marker);
        }

        marker.on('click', () => selectStation(station.id));
        markers[station.id] = marker;
    }
}

// =====================================================
// SIREN POPUP HELPER — Dùng bởi selectStation và Track button
// =====================================================
function _showSirenIfAlerting(stationId, data) {
    const sirenSection = document.getElementById('siren-sidebar-section');

    // Only show siren controls for admin and operator roles
    const user = window.authManager?.getUserInfo();
    const userRole = user?.role;
    if (userRole !== 'admin' && userRole !== 'operator') {
        if (sirenSection) sirenSection.style.display = 'none';
        return;
    }

    // Always visible for admin/operator (grey when idle, red when alerting)
    if (sirenSection) sirenSection.style.display = '';

    const risk = data.risk_assessment?.overall_risk || data.risk_level;
    const isAlerting = (risk === 'EXTREME' || risk === 'CRITICAL') && data.status !== 'offline';

    // Default statuses based on pi_devices array from station detail API
    let pointDeviceStatus = 'idle';
    let centerDeviceStatus = 'idle';

    if (data.pi_devices && Array.isArray(data.pi_devices)) {
        const pPoint = data.pi_devices.find(d => d.device_type === 'pi_point');
        const pCenter = data.pi_devices.find(d => d.device_type === 'pi_center');

        if (pPoint && !pPoint.is_online) pointDeviceStatus = 'offline';
        if (pCenter && !pCenter.is_online) centerDeviceStatus = 'offline';
        // If there is no pi_point or pi_center registered for this station, maybe set to offline?
        // But let's only override if explicitly offline to be safe.
    }

    if (isAlerting) {
        currentAlertStationId = stationId;
        const sirenBtns = document.querySelectorAll('.btn-siren-toggle');
        if (sirenBtns.length > 0) {
            sirenBtns.forEach(b => {
                const target = b.getAttribute('data-target');
                let currentState = b.getAttribute('data-siren-state');

                // Determine target default status (might be offline)
                const isOffline = target === 'pi_center' ? centerDeviceStatus === 'offline' : pointDeviceStatus === 'offline';

                if (isOffline) {
                    setSirenButtonState('offline', target);
                } else {
                    // If online, transition idle to alerting, keep muted as is
                    if (currentState === 'idle' || currentState === 'offline') currentState = 'alerting';
                    setSirenButtonState(currentState, target);
                }
            });
        }
    } else {
        if (currentAlertStationId === stationId) {
            currentAlertStationId = null;
        }

        // Apply idle or offline if not alerting
        setSirenButtonState(centerDeviceStatus === 'offline' ? 'offline' : 'idle', 'pi_center');
        setSirenButtonState(pointDeviceStatus === 'offline' ? 'offline' : 'idle', 'pi_point');
    }
}

async function selectStation(stationId, options = {}) {
    if (currentMapMode === 'rescue') {
        return;
    }

    const { skipZoom = false, skipSiren = false, skipBannerRestore = false } = options;
    console.log(`🎯 [MAP] Selecting station: ${stationId}`, options);

    const sidebar = document.getElementById('detail-sidebar');
    if (sidebar) {
        sidebar.classList.add('active');
    }

    try {
        const res = window.authManager?.isAuthenticated?.()
            ? await window.authManager.apiFetch(`/api/stations/${stationId}/detail`)
            : await fetch(`/api/stations/${stationId}/detail`);
        if (!res.ok) throw new Error('Failed to load station detail');

        const data = await res.json();
        currentStationData = data;

        if (!skipZoom && markers[stationId]) {
            map.flyTo(markers[stationId].getLatLng(), 16, { duration: 1 });
        }

        updateSidebarUI(data);
        applySensorCardAlertsFromAssessment(data);

        // ✅ Siren popup logic — có thể bị skip bởi caller (ví dụ: Track button tự quản lý)
        if (!skipSiren) {
            _showSirenIfAlerting(stationId, data);
        }

        // ✅ Restore alert banner + siren buttons im lặng nếu trạm đang có alert từ DB (sau reload)
        const _banner = document.getElementById('alert-banner');
        const _riskLevel = data.risk_assessment?.overall_risk || data.risk_level || 'LOW';
        const _riskBand = normalizeRiskLevel(_riskLevel, data.status);
        const _activeAlerts = data.risk_assessment?.active_alerts || [];
        if (!_banner?.classList.contains('show') &&
            !skipBannerRestore &&
            !isBannerSuppressed(data.id) &&
            (_riskBand === 'MEDIUM' || _riskBand === 'CRITICAL') &&
            _activeAlerts.length > 0 &&
            data.status !== 'offline') {
            const _topAlert = _activeAlerts.find(a => a.level === 'CRITICAL') || _activeAlerts[0];
            // Show banner (silent — không kêu còi browser)
            showAlertBanner({
                station_id: data.id,
                level: _topAlert.level,
                message: _topAlert.message,
                sensor_type: mapAlertCategoryToSensorType(_topAlert.category)
            }, { silent: true });
            // Sync siren buttons đúng per-device (đã handle offline/online trong _showSirenIfAlerting)
            _showSirenIfAlerting(data.id, data);
        }

    } catch (e) {
        console.error('❌ [MAP] Error loading station detail:', e);
        window.toast?.error('Failed to load station info');
    }
}

function getGnssVelocity(gnssLatest) {
    if (!gnssLatest) return null;
    const data = gnssLatest.data || gnssLatest;
    const toFinite = (value) => {
        const num = Number(value);
        return Number.isFinite(num) ? num : null;
    };

    const velE = toFinite(data.vel_e);
    const velN = toFinite(data.vel_n);
    if (velE !== null && velN !== null) {
        return Math.sqrt(Math.pow(velE, 2) + Math.pow(velN, 2));
    }

    for (const key of ['velocity_mm_s', 'speed_2d_mm_s', 'speed_mm_s']) {
        const value = toFinite(data[key]);
        if (value !== null) return value;
    }

    for (const key of ['speed_2d', 'velocity', 'speed']) {
        const value = toFinite(data[key]);
        if (value !== null) return value * 1000;
    }

    return null;
}

function safeNumber(value, decimals = 2, defaultValue = '--') {
    if (value === null || value === undefined || value === '') {
        return defaultValue;
    }

    const num = parseFloat(value);
    if (isNaN(num)) {
        return defaultValue;
    }

    return num.toFixed(decimals);
}

function formatWaterLevelDisplay(waterLatest) {
    // If sensor is offline or value is fallback, show -- immediately
    if (waterLatest?.is_fallback === true) {
        return `--<span class="sensor-unit">cm</span>`;
    }

    const unitRaw = String(waterLatest?.water_display_unit || '').trim().toLowerCase();
    const displayRaw = parseFloat(waterLatest?.water_display_value);
    let levelCm = null;

    if (!Number.isNaN(displayRaw)) {
        if (unitRaw === 'mm') {
            // Sanity check: if mm unit but value < 10, likely mislabeled as m
            if (displayRaw < 10) {
                levelCm = displayRaw * 100;  // Treat as meters
            } else {
                levelCm = displayRaw / 10;   // Treat as millimeters
            }
        } else if (unitRaw === 'm' || unitRaw === 'meter' || unitRaw === 'meters') {
            levelCm = displayRaw * 100;
        } else if (unitRaw === 'cm') {
            levelCm = displayRaw;
        }
    }

    if (levelCm === null) {
        const cmRaw = parseFloat(waterLatest?.water_level_cm);
        if (!Number.isNaN(cmRaw)) {
            levelCm = cmRaw;
        }
    }

    if (levelCm === null) {
        const meterRaw = parseFloat(waterLatest?.water_level ?? waterLatest?.processed_value_meters);
        if (!Number.isNaN(meterRaw)) {
            levelCm = meterRaw * 100;
        }
    }

    if (levelCm === null) {
        return `--<span class="sensor-unit">cm</span>`;
    }

    if (Math.abs(levelCm) >= 100) {
        return `${safeNumber(levelCm / 100, 2)}<span class="sensor-unit">m</span>`;
    }

    return `${safeNumber(levelCm, 1)}<span class="sensor-unit">cm</span>`;
}

function formatImuDelta(val, axis) {
    const num = parseFloat(val);
    if (isNaN(num)) return '-- cm';
    const dispMm = Math.sin(num * Math.PI / 180) * 0.09 * 1000; // mm
    const sign = dispMm > 0 ? '+' : '';
    // Ưu tiên cm; chỉ dùng mm khi |giá trị| < 1 cm
    const absMm = Math.abs(dispMm);
    const [displayVal, unit] = absMm >= 10
        ? [(dispMm / 10).toFixed(2), 'cm']
        : [dispMm.toFixed(1), 'mm'];
    const threshold = unit === 'cm' ? 0.05 : 0.5;
    const arrows = {
        roll: dispMm > threshold ? ' →' : dispMm < -threshold ? ' ←' : '',
        pitch: dispMm > threshold ? ' ↑' : dispMm < -threshold ? ' ↓' : '',
        yaw: dispMm > threshold ? ' ↻' : dispMm < -threshold ? ' ↺' : '',
    };
    return `${sign}${displayVal} ${unit}${arrows[axis] || ''}`;
}

function updateGnssFixBadge(fixMode, fixQuality) {
    const badge = document.getElementById('gnss-fix-badge');
    if (!badge) return;

    const normalizedMode = (fixMode || '').toString().trim().toUpperCase();
    const quality = Number(fixQuality);

    let cls = 'GNSS_UNKNOWN';
    let text = 'NO DATA';

    switch (normalizedMode) {
        case 'GNSS_RTK_FIXED':
        case 'RTK_FIXED':
            cls = 'GNSS_RTK_FIXED';
            text = 'RTK FIXED';
            break;
        case 'GNSS_RTK_FLOAT':
        case 'RTK_FLOAT':
            cls = 'GNSS_RTK_FLOAT';
            text = 'RTK FLOAT';
            break;
        case 'GNSS_DGPS_FLOAT':
        case 'DGPS_FLOAT':
            cls = 'GNSS_DGPS_FLOAT';
            text = 'DGPS FLOAT';
            break;
        case 'GNSS_SINGLE':
        case 'GPS_SINGLE_NO_RTK':
        case 'SINGLE':
        case 'NO_RTK':
            cls = 'GNSS_SINGLE';
            text = 'NO RTK';
            break;
        case 'GNSS_INVALID':
        case 'INVALID':
            cls = 'GNSS_INVALID';
            text = 'INVALID';
            break;
        case 'GNSS_UNKNOWN':
        case 'NO_DATA':
            cls = 'GNSS_UNKNOWN';
            text = 'NO DATA';
            break;
        default:
            if (quality === 4) {
                cls = 'GNSS_RTK_FIXED';
                text = 'RTK FIXED';
            } else if (quality === 5) {
                cls = 'GNSS_RTK_FLOAT';
                text = 'RTK FLOAT';
            } else if (quality === 2) {
                cls = 'GNSS_DGPS_FLOAT';
                text = 'DGPS FLOAT';
            } else if (quality === 1) {
                cls = 'GNSS_SINGLE';
                text = 'NO RTK';
            }
            break;
    }

    badge.className = `gnss-fix-badge ${cls}`;
    badge.textContent = text;
}

function updateImuOfflineBadge(isOnline) {
    const badge = document.getElementById('imu-offline-badge');
    if (!badge) return;
    badge.style.display = isOnline ? 'none' : '';
}

function updateSensorOfflineBadge(sensorType, isOnline) {
    const badge = document.getElementById(`${sensorType}-offline-badge`);
    if (!badge) return;
    badge.style.display = isOnline ? 'none' : '';
}

function updateSidebarUI(data) {
    setText('st-name', data.name);
    setText('st-code', data.station_code);

    // ✅ Handle offline_display_enabled to force STALE status and show old data
    const isOfflineDisplayEnabled = ((data.offline_display?.enabled === true) || data.offline_display_enabled === true);
    let effectiveStatus = data.status;
    if (effectiveStatus === 'offline' && isOfflineDisplayEnabled) {
        effectiveStatus = 'stale'; // turn yellow
    }

    const riskEl = document.getElementById('st-risk');
    if (riskEl) {
        const riskUi = getRiskPresentation(data.risk_assessment?.overall_risk || data.risk_level, effectiveStatus);
        riskEl.className = `status-badge ${riskUi.className}`;
        riskEl.innerHTML = `<span class="status-dot"></span> ${riskUi.display}`;
    }

    const gnssLatest = data.sensors?.gnss?.latest;
    const rainLatest = data.sensors?.rain?.latest;
    const waterLatest = data.sensors?.water?.latest;
    const imuLatest = data.sensors?.imu?.latest;
    const stationId = data.id;
    const imuApiTs = Number(data.sensors?.imu?.latest_timestamp || 0);
    const imuRealtimeTs = Number(latestRealtimeSensorTs[`${stationId}_imu`] || 0);
    const latestSensorTs = getLatestSensorTimestamp(data);

    // ✅ Per-sensor online check: nếu sensor đó offline → hiển thị '--' dù trạm vẫn online
    const mqttConnected = data.mqtt_connected !== false;
    renderStaleInfo(data, mqttConnected, latestSensorTs);
    
    // staleDisplay is true if station is stale OR if we forced it to stale because of offline_display_enabled
    const staleDisplay = (effectiveStatus === 'stale' || data.status === 'stale') && isOfflineDisplayEnabled;
    
    const gnssOnline = mqttConnected && effectiveStatus !== 'offline' &&
        ((data.sensors?.gnss?.is_online ?? false) || (staleDisplay && !!gnssLatest));
    const rainOnline = mqttConnected && effectiveStatus !== 'offline' &&
        ((data.sensors?.rain?.is_online ?? false) || (staleDisplay && !!rainLatest));
    const waterOnline = mqttConnected && effectiveStatus !== 'offline' &&
        ((data.sensors?.water?.is_online ?? false) || (staleDisplay && !!waterLatest));
    const imuOnline = mqttConnected && effectiveStatus !== 'offline' &&
        ((data.sensors?.imu?.is_online ?? false) || (staleDisplay && !!imuLatest));

    if (gnssOnline) {
        const gnssFixBadgeEl = document.getElementById('gnss-fix-badge');
        const gnssOfflineBadgeEl = document.getElementById('gnss-offline-badge');
        if (gnssFixBadgeEl) gnssFixBadgeEl.style.display = '';
        if (gnssOfflineBadgeEl) gnssOfflineBadgeEl.style.display = 'none';
        updateGnssFixBadge(gnssLatest?.fix_mode, gnssLatest?.fix_quality);
    } else {
        const gnssFixBadgeEl = document.getElementById('gnss-fix-badge');
        const gnssOfflineBadgeEl = document.getElementById('gnss-offline-badge');
        if (gnssFixBadgeEl) gnssFixBadgeEl.style.display = 'none';
        if (gnssOfflineBadgeEl) gnssOfflineBadgeEl.style.display = '';
    }

    // ✅ POPULATE: Điền dữ liệu Advanced GNSS — luôn hiển thị dữ liệu cuối cùng,
    // kể cả khi sensor offline (tránh bị mất chữ khi refresh)
    // API trả data flat trên gnssLatest, WS cache lưu dưới gnssLatest.data
    const adv = gnssLatest?.data || gnssLatest;
    if (adv && adv.adv_x !== undefined) {
        // Vị trí hiện tại: Lat/Lon/Alt từ GNGGA
        setText('adv-val-lat', (adv.lat || 0).toFixed(6));
        setText('adv-val-lon', (adv.lon || 0).toFixed(6));
        setText('adv-val-alt', (adv.adv_h || adv.h || 0).toFixed(3));
        // Biến dạng lũy kế
        setText('adv-val-dx', (adv.adv_dx || 0).toFixed(2));
        setText('adv-val-dy', (adv.adv_dy || 0).toFixed(2));
        setText('adv-val-dh', (adv.adv_dh || 0).toFixed(2));
        // Vận tốc biến dạng
        setText('adv-val-vdx', (adv.adv_vdx || 0).toFixed(4));
        setText('adv-val-vdy', (adv.adv_vdy || 0).toFixed(4));
        setText('adv-val-vdh', (adv.adv_vdh || 0).toFixed(4));
    }
    updateSensorOfflineBadge('rain', rainOnline);
    updateSensorOfflineBadge('water', waterOnline);
    updateImuOfflineBadge(imuOnline);

    // ✅ Khi toàn trạm offline → hiển thị '--' cho TẤT CẢ sensor
    if (effectiveStatus === 'offline') {
        setHTML('val-gnss-vel', `--<span class="sensor-unit">mm/s</span>`);
        setHTML('val-rain', `--<span class="sensor-unit">mm/h</span>`);
        setHTML('val-water', `--<span class="sensor-unit">cm</span>`);
        setText('val-imu-roll', '--°');
        setText('val-imu-pitch', '--°');
        setText('val-imu-yaw', '--°');
        setText('val-imu-delta-roll', '-- mm');
        setText('val-imu-delta-pitch', '-- mm');
        setText('val-imu-delta-yaw', '-- mm');
        updateImuDrift(null, null);

        // ✅ Khi offline, nút tắt còi chuyển xám (idle)
        setSirenButtonState('idle');

        // Ẩn battery khi offline
        const batteryContainer = document.getElementById('battery-container');
        if (batteryContainer) batteryContainer.style.display = 'none';
    } else {
        // GNSS: chỉ hiện giá trị khi sensor đang online
        if (gnssOnline) {
            const gnssSpeed = getGnssVelocity(gnssLatest);
            setHTML('val-gnss-vel', `${safeNumber(gnssSpeed, 4)}<span class="sensor-unit">mm/s</span>`);
        } else {
            setHTML('val-gnss-vel', `--<span class="sensor-unit">mm/s</span>`);
        }

        // Rain
        if (rainOnline) {
            const rainIntensity = rainLatest?.intensity_mm_h ?? null;
            setHTML('val-rain', `${safeNumber(rainIntensity, 1)}<span class="sensor-unit">mm/h</span>`);
        } else {
            setHTML('val-rain', `--<span class="sensor-unit">mm/h</span>`);
        }

        // Water
        if (waterOnline) {
            setHTML('val-water', formatWaterLevelDisplay(waterLatest));
        } else {
            setHTML('val-water', `--<span class="sensor-unit">cm</span>`);
        }

        // IMU
        if (imuOnline) {
            const useApiImu = !imuRealtimeTs || !imuApiTs || imuApiTs >= imuRealtimeTs;
            console.debug(`🧭 [IMU][MERGE] station=${stationId} api_ts=${imuApiTs || 'none'} ws_ts=${imuRealtimeTs || 'none'} source=${useApiImu ? 'api' : 'ws-cache'}`);

            if (useApiImu) {
                setText('val-imu-roll', `${safeNumber(imuLatest?.raw_roll, 1)}°`);
                setText('val-imu-pitch', `${safeNumber(imuLatest?.raw_pitch, 1)}°`);
                setText('val-imu-yaw', `${safeNumber(imuLatest?.raw_yaw, 1)}°`);
                setText('val-imu-delta-roll', formatImuDelta(imuLatest?.roll, 'roll'));
                setText('val-imu-delta-pitch', formatImuDelta(imuLatest?.pitch, 'pitch'));
                setText('val-imu-delta-yaw', formatImuDelta(imuLatest?.yaw, 'yaw'));
            } else {
                console.warn(`⏭️ [IMU] Skip stale API overwrite station=${stationId} api_ts=${imuApiTs} < ws_ts=${imuRealtimeTs}`);
            }

            // Use backend drift calculation if available
            if (useApiImu) {
                if (imuLatest?.drift_len_mm !== undefined && imuLatest?.drift_dir !== undefined) {
                    setText('val-imu-drift-len', `${safeNumber((parseFloat(imuLatest.drift_len_mm) || 0) / 10, 1)} cm`);
                    setText('val-imu-drift-dir', `(${imuLatest.drift_dir})`);

                    // Update realtime 3D if active
                    if (realtimeImuActive && realtimeImuSensorBlock && _THREE) {
                        const currPitch = (imuLatest.pitch || 0) * Math.PI / 180;
                        const currRoll = (imuLatest.roll || 0) * Math.PI / 180;
                        const targetQuaternion = new _THREE.Quaternion();
                        const euler = new _THREE.Euler(currPitch, 0, currRoll, 'XYZ');
                        targetQuaternion.setFromEuler(euler);
                        realtimeImuTargetQuaternion = targetQuaternion;
                    }
                } else {
                    updateImuDrift(imuLatest?.roll, imuLatest?.pitch);
                }
            }
        } else {
            setText('val-imu-roll', '--°');
            setText('val-imu-pitch', '--°');
            setText('val-imu-yaw', '--°');
            setText('val-imu-delta-roll', '-- mm');
            setText('val-imu-delta-pitch', '-- mm');
            setText('val-imu-delta-yaw', '-- mm');
            updateImuDrift(null, null);
        }

        // ✅ GNSS Adjusted Cache Rendering
        const adjResultsSection = document.getElementById('adj-results-section');
        const adjStatusEl = document.getElementById('adj-process-status');
        const adjTimeEl = document.getElementById('adj-val-time');
        const adjPointsList = document.getElementById('adj-points-list');
        
        const adjCached = data.sensors?.gnss_adjusted;
        if (
            adjCached
            && adjCached.latest
            && isGnssAdjustmentResultRelevant(adjCached.latest, adjCached.latest_timestamp)
        ) {
            const cacheData = adjCached.latest;
            window.gnssBoardState?.loadAdjustmentResult?.(cacheData);
            if (adjStatusEl) {
                adjStatusEl.innerHTML = `<span class="text-success fw-bold"><i class="bi bi-check-circle-fill me-1"></i>Bình sai thành công (Đã lưu)</span>`;
            }
            if (adjTimeEl && adjCached.latest_timestamp) {
                adjTimeEl.textContent = new Date(adjCached.latest_timestamp * 1000).toLocaleString();
            }
            if (adjResultsSection) {
                adjResultsSection.style.display = 'block';
            }
            if (adjPointsList) {
                adjPointsList.innerHTML = '';
                
                // Add Excel workbook download button
                if (cacheData.excel_report_url) {
                    const downloadXlsBtn = document.createElement('a');
                    downloadXlsBtn.href = cacheData.excel_report_url;
                    downloadXlsBtn.target = '_blank';
                    downloadXlsBtn.className = 'btn btn-sm btn-outline-success w-100 mb-2 py-1';
                    downloadXlsBtn.style.fontSize = '0.72rem';
                    downloadXlsBtn.innerHTML = '<i class="bi bi-file-earmark-spreadsheet me-1"></i> Tải báo cáo bình sai (Excel)';
                    adjPointsList.appendChild(downloadXlsBtn);
                }
                // Add download report button
                if (cacheData.report_file_url) {
                    const downloadBtn = document.createElement('a');
                    downloadBtn.href = cacheData.report_file_url;
                    downloadBtn.target = '_blank';
                    downloadBtn.className = 'btn btn-sm btn-outline-info w-100 mb-2 py-1';
                    downloadBtn.style.fontSize = '0.72rem';
                    downloadBtn.innerHTML = '<i class="bi bi-download me-1"></i> Tải báo cáo bình sai (JSON)';
                    adjPointsList.appendChild(downloadBtn);
                }
                
                if (cacheData.points) {
                    for (const [ptName, ptCoords] of Object.entries(cacheData.points)) {
                        const coordinates = getAdjustedPointCoordinates(ptCoords);
                        const item = document.createElement('div');
                        item.className = 'list-group-item bg-transparent text-slate-300 py-1.5 px-0 d-flex justify-content-between align-items-center border-bottom border-white/5';
                        item.innerHTML = `
                            <span class="fw-semibold text-teal-400 font-monospace">${ptName}</span>
                            <span class="text-glow font-monospace text-end" style="font-size:0.68rem; line-height: 1.2;">
                                X: ${formatAdjustedCoordinate(coordinates[0])}<br>
                                Y: ${formatAdjustedCoordinate(coordinates[1])}<br>
                                Z: ${formatAdjustedCoordinate(coordinates[2])}
                            </span>
                        `;
                        adjPointsList.appendChild(item);
                    }
                }
            }
        } else {
            if (adjResultsSection) adjResultsSection.style.display = 'none';
            if (adjPointsList) adjPointsList.innerHTML = '';
        }

        // ✅ Battery Voltage: chỉ hiển thị khi IMU online và có giá trị > 0
        const batteryContainer = document.getElementById('battery-container');
        const batteryVal = imuLatest?.battery;
        if (imuOnline && batteryVal !== undefined && batteryVal !== null && parseFloat(batteryVal) > 0) {
            if (batteryContainer) batteryContainer.style.display = '';
            setHTML('val-battery', `${safeNumber(batteryVal, 2)}<span class="sensor-unit">V</span>`);
        } else {
            if (batteryContainer) batteryContainer.style.display = 'none';
        }
    }
}

function renderCharts(data) {
    if (!data.sensors) return;

    console.log('📊 [CHARTS] Rendering charts for station devices...');

    // Show charts based on DEVICE presence, not data existence
    const allChartIds = ['chart-box-gnss', 'chart-box-rain', 'chart-box-water', 'chart-box-imu'];
    const activeChartBoxIds = [];

    // GNSS
    if (data.sensors.gnss) {
        activeChartBoxIds.push('chart-box-gnss');
        const history = data.sensors.gnss.history || [];
        // Compute velocity from vel_e/vel_n components (đã qua bộ lọc zeroing, khớp sidebar)
        const gnssHistory = history.map(h => ({
            timestamp: h.timestamp,
            data: {
                ...h.data,
                _chart_velocity: getGnssVelocity(h.data)
            }
        })).filter(h => h.data._chart_velocity !== null);
        renderChart('chart-gnss', gnssHistory, '_chart_velocity', '#fa5252', 'Velocity (mm/s)');
    }

    // Rain
    if (data.sensors.rain) {
        activeChartBoxIds.push('chart-box-rain');
        const history = data.sensors.rain.history || [];
        renderChart('chart-rain', history, 'intensity_mm_h', '#06b6d4', 'Intensity (mm/h)');
    }

    // Water
    if (data.sensors.water) {
        activeChartBoxIds.push('chart-box-water');
        const history = data.sensors.water.history || [];
        renderChart('chart-water', history, 'water_level', '#10b981', 'Level (m)');
    }

    // IMU (3-axis)
    if (data.sensors.imu) {
        activeChartBoxIds.push('chart-box-imu');
        renderImuChart(data.sensors.imu.history || []);
    }

    // Show/hide chart boxes
    allChartIds.forEach(chartBoxId => {
        const chartBox = document.getElementById(chartBoxId);
        if (chartBox) {
            chartBox.style.display = activeChartBoxIds.includes(chartBoxId) ? 'block' : 'none';
        }
    });

    // Show empty state if no sensors at all
    const emptyState = document.getElementById('charts-empty-state');
    if (emptyState) {
        emptyState.style.display = activeChartBoxIds.length === 0 ? 'block' : 'none';
    }

    console.log(`✅ [CHARTS] Rendered ${activeChartBoxIds.length} charts`);
}

function renderChart(id, history, key, color, label) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const labels = (history || []).map(h => {
        const date = new Date(h.timestamp * 1000);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });

    const values = (history || []).map(h => {
        const val = h.data?.[key];
        if (val === null || val === undefined || val === '') return null;
        const num = parseFloat(val);
        return Number.isFinite(num) ? num : null;
    });
    const numericValues = values.filter(value => value !== null);

    // Cập nhật chỉ số thống kê
    if (numericValues.length > 0) {
        const maxVal = Math.max(...numericValues);
        const minVal = Math.min(...numericValues);
        const avgVal = numericValues.reduce((a, b) => a + b, 0) / numericValues.length;
        const latestVal = numericValues[numericValues.length - 1];

        const elLatest = document.getElementById(`stat-${id}-latest`);
        const elMax = document.getElementById(`stat-${id}-max`);
        const elMin = document.getElementById(`stat-${id}-min`);
        const elAvg = document.getElementById(`stat-${id}-avg`);

        if (elLatest) elLatest.innerText = latestVal.toFixed(2);
        if (elMax) elMax.innerText = maxVal.toFixed(2);
        if (elMin) elMin.innerText = minVal.toFixed(2);
        if (elAvg) elAvg.innerText = avgVal.toFixed(2);
    } else {
        const elLatest = document.getElementById(`stat-${id}-latest`);
        const elMax = document.getElementById(`stat-${id}-max`);
        const elMin = document.getElementById(`stat-${id}-min`);
        const elAvg = document.getElementById(`stat-${id}-avg`);
        
        if (elLatest) elLatest.innerText = '--';
        if (elMax) elMax.innerText = '--';
        if (elMin) elMin.innerText = '--';
        if (elAvg) elAvg.innerText = '--';
    }

    if (charts[id]) {
        charts[id].destroy();
    }

    // Theme-aware colors
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const gridColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)';
    const tickColor = isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.4)';

    // Extract RGB from hex for gradient
    let r = 13, g = 110, b = 253; // Default blue
    if (color.startsWith('#') && color.length === 7) {
        r = parseInt(color.slice(1, 3), 16);
        g = parseInt(color.slice(3, 5), 16);
        b = parseInt(color.slice(5, 7), 16);
    }
    
    let gradient = ctx.createLinearGradient(0, 0, 0, 300);
    gradient.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.5)`);
    gradient.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0.0)`);

    charts[id] = new Chart(canvas, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: label,
                data: values,
                borderColor: color,
                backgroundColor: gradient,
                fill: true,
                tension: 0.4,
                borderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 4,
                pointBackgroundColor: color,
                pointBorderColor: '#fff',
                pointBorderWidth: 1.5,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: { 
                legend: { display: false },
                tooltip: {
                    backgroundColor: isDark ? 'rgba(15, 23, 42, 0.9)' : 'rgba(255, 255, 255, 0.9)',
                    titleColor: isDark ? '#fff' : '#1e293b',
                    bodyColor: isDark ? '#cbd5e1' : '#475569',
                    borderColor: isDark ? '#334155' : '#e2e8f0',
                    borderWidth: 1,
                    padding: 10,
                    boxPadding: 4,
                    usePointStyle: true,
                }
            },
            scales: {
                x: { 
                    display: true,
                    grid: { display: false },
                    ticks: {
                        color: tickColor,
                        maxTicksLimit: 6,
                        maxRotation: 0
                    }
                },
                y: {
                    grid: { 
                        color: gridColor,
                        borderDash: [5, 5],
                        drawBorder: false
                    },
                    ticks: { 
                        color: tickColor,
                        padding: 8
                    },
                    beginAtZero: true
                }
            }
        }
    });
}

function renderImuChart(history) {
    const ctx = document.getElementById('chart-imu');
    if (!ctx) return;

    const labels = (history || []).map(h => {
        const date = new Date(h.timestamp * 1000);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });

    const rollData = (history || []).map(h => parseFloat(h.data?.roll) || 0);
    const pitchData = (history || []).map(h => parseFloat(h.data?.pitch) || 0);
    const yawData = (history || []).map(h => parseFloat(h.data?.yaw) || 0);

    if (charts['chart-imu']) {
        charts['chart-imu'].destroy();
    }

    // Theme-aware colors
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const gridColor = isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)';
    const tickColor = isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.5)';
    const legendColor = isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.6)';

    charts['chart-imu'] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Roll (°)',
                    data: rollData,
                    borderColor: '#ff6384',
                    backgroundColor: 'rgba(255, 99, 132, 0.08)',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                    fill: true
                },
                {
                    label: 'Pitch (°)',
                    data: pitchData,
                    borderColor: '#4bc0c0',
                    backgroundColor: 'rgba(75, 192, 192, 0.08)',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                    fill: true
                },
                {
                    label: 'Yaw (°)',
                    data: yawData,
                    borderColor: '#36a2eb',
                    backgroundColor: 'rgba(54, 162, 235, 0.08)',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    display: true,
                    labels: {
                        color: legendColor,
                        usePointStyle: true,
                        pointStyle: 'circle',
                        font: { size: 11 }
                    }
                }
            },
            scales: {
                x: { display: false },
                y: {
                    grid: { color: gridColor },
                    ticks: {
                        color: tickColor,
                        callback: (v) => v + '°'
                    }
                }
            }
        }
    });
}

async function loadLongTermAnalysis(options = {}) {
    console.log('📊 [MAP] Loading long-term analysis...');

    if (!currentStationData) {
        console.error('❌ [MAP] No station selected');
        return null;
    }

    const stationId = currentStationData.id;
    const includeCorrelation = options.includeCorrelation === true || isRainCorrelationAiEnabled;

    // Get selected days from range selector
    const activeBtn = document.querySelector('#longterm-range-selector .btn.active');
    const days = activeBtn ? parseFloat(activeBtn.dataset.days) || 30 : 30;

    document.getElementById('longterm-loading').style.display = 'block';
    document.getElementById('longterm-content').style.display = 'none';
    document.getElementById('longterm-error').style.display = 'none';
    updateRainCorrelationAiControls();

    try {
        const params = new URLSearchParams({
            days: String(days),
            include_correlation: includeCorrelation ? 'true' : 'false',
            correlation_model: 'slide_model'
        });
        const res = await fetch(`/api/stations/${stationId}/long-term-analysis?${params.toString()}`);

        if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || 'Failed to load analysis');
        }

        const data = await res.json();

        renderLongTermAnalysis(data);
        return data;

    } catch (e) {
        console.error('❌ [MAP] Error loading long-term analysis:', e);
        showLongTermError(e.message);
        return null;
    } finally {
        rainCorrelationAiRunning = false;
        updateRainCorrelationAiControls();
    }
}

// Store last analysis data for re-rendering on time range change
let _lastLongTermData = null;

function renderLongTermAnalysis(data) {
    document.getElementById('longterm-loading').style.display = 'none';
    document.getElementById('longterm-content').style.display = 'block';
    document.getElementById('longterm-error').style.display = 'none';

    _lastLongTermData = data;
    updateRainCorrelationAiControls(data.rainfall_correlation);

    // === GNSS Section ===
    const gnss = data.gnss;
    const sourceNoteEl = document.getElementById('lt-gnss-source-note');
    if (gnss && gnss.status === 'success') {
        const analysis = gnss.analysis;

        const warningEl = document.getElementById('longterm-warning');
        const warningTextEl = document.getElementById('warning-text');
        const reliabilityNoteEl = document.getElementById('lt-reliability-note');
        const reliabilityTextEl = document.getElementById('lt-reliability-text');

        if (gnss.risk_level === 'CRITICAL' || gnss.risk_level === 'WARNING') {
            warningEl.style.display = 'block';
            warningEl.className = `alert ${gnss.risk_level === 'CRITICAL' ? 'alert-danger' : 'alert-warning'} mb-3`;
            warningTextEl.textContent = sanitizeLongTermText(gnss.warning_message);
        } else if (gnss.risk_level === 'INFO') {
            warningEl.style.display = 'block';
            warningEl.className = `alert alert-success mb-3`;
            warningTextEl.textContent = sanitizeLongTermText(gnss.warning_message);
        } else {
            warningEl.style.display = 'none';
        }

        const velocityDisplay = formatLongTermVelocityDisplay(analysis);
        setText('lt-velocity', velocityDisplay.text);
        setText('lt-velocity-ci', velocityDisplay.ciText);
        setText('lt-classification', analysis.classification || 'N/A');

        // Use auto cm/mm formatting
        setText('lt-total-disp', formatDisplacementString(analysis.total_displacement_mm, 1));

        setText('lt-duration', formatDurationString(analysis.duration_days));

        if (analysis.velocity_reliable === false) {
            reliabilityNoteEl.style.display = 'flex';
            reliabilityTextEl.textContent = analysis.reliability_message || 'Chưa đủ thời lượng quan sát.';
        } else {
            reliabilityNoteEl.style.display = 'none';
            reliabilityTextEl.textContent = '';
        }

        if (sourceNoteEl) {
            if (gnss.source === 'daily_summary_rollup') {
                sourceNoteEl.style.display = 'block';
                sourceNoteEl.innerHTML = '<i class="bi bi-calendar-week me-2"></i>GNSS đang phân tích từ dữ liệu tổng hợp ngày (daily summary). Dữ liệu raw cũ có thể đã được dọn để tối ưu hệ thống.';
            } else {
                sourceNoteEl.style.display = 'block';
                sourceNoteEl.innerHTML = '<i class="bi bi-broadcast me-2"></i>GNSS đang phân tích trực tiếp từ dữ liệu raw theo thời gian thực.';
            }
        }

        const trendIcons = { 'accelerating': '', 'stable': '', 'decelerating': '' };
        const trendTexts = { 'accelerating': 'Đang tăng tốc', 'stable': 'Ổn định', 'decelerating': 'Đang giảm tốc' };

        document.getElementById('trend-icon').textContent = trendIcons[analysis.trend] || '';
        document.getElementById('trend-value').textContent = trendTexts[analysis.trend] || 'Không xác định';

        const cusumBadge = document.getElementById('cusum-badge');
        const cusumMessage = document.getElementById('cusum-message');
        if (analysis.cusum_change) {
            cusumBadge.style.display = 'inline-block';
            cusumMessage.textContent = analysis.cusum_message || 'Có thay đổi xu hướng';
            cusumMessage.style.display = 'inline-block';
        } else {
            cusumBadge.style.display = 'none';
            cusumMessage.style.display = 'none';
        }
    } else {
        const warningEl = document.getElementById('longterm-warning');
        const reliabilityNoteEl = document.getElementById('lt-reliability-note');
        const reliabilityTextEl = document.getElementById('lt-reliability-text');
        if (warningEl) warningEl.style.display = 'none';
        if (reliabilityNoteEl) reliabilityNoteEl.style.display = 'none';
        if (reliabilityTextEl) reliabilityTextEl.textContent = '';
        if (sourceNoteEl) {
            sourceNoteEl.style.display = 'none';
            sourceNoteEl.textContent = '';
        }
        setText('lt-velocity', 'N/A');
        setText('lt-velocity-ci', '(Chưa có thông tin)');
        setText('lt-classification', 'N/A');
        setText('lt-total-disp', 'N/A');
        setText('lt-duration', 'N/A');
        document.getElementById('cusum-badge').style.display = 'none';
        document.getElementById('cusum-message').style.display = 'none';
    }

    // === IMU Section ===
    renderImuLongTermSection(data.imu);

    // === Combined Chart ===
    renderCombinedLongTermChart(data);

    // === 3D Simulations ===
    init3DVisualizations(data);

    // === NEW: Inverse Velocity (Fukuzono) ===
    renderInverseVelocitySection(data);

    // === NEW: Rainfall-Displacement Correlation ===
    renderRainfallCorrelationSection(data);

    // Multi-Window section removed per user request

    // === Cross-Sensor Consensus ===
    renderCrossConsensusSection(data);
}

function resetRainfallCorrelationUi() {
    const section = document.getElementById('rainfall-correlation-section');
    if (section) {
        section.style.display = 'none';
    }
    if (charts['chart-rainfall-correlation']) {
        charts['chart-rainfall-correlation'].destroy();
        delete charts['chart-rainfall-correlation'];
    }
    if (charts['chart-sm-model-index']) {
        charts['chart-sm-model-index'].destroy();
        delete charts['chart-sm-model-index'];
    }
}

function updateRainCorrelationAiControls(rainCorr = null) {
    const runBtn = document.getElementById('btn-run-rain-correlation');
    const hintEl = document.getElementById('rain-correlation-hint');
    if (!runBtn || !hintEl) return;

    const canRun = !!currentStationData;
    runBtn.disabled = !canRun || rainCorrelationAiRunning;

    if (rainCorrelationAiRunning) {
        runBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Đang chạy Slide model...';
        hintEl.textContent = 'Hệ thống đang phân tích tương quan mưa - dịch chuyển bằng Slide model.';
        return;
    }

    runBtn.innerHTML = '<i class="bi bi-stars me-2"></i>Chạy AI Slide model';

    if (!isRainCorrelationAiEnabled) {
        hintEl.textContent = 'Tương quan mưa - dịch chuyển chỉ phân tích khi bạn bấm nút AI Slide model.';
        return;
    }

    if (rainCorr && rainCorr.available) {
        hintEl.textContent = 'Đã chạy AI Slide model thành công cho khoảng thời gian đang chọn.';
        return;
    }

    hintEl.textContent = rainCorr?.message || 'Đã gửi yêu cầu AI Slide model, nhưng chưa có đủ dữ liệu để tính.';
}

function closeSlideModelResultPopup() {
    const overlay = document.getElementById('sm-model-popup-overlay');
    if (!overlay) return;
    overlay.classList.remove('active');
    overlay.setAttribute('aria-hidden', 'true');
}

function showSlideModelResultPopup(rainCorr) {
    const overlay = document.getElementById('sm-model-popup-overlay');
    const statusEl = document.getElementById('sm-model-popup-status');
    if (!overlay || !statusEl) return;

    const available = rainCorr?.available === true;
    const corr = Number(rainCorr?.correlation);
    const r2 = Number(rainCorr?.r_squared);
    const lag = Number(rainCorr?.lag_days);
    const trigger = String(rainCorr?.trigger_potential || 'LOW').toUpperCase();

    // --- Tab switching ---
    overlay.querySelectorAll('.sm-model-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            overlay.querySelectorAll('.sm-model-tab').forEach(t => t.classList.remove('active'));
            overlay.querySelectorAll('.sm-model-tab-pane').forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            const target = document.getElementById(tab.dataset.tab);
            if (target) target.classList.add('active');
        });
    });
    // Reset to first tab
    overlay.querySelectorAll('.sm-model-tab').forEach((t, i) => t.classList.toggle('active', i === 0));
    overlay.querySelectorAll('.sm-model-tab-pane').forEach((p, i) => p.classList.toggle('active', i === 0));

    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    const fmtDate = (d) => { if (!d) return '--'; try { const [y, m, dd] = d.split('-'); return `${dd}/${m}`; } catch { return d; } };

    if (available) {
        // === Overview tab ===
        setVal('sm-model-popup-r', Number.isFinite(corr) ? corr.toFixed(4) : '--');
        setVal('sm-model-popup-r2', Number.isFinite(r2) ? r2.toFixed(4) : '--');
        setVal('sm-model-popup-lag', Number.isFinite(lag) ? `${lag} ngày` : '--');
        setVal('sm-model-popup-trigger', trigger);
        setVal('sm-model-popup-strength', rainCorr?.strength || '--');
        setVal('sm-model-popup-slope', rainCorr?.slope_mm_day_per_rain_index != null
            ? Number(rainCorr.slope_mm_day_per_rain_index).toFixed(4) : '--');
        setVal('sm-model-popup-message', sanitizeLongTermText(
            rainCorr?.risk_message || rainCorr?.message || rainCorr?.assessment || 'Slide model hoàn tất.'
        ));

        // Status badge
        if (trigger === 'HIGH') {
            statusEl.className = 'sm-model-popup-status status-fail';
            statusEl.textContent = '🚨 TRIGGER: HIGH';
        } else if (trigger === 'MEDIUM') {
            statusEl.className = 'sm-model-popup-status status-warn';
            statusEl.textContent = '⚠️ TRIGGER: MEDIUM';
        } else {
            statusEl.className = 'sm-model-popup-status status-ok';
            statusEl.textContent = '✅ TRIGGER: LOW';
        }

        // === Rain stats tab ===
        const rs = rainCorr?.rain_stats || {};
        setVal('sm-model-rain-total', rs.total_mm != null ? `${rs.total_mm} mm` : '--');
        setVal('sm-model-rain-max', rs.max_daily_mm != null ? `${rs.max_daily_mm} mm` : '--');
        setVal('sm-model-rain-max-day', fmtDate(rs.max_rain_day));
        setVal('sm-model-rain-days', rs.rain_days != null ? `${rs.rain_days} ngày` : '--');
        setVal('sm-model-dry-days', rs.dry_days != null ? `${rs.dry_days} ngày` : '--');
        setVal('sm-model-rain-avg', rs.avg_rain_on_rainy_days_mm != null ? `${rs.avg_rain_on_rainy_days_mm} mm` : '--');
        setVal('sm-model-idx-max', rs.max_slide_model_index != null ? rs.max_slide_model_index.toFixed(2) : '--');
        setVal('sm-model-idx-mean', rs.mean_slide_model_index != null ? rs.mean_slide_model_index.toFixed(2) : '--');
        setVal('sm-model-common-days', rainCorr?.common_days != null ? `${rainCorr.common_days} ngày` : '--');

        // === Displacement stats tab ===
        const ds = rainCorr?.disp_stats || {};
        setVal('sm-model-disp-total', ds.total_mm != null ? `${ds.total_mm} mm` : '--');
        setVal('sm-model-disp-max', ds.max_daily_mm != null ? `${ds.max_daily_mm} mm` : '--');
        setVal('sm-model-disp-max-day', fmtDate(ds.max_disp_day));
        setVal('sm-model-disp-avg', ds.avg_daily_mm != null ? `${ds.avg_daily_mm} mm` : '--');
        setVal('sm-model-disp-rain', ds.disp_during_rain_mm != null ? `${ds.disp_during_rain_mm} mm` : '--');
        setVal('sm-model-disp-dry', ds.disp_during_dry_mm != null ? `${ds.disp_during_dry_mm} mm` : '--');
        setVal('sm-model-accel-ratio', ds.rain_acceleration_ratio != null
            ? `${ds.rain_acceleration_ratio}x` : '--');
        setVal('sm-model-sensitivity', rainCorr?.sensitivity_mm_per_mm != null
            ? `${rainCorr.sensitivity_mm_per_mm} mm/mm` : '--');

        // Lag scan summary
        const lagScan = rainCorr?.lag_scan || [];
        if (lagScan.length > 0) {
            const lagText = lagScan.map(l => `L${l.lag}:${l.correlation}`).join(' | ');
            setVal('sm-model-lag-scan', lagText);
        } else {
            setVal('sm-model-lag-scan', '--');
        }

        // === Events tab: CWD ===
        const cwdEl = document.getElementById('sm-model-cwd-events');
        const cwdEvents = rainCorr?.cwd_events || [];
        if (cwdEl) {
            if (cwdEvents.length > 0) {
                cwdEl.innerHTML = cwdEvents.map(e => `
                    <div class="sm-model-event-item">
                        <div class="sm-model-event-header">
                            <span class="sm-model-event-date">${fmtDate(e.start)} → ${fmtDate(e.end)}</span>
                            <span class="sm-model-event-badge">${e.days} ngày</span>
                        </div>
                        <div class="sm-model-event-stats">
                            <span>🌧️ ${e.total_rain_mm} mm</span>
                            <span>📏 ${e.displacement_mm} mm</span>
                            <span>💧 TB ${e.avg_intensity} mm/ngày</span>
                        </div>
                    </div>
                `).join('');
            } else {
                cwdEl.innerHTML = '<div class="text-muted small">Không có đợt mưa liên tục ≥2 ngày</div>';
            }
        }

        // === Events tab: Peak rain ===
        const peakEl = document.getElementById('sm-model-peak-events');
        const peakEvents = rainCorr?.peak_rain_events || [];
        if (peakEl) {
            if (peakEvents.length > 0) {
                peakEl.innerHTML = peakEvents.map(e => `
                    <div class="sm-model-event-item">
                        <div class="sm-model-event-header">
                            <span class="sm-model-event-date">${fmtDate(e.date)}</span>
                            <span class="sm-model-event-badge sm-model-event-badge-danger">⚡ ${e.rain_mm} mm</span>
                        </div>
                        <div class="sm-model-event-stats">
                            <span>📏 Phản hồi: ${e.disp_response_mm} mm</span>
                            <span>📊 Index: ${e.slide_model_index}</span>
                        </div>
                    </div>
                `).join('');
            } else {
                peakEl.innerHTML = '<div class="text-muted small">Không có ngày mưa ≥20mm trong giai đoạn này</div>';
            }
        }

        // === Risk insights tab ===
        const riskEl = document.getElementById('sm-model-risk-insights');
        const riskInsights = rainCorr?.risk_insights || [];
        if (riskEl) {
            if (riskInsights.length > 0) {
                riskEl.innerHTML = riskInsights.map(msg => `
                    <div class="sm-model-insight-item">${msg}</div>
                `).join('');
            } else {
                riskEl.innerHTML = `<div class="sm-model-insight-item sm-model-insight-ok">
                    ✅ ${rainCorr?.assessment || 'Không phát hiện yếu tố rủi ro đặc biệt từ tương quan mưa.'}
                </div>`;
            }
        }

    } else {
        // Not available — reset all
        ['sm-model-popup-r', 'sm-model-popup-r2', 'sm-model-popup-lag', 'sm-model-popup-trigger',
            'sm-model-popup-strength', 'sm-model-popup-slope'].forEach(id => setVal(id, '--'));
        setVal('sm-model-popup-message', sanitizeLongTermText(
            rainCorr?.message || 'Không thể tạo kết quả Slide model cho khoảng thời gian này.'
        ));
        statusEl.className = 'sm-model-popup-status status-warn';
        statusEl.textContent = '⚠ CHƯA ĐỦ DỮ LIỆU';
    }

    overlay.classList.add('active');
    overlay.setAttribute('aria-hidden', 'false');
}

// Global references for 3D logic
let gnssScene, gnssCamera, gnssRenderer, gnssControls, gnssAnimationId;
let imuScene, imuCamera, imuRenderer, imuControls, imuAnimationId;

// Helper: wait until a container has non-zero dimensions (handles CSS transitions/display:none)
function waitForContainerSize(container, timeoutMs = 3000) {
    return new Promise((resolve) => {
        if (container.clientWidth > 0 && container.clientHeight > 0) {
            resolve(true);
            return;
        }
        const start = Date.now();
        const check = () => {
            if (container.clientWidth > 0 && container.clientHeight > 0) {
                resolve(true);
            } else if (Date.now() - start > timeoutMs) {
                console.warn('[3D] Container still has 0 size after timeout, using fallback');
                resolve(false);
            } else {
                requestAnimationFrame(check);
            }
        };
        requestAnimationFrame(check);
    });
}

// Helper: get container dimensions with fallback
function getContainerDims(container) {
    let w = container.clientWidth;
    let h = container.clientHeight;
    if (w <= 0 || h <= 0) {
        // Fallback: use style dimensions or parent
        const rect = container.getBoundingClientRect();
        w = rect.width > 0 ? rect.width : 600;
        h = rect.height > 0 ? rect.height : 350;
    }
    return { w, h };
}

async function init3DVisualizations(data) {
    try {
        const THREE = await import('three');
        _THREE = THREE; // Cache for realtime updates
        const { OrbitControls } = await import('three/addons/controls/OrbitControls.js');

        // GNSS
        if (data.gnss && data.gnss.status === 'success' && data.gnss.time_series) {
            const gnssLoading = document.getElementById('gnss-3d-loading');
            if (gnssLoading) gnssLoading.style.display = 'block';
            const gnssContainer = document.getElementById('container-3d-gnss');
            // Wait for container to become visible (overlay transition)
            await waitForContainerSize(gnssContainer, 2000);
            setTimeout(() => {
                initGNSS3D(data.gnss.time_series, THREE, OrbitControls);
                if (gnssLoading) gnssLoading.style.display = 'none';
            }, 100);
        } else {
            const cGnss = document.getElementById('container-3d-gnss');
            if (cGnss) cGnss.innerHTML = '<div class="text-muted d-flex h-100 align-items-center justify-content-center">Không có dữ liệu GNSS 3D</div>';
        }

        // IMU
        if (data.imu && data.imu.status === 'success' && data.imu.time_series) {
            const imuLoading = document.getElementById('imu-3d-loading');
            if (imuLoading) imuLoading.style.display = 'block';
            const imuContainer = document.getElementById('container-3d-imu');
            // Wait for container to become visible (overlay transition)
            await waitForContainerSize(imuContainer, 2000);
            setTimeout(() => {
                initIMU3D(data.imu.time_series, THREE, OrbitControls);
                if (imuLoading) imuLoading.style.display = 'none';
            }, 100);
        } else {
            const cImu = document.getElementById('container-3d-imu');
            if (cImu) cImu.innerHTML = '<div class="text-muted d-flex h-100 align-items-center justify-content-center">Không có dữ liệu IMU 3D</div>';
        }

    } catch (error) {
        console.error("Failed to load Three.js:", error);
    }
}

function initGNSS3D(timeSeries, THREE, OrbitControls) {
    const container = document.getElementById('container-3d-gnss');
    if (!container) return;

    // Cleanup previous
    if (gnssAnimationId) cancelAnimationFrame(gnssAnimationId);
    container.innerHTML = '';

    gnssScene = new THREE.Scene();
    gnssScene.background = new THREE.Color(0x0a0e17);

    const dims = getContainerDims(container);
    const aspect = dims.w / dims.h;
    gnssCamera = new THREE.PerspectiveCamera(50, aspect, 0.1, 1000);
    gnssCamera.position.set(10, 10, 10);

    gnssRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    gnssRenderer.setSize(dims.w, dims.h);
    container.appendChild(gnssRenderer.domElement);

    gnssControls = new OrbitControls(gnssCamera, gnssRenderer.domElement);
    gnssControls.enableDamping = true;
    gnssControls.dampingFactor = 0.05;

    // Grid and Axes
    const gridHelper = new THREE.GridHelper(50, 50, 0x444444, 0x222222);
    gnssScene.add(gridHelper);

    const axesHelper = new THREE.AxesHelper(5);
    // Red=X(East), Green=Y(Up), Blue=Z(North)
    gnssScene.add(axesHelper);

    // Data points
    const e = timeSeries.e || [];
    const n = timeSeries.n || [];
    const u = timeSeries.u || [];

    // Default fallback if e,n,u missing
    if (!e.length && timeSeries.displacement) {
        // Just make a dummy random path if backend didn't update yet
        for (let i = 0; i < timeSeries.displacement.length; i++) {
            e.push(i * 2); n.push(Math.sin(i) * 2); u.push(Math.cos(i) * 2);
        }
    }

    if (e.length === 0) return;

    // Normalize scale to fit nicely in view
    let maxVal = 0.01;
    for (let i = 0; i < e.length; i++) {
        maxVal = Math.max(maxVal, Math.abs(e[i]), Math.abs(n[i]), Math.abs(u[i]));
    }
    const scaleFactor = 5 / maxVal;

    // Create Path Line
    const points = [];
    for (let i = 0; i < e.length; i++) {
        // Note: in ThreeJS, Y is up. Data usually has E=X, N=Y, U=Z or similar.
        // We'll map E -> X, U -> Y, N -> Z (standard right handed, Y up)
        points.push(new THREE.Vector3(e[i] * scaleFactor, u[i] * scaleFactor, -n[i] * scaleFactor));
    }

    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({ color: 0x0ea5e9, linewidth: 2 });
    const line = new THREE.Line(geometry, material);
    gnssScene.add(line);

    // Current point sphere
    const sphereGeo = new THREE.SphereGeometry(0.3, 16, 16);
    const sphereMat = new THREE.MeshBasicMaterial({ color: 0xff0000 });
    const sphere = new THREE.Mesh(sphereGeo, sphereMat);
    gnssScene.add(sphere);

    // Analysis mode: keep marker at the latest GNSS position (no autoplay movement).
    if (points.length > 0) {
        sphere.position.copy(points[points.length - 1]);
    }

    function animate() {
        gnssAnimationId = requestAnimationFrame(animate);

        gnssControls.update();
        gnssRenderer.render(gnssScene, gnssCamera);
    }
    animate();

    // Resize handler + ResizeObserver for proper sizing after CSS transitions
    function handleGnssResize() {
        if (!container || !gnssRenderer || !gnssCamera) return;
        const d = getContainerDims(container);
        gnssCamera.aspect = d.w / d.h;
        gnssCamera.updateProjectionMatrix();
        gnssRenderer.setSize(d.w, d.h);
    }
    window.addEventListener('resize', handleGnssResize);
    if (typeof ResizeObserver !== 'undefined') {
        const gnssRo = new ResizeObserver(() => handleGnssResize());
        gnssRo.observe(container);
    }
}

function initIMU3D(timeSeries, THREE, OrbitControls) {
    const container = document.getElementById('container-3d-imu');
    if (!container) return;

    if (imuAnimationId) cancelAnimationFrame(imuAnimationId);
    container.innerHTML = '';

    imuScene = new THREE.Scene();
    // Premium dark gradient background - we'll just use a color but add fog
    imuScene.background = new THREE.Color(0x0b0e14);
    imuScene.fog = new THREE.FogExp2(0x0b0e14, 0.03);

    const dims = getContainerDims(container);
    const aspect = dims.w / dims.h;
    imuCamera = new THREE.PerspectiveCamera(45, aspect, 0.1, 100);
    imuCamera.position.set(5, 6, 8);

    imuRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    imuRenderer.setPixelRatio(window.devicePixelRatio);
    imuRenderer.setSize(dims.w, dims.h);
    imuRenderer.shadowMap.enabled = true;
    imuRenderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container.appendChild(imuRenderer.domElement);

    imuControls = new OrbitControls(imuCamera, imuRenderer.domElement);
    imuControls.enableDamping = true;
    imuControls.dampingFactor = 0.05;
    imuControls.maxPolarAngle = Math.PI / 2 + 0.1; // Limit below ground
    imuControls.minDistance = 3;
    imuControls.maxDistance = 15;

    // Advanced Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    imuScene.add(ambientLight);

    const hemiLight = new THREE.HemisphereLight(0xddeeff, 0x0f0e1d, 0.5);
    imuScene.add(hemiLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
    dirLight.position.set(5, 10, 7);
    dirLight.castShadow = true;
    dirLight.shadow.mapSize.width = 1024;
    dirLight.shadow.mapSize.height = 1024;
    dirLight.shadow.camera.near = 0.5;
    dirLight.shadow.camera.far = 25;
    dirLight.shadow.camera.left = -5;
    dirLight.shadow.camera.right = 5;
    dirLight.shadow.camera.top = 5;
    dirLight.shadow.camera.bottom = -5;
    dirLight.shadow.bias = -0.001;
    imuScene.add(dirLight);

    const pointLight = new THREE.PointLight(0x00e5ff, 2, 8);
    pointLight.position.set(0, 1.5, 0);
    imuScene.add(pointLight);

    // Floor with grid
    const floorGeo = new THREE.PlaneGeometry(30, 30);
    const floorMat = new THREE.MeshStandardMaterial({
        color: 0x0b0e14,
        roughness: 0.8,
        metalness: 0.2
    });
    const floor = new THREE.Mesh(floorGeo, floorMat);
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -1.5;
    floor.receiveShadow = true;
    imuScene.add(floor);

    const grid = new THREE.GridHelper(30, 30, 0x00e5ff, 0x222233);
    grid.position.y = -1.49;
    grid.material.opacity = 0.15;
    grid.material.transparent = true;
    imuScene.add(grid);

    // ==========================================
    // REALISTIC IMU BLACK BOX MOUNT DESIGN
    // ==========================================
    const sensorBlock = new THREE.Group();

    // 1. Silver Base Plate (Circular)
    const plateRadius = 2.0;
    const plateThickness = 0.1;
    const plateGeo = new THREE.CylinderGeometry(plateRadius, plateRadius, plateThickness, 32);
    const plateMat = new THREE.MeshStandardMaterial({
        color: 0xcccccc, // Silver
        metalness: 0.8,
        roughness: 0.3
    });
    const plate = new THREE.Mesh(plateGeo, plateMat);
    plate.position.y = plateThickness / 2;
    plate.castShadow = true;
    plate.receiveShadow = true;
    sensorBlock.add(plate);

    // 2. The Black IMU Box (Main Sensor)
    const boxWidth = 2.2;
    const boxHeight = 1.0;
    const boxDepth = 2.2;
    const boxGeo = new THREE.BoxGeometry(boxWidth, boxHeight, boxDepth);
    const boxMat = new THREE.MeshStandardMaterial({
        color: 0x111111, // Flat black
        metalness: 0.2,
        roughness: 0.8,
        bumpScale: 0.02
    });
    const imuBox = new THREE.Mesh(boxGeo, boxMat);
    imuBox.position.y = plateThickness + boxHeight / 2;
    imuBox.castShadow = true;
    imuBox.receiveShadow = true;
    sensorBlock.add(imuBox);

    // 3. Direction Indicator (Simple white arrow on top of black box)
    const arrowGeo = new THREE.ConeGeometry(0.15, 0.4, 16);
    const arrowMat = new THREE.MeshStandardMaterial({ color: 0xffffff });
    const arrow = new THREE.Mesh(arrowGeo, arrowMat);
    // Point it forward (along Z axis)
    arrow.rotation.x = Math.PI / 2;
    arrow.position.set(0, plateThickness + boxHeight + 0.05, boxDepth / 2 - 0.3);
    sensorBlock.add(arrow);

    // 4. Mounting Screws on the plate
    // 4. Mounting Screws on the plate — cardinal positions (N/S/E/W)
    const screwGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.15, 16);
    const screwMat = new THREE.MeshStandardMaterial({ color: 0x999999, metalness: 0.9, roughness: 0.2 });
    const screwRadius = plateRadius - 0.3;

    for (let i = 0; i < 4; i++) {
        const angle = (i * Math.PI) / 2; // 0°, 90°, 180°, 270° → mỗi mặt
        const screw = new THREE.Mesh(screwGeo, screwMat);
        screw.position.set(Math.cos(angle) * screwRadius, plateThickness, Math.sin(angle) * screwRadius);
        sensorBlock.add(screw);
    }

    // 5. Add visual XYZ axis indicators
    const origin = new THREE.Vector3(0, plateThickness + boxHeight + 0.2, 0);
    const xArrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), origin, 1.2, 0xff2a5f, 0.2, 0.15); // Red X
    const yArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), origin, 1.2, 0x00e5ff, 0.2, 0.15); // Cyan Y (Up)
    const zArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), origin, 1.2, 0x00ff88, 0.2, 0.15); // Green Z
    sensorBlock.add(xArrow, yArrow, zArrow);

    imuScene.add(sensorBlock);

    // ==========================================
    // GUY WIRES — 4 cáp neo thể hiện hướng lệch
    // ==========================================
    const _gwDist = 5.5;
    const _gwFloor = -1.49;
    const _gwScrewR = plateRadius - 0.3;
    const _gwSpecs = [
        { local: new THREE.Vector3(_gwScrewR, plateThickness, 0), anchor: [_gwDist, _gwFloor, 0], color: 0xff6b35 }, // Roll+
        { local: new THREE.Vector3(-_gwScrewR, plateThickness, 0), anchor: [-_gwDist, _gwFloor, 0], color: 0xff6b35 }, // Roll-
        { local: new THREE.Vector3(0, plateThickness, _gwScrewR), anchor: [0, _gwFloor, _gwDist], color: 0x00d4ff }, // Pitch+
        { local: new THREE.Vector3(0, plateThickness, -_gwScrewR), anchor: [0, _gwFloor, -_gwDist], color: 0x00d4ff }, // Pitch-
    ];
    const imuWires = _gwSpecs.map(spec => {
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
        const mat = new THREE.LineBasicMaterial({ color: spec.color, linewidth: 2 });
        const line = new THREE.Line(geo, mat);
        imuScene.add(line);
        // Anchor peg
        const peg = new THREE.Mesh(
            new THREE.CylinderGeometry(0.08, 0.08, 0.25, 8),
            new THREE.MeshStandardMaterial({ color: spec.color, metalness: 0.7, roughness: 0.3, emissive: spec.color, emissiveIntensity: 0.25 })
        );
        peg.position.set(spec.anchor[0], _gwFloor + 0.12, spec.anchor[2]);
        imuScene.add(peg);
        return { line, local: spec.local, anchor: new THREE.Vector3(...spec.anchor) };
    });

    // Data parsing (backend sends 'rolls'/'pitches' plural)
    const rollData = timeSeries.rolls || timeSeries.roll || [];
    const pitchData = timeSeries.pitches || timeSeries.pitch || [];

    // Analysis mode: use the latest tilt sample and keep IMU model static.
    const hasTilt = rollData.length > 0 && pitchData.length > 0;
    if (hasTilt) {
        const lastIdx = Math.min(rollData.length, pitchData.length) - 1;
        const finalPitch = (pitchData[lastIdx] || 0) * Math.PI / 180;
        const finalRoll = (rollData[lastIdx] || 0) * Math.PI / 180;
        const finalQ = new THREE.Quaternion();
        finalQ.setFromEuler(new THREE.Euler(finalPitch, 0, finalRoll, 'XYZ'));
        sensorBlock.quaternion.copy(finalQ);
    }

    function animate() {
        imuAnimationId = requestAnimationFrame(animate);

        // Cập nhật guy wires
        sensorBlock.updateMatrixWorld();
        imuWires.forEach(w => {
            const wp = w.local.clone().applyMatrix4(sensorBlock.matrixWorld);
            const attr = w.line.geometry.attributes.position;
            attr.setXYZ(0, wp.x, wp.y, wp.z);
            attr.setXYZ(1, w.anchor.x, w.anchor.y, w.anchor.z);
            attr.needsUpdate = true;
        });
        imuControls.update();
        imuRenderer.render(imuScene, imuCamera);
    }
    animate();

    // Resize handler + ResizeObserver for proper sizing after CSS transitions
    function handleImuResize() {
        if (!container || !imuRenderer || !imuCamera) return;
        const d = getContainerDims(container);
        imuCamera.aspect = d.w / d.h;
        imuCamera.updateProjectionMatrix();
        imuRenderer.setSize(d.w, d.h);
    }
    window.addEventListener('resize', handleImuResize);
    if (typeof ResizeObserver !== 'undefined') {
        const imuRo = new ResizeObserver(() => handleImuResize());
        imuRo.observe(container);
    }
}

async function initRealtimeIMU3D(initialRoll, initialPitch) {
    const container = document.getElementById('realtime-imu-3d-scene');
    if (!container) return;

    if (realtimeImuAnimationId) cancelAnimationFrame(realtimeImuAnimationId);
    container.innerHTML = '';

    try {
        const THREE = await import('three');
        _THREE = THREE; // Cache for realtime updates
        const { OrbitControls } = await import('three/addons/controls/OrbitControls.js');

        realtimeImuScene = new THREE.Scene();
        realtimeImuScene.background = new THREE.Color(0x0b0e14);
        realtimeImuScene.fog = new THREE.FogExp2(0x0b0e14, 0.03);

        // Wait for wrapper to be visible before measuring
        await waitForContainerSize(container, 2000);
        const dims = getContainerDims(container);
        const aspect = dims.w / dims.h;
        realtimeImuCamera = new THREE.PerspectiveCamera(45, aspect, 0.1, 100);
        realtimeImuCamera.position.set(5, 6, 8);

        realtimeImuRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        realtimeImuRenderer.setPixelRatio(window.devicePixelRatio);
        realtimeImuRenderer.setSize(dims.w, dims.h);
        realtimeImuRenderer.shadowMap.enabled = true;
        realtimeImuRenderer.shadowMap.type = THREE.PCFSoftShadowMap;
        container.appendChild(realtimeImuRenderer.domElement);

        realtimeImuControls = new OrbitControls(realtimeImuCamera, realtimeImuRenderer.domElement);
        realtimeImuControls.enableDamping = true;
        realtimeImuControls.dampingFactor = 0.05;
        realtimeImuControls.maxPolarAngle = Math.PI / 2 + 0.1;
        realtimeImuControls.minDistance = 3;
        realtimeImuControls.maxDistance = 15;

        // Advanced Lighting
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
        realtimeImuScene.add(ambientLight);

        const hemiLight = new THREE.HemisphereLight(0xddeeff, 0x0f0e1d, 0.5);
        realtimeImuScene.add(hemiLight);

        const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
        dirLight.position.set(5, 10, 7);
        dirLight.castShadow = true;
        realtimeImuScene.add(dirLight);

        const pointLight = new THREE.PointLight(0x00e5ff, 2, 8);
        pointLight.position.set(0, 1.5, 0);
        realtimeImuScene.add(pointLight);

        // Floor
        const floorGeo = new THREE.PlaneGeometry(30, 30);
        const floorMat = new THREE.MeshStandardMaterial({
            color: 0x0b0e14, roughness: 0.8, metalness: 0.2
        });
        const floor = new THREE.Mesh(floorGeo, floorMat);
        floor.rotation.x = -Math.PI / 2;
        floor.position.y = -1.5;
        floor.receiveShadow = true;
        realtimeImuScene.add(floor);

        const grid = new THREE.GridHelper(30, 30, 0x00e5ff, 0x222233);
        grid.position.y = -1.49;
        grid.material.opacity = 0.15;
        grid.material.transparent = true;
        realtimeImuScene.add(grid);

        // Realistic IMU mounting
        realtimeImuSensorBlock = new THREE.Group();

        // Base Plate
        const plateRadius = 2.0;
        const plateThickness = 0.1;
        const plateGeo = new THREE.CylinderGeometry(plateRadius, plateRadius, plateThickness, 32);
        const plateMat = new THREE.MeshStandardMaterial({ color: 0xcccccc, metalness: 0.8, roughness: 0.3 });
        const plate = new THREE.Mesh(plateGeo, plateMat);
        plate.position.y = plateThickness / 2;
        plate.castShadow = true;
        plate.receiveShadow = true;
        realtimeImuSensorBlock.add(plate);

        // IMU Box
        const boxWidth = 2.2;
        const boxHeight = 1.0;
        const boxDepth = 2.2;
        const boxGeo = new THREE.BoxGeometry(boxWidth, boxHeight, boxDepth);
        const boxMat = new THREE.MeshStandardMaterial({ color: 0x111111, metalness: 0.2, roughness: 0.8 });
        const imuBox = new THREE.Mesh(boxGeo, boxMat);
        imuBox.position.y = plateThickness + boxHeight / 2;
        imuBox.castShadow = true;
        imuBox.receiveShadow = true;
        realtimeImuSensorBlock.add(imuBox);

        // Arrow
        const arrowGeo = new THREE.ConeGeometry(0.15, 0.4, 16);
        const arrowMat = new THREE.MeshStandardMaterial({ color: 0xffffff });
        const arrow = new THREE.Mesh(arrowGeo, arrowMat);
        arrow.rotation.x = Math.PI / 2;
        arrow.position.set(0, plateThickness + boxHeight + 0.05, boxDepth / 2 - 0.3);
        realtimeImuSensorBlock.add(arrow);

        // Screws
        // Screws — cardinal positions
        const screwGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.15, 16);
        const screwMat = new THREE.MeshStandardMaterial({ color: 0x999999, metalness: 0.9, roughness: 0.2 });
        const screwRadius = plateRadius - 0.3;
        for (let i = 0; i < 4; i++) {
            const angle = (i * Math.PI) / 2;
            const screw = new THREE.Mesh(screwGeo, screwMat);
            screw.position.set(Math.cos(angle) * screwRadius, plateThickness, Math.sin(angle) * screwRadius);
            realtimeImuSensorBlock.add(screw);
        }

        // Axes Support
        const origin = new THREE.Vector3(0, plateThickness + boxHeight + 0.2, 0);
        const xArrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), origin, 1.2, 0xff2a5f, 0.2, 0.15);
        const yArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), origin, 1.2, 0x00e5ff, 0.2, 0.15);
        const zArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), origin, 1.2, 0x00ff88, 0.2, 0.15);
        realtimeImuSensorBlock.add(xArrow, yArrow, zArrow);

        realtimeImuScene.add(realtimeImuSensorBlock);

        // ==========================================
        // GUY WIRES — 4 cáp neo realtime
        // ==========================================
        const _rtGwDist = 5.5;
        const _rtGwFloor = -1.49;
        const _rtGwScrewR = plateRadius - 0.3;
        const _rtGwSpecs = [
            { local: new THREE.Vector3(_rtGwScrewR, plateThickness, 0), anchor: [_rtGwDist, _rtGwFloor, 0], color: 0xff6b35 },
            { local: new THREE.Vector3(-_rtGwScrewR, plateThickness, 0), anchor: [-_rtGwDist, _rtGwFloor, 0], color: 0xff6b35 },
            { local: new THREE.Vector3(0, plateThickness, _rtGwScrewR), anchor: [0, _rtGwFloor, _rtGwDist], color: 0x00d4ff },
            { local: new THREE.Vector3(0, plateThickness, -_rtGwScrewR), anchor: [0, _rtGwFloor, -_rtGwDist], color: 0x00d4ff },
        ];
        const rtImuWires = _rtGwSpecs.map(spec => {
            const geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
            const mat = new THREE.LineBasicMaterial({ color: spec.color, linewidth: 2 });
            const line = new THREE.Line(geo, mat);
            realtimeImuScene.add(line);
            const peg = new THREE.Mesh(
                new THREE.CylinderGeometry(0.08, 0.08, 0.25, 8),
                new THREE.MeshStandardMaterial({ color: spec.color, metalness: 0.7, roughness: 0.3, emissive: spec.color, emissiveIntensity: 0.25 })
            );
            peg.position.set(spec.anchor[0], _rtGwFloor + 0.12, spec.anchor[2]);
            realtimeImuScene.add(peg);
            return { line, local: spec.local, anchor: new THREE.Vector3(...spec.anchor) };
        });

        // Initial orientation
        const currPitch = initialPitch * Math.PI / 180;
        const currRoll = initialRoll * Math.PI / 180;
        realtimeImuTargetQuaternion = new THREE.Quaternion();
        const euler = new THREE.Euler(currPitch, 0, currRoll, 'XYZ');
        realtimeImuTargetQuaternion.setFromEuler(euler);

        function animate() {
            realtimeImuAnimationId = requestAnimationFrame(animate);

            if (realtimeImuTargetQuaternion) {
                realtimeImuSensorBlock.quaternion.slerp(realtimeImuTargetQuaternion, 0.1);
            }

            // Cập nhật guy wires realtime
            realtimeImuSensorBlock.updateMatrixWorld();
            rtImuWires.forEach(w => {
                const wp = w.local.clone().applyMatrix4(realtimeImuSensorBlock.matrixWorld);
                const attr = w.line.geometry.attributes.position;
                attr.setXYZ(0, wp.x, wp.y, wp.z);
                attr.setXYZ(1, w.anchor.x, w.anchor.y, w.anchor.z);
                attr.needsUpdate = true;
            });
            realtimeImuControls.update();
            realtimeImuRenderer.render(realtimeImuScene, realtimeImuCamera);
        }
        animate();

        // Resize handler + ResizeObserver for proper sizing
        function handleRealtimeImuResize() {
            if (!container || !realtimeImuRenderer || !realtimeImuCamera) return;
            const d = getContainerDims(container);
            realtimeImuCamera.aspect = d.w / d.h;
            realtimeImuCamera.updateProjectionMatrix();
            realtimeImuRenderer.setSize(d.w, d.h);
        }
        window.addEventListener('resize', handleRealtimeImuResize);
        if (typeof ResizeObserver !== 'undefined') {
            const rtImuRo = new ResizeObserver(() => handleRealtimeImuResize());
            rtImuRo.observe(container);
        }

    } catch (e) {
        console.error("ThreeJS not loaded for realtime IMU", e);
    }
}

function renderImuLongTermSection(imuData) {
    const nodataEl = document.getElementById('imu-longterm-nodata');
    const contentEl = document.getElementById('imu-longterm-content');

    if (!imuData || imuData.status !== 'success') {
        if (nodataEl) {
            nodataEl.style.display = 'block';
            const msgEl = document.getElementById('imu-nodata-msg');
            if (msgEl) msgEl.textContent = imuData?.message || 'Không đủ dữ liệu IMU để phân tích.';
        }
        if (contentEl) contentEl.style.display = 'none';
        return;
    }

    if (nodataEl) nodataEl.style.display = 'none';
    if (contentEl) contentEl.style.display = 'block';

    const analysis = imuData.analysis;

    // Warning banner
    const warningEl = document.getElementById('imu-longterm-warning');
    const warningTextEl = document.getElementById('imu-warning-text');
    if (imuData.risk_level === 'EXTREME' || imuData.risk_level === 'HIGH' || imuData.risk_level === 'MEDIUM') {
        warningEl.style.display = 'block';
        warningEl.className = `alert ${imuData.risk_level === 'EXTREME' ? 'alert-danger' : 'alert-warning'} mb-3`;
        warningTextEl.textContent = sanitizeLongTermText(imuData.warning_message);
    } else {
        warningEl.style.display = 'none';
    }

    // Metrics
    setText('lt-imu-tilt-change', `${safeNumber(analysis.total_tilt_change_deg, 2)}°`);
    setText('lt-imu-rate', `${safeNumber(analysis.avg_rate_deg_per_day, 4)}°/ngày`);
    setText('lt-imu-max-roll', `${safeNumber(analysis.max_roll_deg, 2)}°`);
    setText('lt-imu-max-pitch', `${safeNumber(analysis.max_pitch_deg, 2)}°`);
    setText('lt-imu-points', analysis.data_points || '--');
    setText('lt-imu-duration', formatDurationString(analysis.duration_days));

    // Trend
    const trendIcons = { 'accelerating': '', 'stable': '', 'decelerating': '' };
    const trendTexts = { 'accelerating': 'Đang tăng tốc', 'stable': 'Ổn định', 'decelerating': 'Đang giảm tốc' };
    document.getElementById('imu-trend-icon').textContent = trendIcons[analysis.trend] || '';
    document.getElementById('imu-trend-value').textContent = trendTexts[analysis.trend] || 'Không xác định';
}

// =========================================================================
// COMBINED LONG-TERM CHART (GNSS + IMU on dual Y-axes)
// =========================================================================
function renderCombinedLongTermChart(data) {
    const ctx = document.getElementById('chart-longterm-combined');
    if (!ctx) return;

    if (charts['chart-longterm-combined']) {
        charts['chart-longterm-combined'].destroy();
    }

    const datasets = [];
    let allLabels = [];
    let hasGnss = false;
    let hasImu = false;

    // GNSS displacement → left Y-axis
    const gnss = data.gnss;
    if (gnss && gnss.status === 'success' && gnss.time_series && gnss.time_series.labels.length > 0) {
        allLabels = gnss.time_series.labels;
        hasGnss = true;
        datasets.push({
            label: 'GNSS Displacement (mm)',
            data: gnss.time_series.displacement,
            borderColor: '#0ea5e9',
            backgroundColor: 'rgba(14, 165, 233, 0.08)',
            tension: 0.4,
            borderWidth: 2.5,
            fill: true,
            pointRadius: 3,
            pointHoverRadius: 5,
            yAxisID: 'y-gnss'
        });
    }

    // IMU roll/pitch → right Y-axis
    const imu = data.imu;
    if (imu && imu.status === 'success' && imu.time_series) {
        hasImu = true;
        // Use IMU labels if no GNSS labels, or merge
        if (allLabels.length === 0) {
            allLabels = imu.time_series.labels;
        }

        datasets.push({
            label: 'Roll (°)',
            data: imu.time_series.roll,
            borderColor: '#f59e0b',
            backgroundColor: 'transparent',
            tension: 0.4,
            borderWidth: 2,
            borderDash: [5, 3],
            fill: false,
            pointRadius: 2,
            pointHoverRadius: 4,
            yAxisID: 'y-imu'
        });

        datasets.push({
            label: 'Pitch (°)',
            data: imu.time_series.pitch,
            borderColor: '#8b5cf6',
            backgroundColor: 'transparent',
            tension: 0.4,
            borderWidth: 2,
            borderDash: [5, 3],
            fill: false,
            pointRadius: 2,
            pointHoverRadius: 4,
            yAxisID: 'y-imu'
        });
    }

    if (datasets.length === 0) return;

    // Build scales
    const scales = {
        x: {
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: 'var(--text-secondary)', maxRotation: 45 }
        }
    };

    if (hasGnss) {
        scales['y-gnss'] = {
            type: 'linear',
            position: 'left',
            title: { display: true, text: 'Displacement (mm)', color: '#0ea5e9' },
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: '#0ea5e9', callback: v => v + ' mm' }
        };
    }

    if (hasImu) {
        scales['y-imu'] = {
            type: 'linear',
            position: hasGnss ? 'right' : 'left',
            title: { display: true, text: 'Góc nghiêng (°)', color: '#f59e0b' },
            grid: { drawOnChartArea: !hasGnss, color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: '#f59e0b', callback: v => v + '°' }
        };
    }

    // If only IMU (no GNSS), reassign yAxisID to y-imu for consistency
    if (!hasGnss && hasImu) {
        datasets.forEach(ds => { ds.yAxisID = 'y-imu'; });
    }

    charts['chart-longterm-combined'] = new Chart(ctx, {
        type: 'line',
        data: { labels: allLabels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    display: true,
                    labels: { color: 'var(--text-primary)', usePointStyle: true, padding: 16 }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.85)',
                    padding: 12,
                    titleFont: { weight: 'bold' }
                }
            },
            scales
        }
    });
}



function showLongTermError(message) {
    document.getElementById('longterm-loading').style.display = 'none';
    document.getElementById('longterm-content').style.display = 'none';
    document.getElementById('longterm-error').style.display = 'block';

    const errorMessageEl = document.getElementById('error-message');
    if (errorMessageEl) {
        errorMessageEl.textContent = message;
    }
}

// =========================================================================
// INVERSE VELOCITY (FUKUZONO) SECTION
// =========================================================================
function renderInverseVelocitySection(data) {
    const section = document.getElementById('inverse-velocity-section');
    if (!section) return;

    const invVel = data.gnss?.inverse_velocity;
    if (!invVel || !invVel.available) {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';

    // Warning
    const warningEl = document.getElementById('inv-vel-warning');
    const warningTextEl = document.getElementById('inv-vel-warning-text');
    if (invVel.predicted_failure) {
        warningEl.style.display = 'block';
        warningTextEl.textContent = sanitizeLongTermText(invVel.message);
    } else {
        warningEl.style.display = 'none';
    }

    // Metrics
    setText('inv-vel-prediction', invVel.predicted_failure
        ? `Có — ${invVel.predicted_failure_date ? new Date(invVel.predicted_failure_date).toLocaleDateString('vi-VN') : ''}`
        : 'Không');
    setText('inv-vel-days', invVel.predicted_failure
        ? `~${invVel.days_to_failure} ngày`
        : 'N/A');
    setText('inv-vel-r2', invVel.r_squared !== undefined ? invVel.r_squared.toFixed(4) : '--');
    setText('inv-vel-confidence', invVel.confidence
        ? (invVel.confidence === 'high' ? 'Cao' : 'Trung bình')
        : sanitizeLongTermText(invVel.message) || '--');

    // Chart
    if (invVel.time_series) {
        const ctx = document.getElementById('chart-inverse-velocity');
        if (!ctx) return;
        if (charts['chart-inverse-velocity']) {
            charts['chart-inverse-velocity'].destroy();
        }

        charts['chart-inverse-velocity'] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: invVel.time_series.labels,
                datasets: [
                    {
                        label: 'hệ số (thời gian thực)',
                        data: invVel.time_series.inverse_velocity,
                        borderColor: '#ef4444',
                        backgroundColor: 'rgba(239, 68, 68, 0.1)',
                        tension: 0.3,
                        borderWidth: 2,
                        pointRadius: 3,
                        fill: true
                    },
                    {
                        label: 'Đường xu hướng',
                        data: invVel.time_series.trend_line,
                        borderColor: '#fbbf24',
                        borderWidth: 2,
                        borderDash: [8, 4],
                        pointRadius: 0,
                        fill: false
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        labels: { color: 'var(--text-primary)', usePointStyle: true }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(0,0,0,0.85)',
                        padding: 12
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: 'var(--text-secondary)' }
                    },
                    y: {
                        title: { display: true, text: '1/Velocity (day/mm)', color: '#ef4444' },
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: '#ef4444' }
                    }
                }
            }
        });
    }
}

// =========================================================================
// RAINFALL-DISPLACEMENT CORRELATION SECTION
// =========================================================================
function renderRainfallCorrelationSection(data) {
    const section = document.getElementById('rainfall-correlation-section');
    if (!section) return;

    const rainCorr = data.rainfall_correlation;

    // Nếu chưa bật AI Slide model thì ẩn section (chỉ hiện khi user đã bấm nút)
    if (!isRainCorrelationAiEnabled) {
        section.style.display = 'none';
        return;
    }

    if (!rainCorr || !rainCorr.available) {
        // Show the section with an informative status message instead of hiding it
        const msg = (rainCorr && rainCorr.message)
            ? rainCorr.message
            : 'Không đủ dữ liệu để chạy Slide model. Cần ít nhất 3 ngày chung giữa GNSS và cảm biến mưa.';
        section.style.display = 'block';
        section.innerHTML = `
            <h5 class="mb-3 text-info border-bottom pb-2">
                <i class="bi bi-cloud-rain me-2"></i>Tương quan Mưa - Dịch chuyển (Slide model v2)
            </h5>
            <div class="alert alert-warning d-flex align-items-start gap-2 mb-0" role="alert">
                <i class="bi bi-exclamation-triangle-fill flex-shrink-0 mt-1"></i>
                <div>
                    <strong>Không thể chạy phân tích Slide model</strong><br>
                    <span class="small">${msg}</span>
                </div>
            </div>`;
        return;
    }

    // Restore full section HTML in case it was replaced by the error state
    if (!document.getElementById('rain-correlation')) {
        section.innerHTML = `
            <h5 class="mb-3 text-info border-bottom pb-2">
                <i class="bi bi-cloud-rain me-2"></i>Tương quan Mưa - Dịch chuyển (Slide model v2)
            </h5>
            <div class="row g-3 mb-3">
                <div class="col-md-2 col-6">
                    <div class="longterm-metric-card">
                        <div class="text-muted small">Hệ số r</div>
                        <div class="fs-4 fw-bold text-info mt-1" id="rain-correlation">--</div>
                    </div>
                </div>
                <div class="col-md-2 col-6">
                    <div class="longterm-metric-card">
                        <div class="text-muted small">R²</div>
                        <div class="fs-5 fw-bold mt-1" id="rain-r2">--</div>
                    </div>
                </div>
                <div class="col-md-2 col-6">
                    <div class="longterm-metric-card">
                        <div class="text-muted small">Lag</div>
                        <div class="fs-5 fw-bold mt-1" id="rain-lag">--</div>
                    </div>
                </div>
                <div class="col-md-2 col-6">
                    <div class="longterm-metric-card">
                        <div class="text-muted small">Trigger</div>
                        <div class="fs-5 fw-bold mt-1" id="rain-trigger">--</div>
                    </div>
                </div>
                <div class="col-md-2 col-6">
                    <div class="longterm-metric-card">
                        <div class="text-muted small">Mức tương quan</div>
                        <div class="fs-5 fw-bold mt-1" id="rain-strength">--</div>
                    </div>
                </div>
                <div class="col-md-2 col-6">
                    <div class="longterm-metric-card">
                        <div class="text-muted small">Độ nhạy</div>
                        <div class="fs-5 fw-bold mt-1" id="rain-sensitivity">--</div>
                    </div>
                </div>
                <div class="col-md-12">
                    <div class="longterm-metric-card">
                        <div class="text-muted small">Nhận xét rủi ro</div>
                        <div class="fs-6 mt-1" id="rain-assessment">--</div>
                    </div>
                </div>
            </div>
            <div class="row g-3">
                <div class="col-md-6">
                    <div class="chart-box border-0 shadow-sm">
                        <div class="chart-title"><i class="bi bi-moisture me-2"></i>Mưa tích lũy vs Dịch chuyển tích lũy</div>
                        <div style="height: 350px; padding: 10px;">
                            <canvas id="chart-rainfall-correlation"></canvas>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="chart-box border-0 shadow-sm">
                        <div class="chart-title"><i class="bi bi-graph-up-arrow me-2"></i>Slide model Index vs Dịch chuyển ngày</div>
                        <div style="height: 350px; padding: 10px;">
                            <canvas id="chart-sm-model-index"></canvas>
                        </div>
                    </div>
                </div>
            </div>`;
    }

    section.style.display = 'block';

    // Metrics
    const corrVal = rainCorr.correlation;
    const corrColor = Math.abs(corrVal) >= 0.6 ? 'text-danger' : Math.abs(corrVal) >= 0.4 ? 'text-warning' : 'text-info';
    const corrEl = document.getElementById('rain-correlation');
    if (corrEl) {
        corrEl.textContent = corrVal.toFixed(4);
        corrEl.className = `fs-4 fw-bold mt-1 ${corrColor}`;
    }
    setText('rain-strength', rainCorr.strength || '--');
    setText('rain-r2', rainCorr.r_squared != null ? rainCorr.r_squared.toFixed(4) : '--');
    setText('rain-lag', rainCorr.lag_days != null ? `${rainCorr.lag_days} ngày` : '--');

    // Trigger with color
    const triggerEl = document.getElementById('rain-trigger');
    if (triggerEl) {
        const tp = String(rainCorr.trigger_potential || 'LOW').toUpperCase();
        triggerEl.textContent = tp;
        triggerEl.className = 'fs-5 fw-bold mt-1 ' + (tp === 'HIGH' ? 'text-danger' : tp === 'MEDIUM' ? 'text-warning' : 'text-success');
    }

    // Sensitivity
    setText('rain-sensitivity', rainCorr.sensitivity_mm_per_mm != null
        ? `${rainCorr.sensitivity_mm_per_mm} mm/mm` : '--');

    // Assessment — prioritize risk_message if present
    setText('rain-assessment', rainCorr.risk_message || rainCorr.assessment || '--');

    // Chart 1: Dual-axis — cumulative displacement + cumulative/daily rainfall
    if (rainCorr.time_series) {
        const ctx = document.getElementById('chart-rainfall-correlation');
        if (ctx) {
            if (charts['chart-rainfall-correlation']) {
                charts['chart-rainfall-correlation'].destroy();
            }

            charts['chart-rainfall-correlation'] = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: rainCorr.time_series.labels,
                    datasets: [
                        {
                            label: 'Dịch chuyển tích lũy (mm)',
                            data: rainCorr.time_series.cumulative_displacement_mm,
                            borderColor: '#0ea5e9',
                            backgroundColor: 'rgba(14, 165, 233, 0.08)',
                            tension: 0.4,
                            borderWidth: 2.5,
                            fill: true,
                            pointRadius: 2,
                            yAxisID: 'y-disp'
                        },
                        {
                            label: 'Mưa tích lũy (mm)',
                            data: rainCorr.time_series.cumulative_rainfall_mm,
                            borderColor: '#10b981',
                            backgroundColor: 'transparent',
                            tension: 0.4,
                            borderWidth: 2,
                            borderDash: [5, 3],
                            fill: false,
                            pointRadius: 2,
                            yAxisID: 'y-rain'
                        },
                        {
                            label: 'Mưa ngày (mm)',
                            type: 'bar',
                            data: rainCorr.time_series.daily_rainfall_mm,
                            backgroundColor: 'rgba(59, 130, 246, 0.3)',
                            borderColor: '#3b82f6',
                            borderWidth: 1,
                            yAxisID: 'y-rain'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    plugins: {
                        legend: {
                            labels: { color: 'var(--text-primary)', usePointStyle: true, padding: 16 }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0,0,0,0.85)',
                            padding: 12
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(255,255,255,0.05)' },
                            ticks: { color: 'var(--text-secondary)', maxRotation: 45 }
                        },
                        'y-disp': {
                            type: 'linear',
                            position: 'left',
                            title: { display: true, text: 'Dịch chuyển (mm)', color: '#0ea5e9' },
                            grid: { color: 'rgba(255,255,255,0.05)' },
                            ticks: { color: '#0ea5e9' }
                        },
                        'y-rain': {
                            type: 'linear',
                            position: 'right',
                            title: { display: true, text: 'Lượng mưa (mm)', color: '#10b981' },
                            grid: { drawOnChartArea: false },
                            ticks: { color: '#10b981' }
                        }
                    }
                }
            });
        }

        // Chart 2: Slide model Index vs Daily Displacement
        const ctx2 = document.getElementById('chart-sm-model-index');
        if (ctx2 && rainCorr.time_series.slide_model_index) {
            if (charts['chart-sm-model-index']) {
                charts['chart-sm-model-index'].destroy();
            }

            charts['chart-sm-model-index'] = new Chart(ctx2, {
                type: 'line',
                data: {
                    labels: rainCorr.time_series.labels,
                    datasets: [
                        {
                            label: 'Slide model Index',
                            data: rainCorr.time_series.slide_model_index,
                            borderColor: '#f59e0b',
                            backgroundColor: 'rgba(245, 158, 11, 0.1)',
                            tension: 0.4,
                            borderWidth: 2.5,
                            fill: true,
                            pointRadius: 2,
                            yAxisID: 'y-idx'
                        },
                        {
                            label: 'Dịch chuyển ngày (mm)',
                            data: rainCorr.time_series.daily_displacement_mm,
                            borderColor: '#ec4899',
                            backgroundColor: 'rgba(236, 72, 153, 0.08)',
                            tension: 0.3,
                            borderWidth: 2,
                            fill: true,
                            pointRadius: 2,
                            yAxisID: 'y-disp2'
                        },
                        {
                            label: 'Mưa hiệu dụng ngắn (mm)',
                            data: rainCorr.time_series.effective_rainfall_short_mm,
                            borderColor: 'rgba(34, 197, 94, 0.6)',
                            borderWidth: 1.5,
                            borderDash: [4, 2],
                            pointRadius: 0,
                            fill: false,
                            yAxisID: 'y-idx'
                        },
                        {
                            label: 'Mưa hiệu dụng dài (mm)',
                            data: rainCorr.time_series.effective_rainfall_long_mm,
                            borderColor: 'rgba(99, 102, 241, 0.6)',
                            borderWidth: 1.5,
                            borderDash: [8, 4],
                            pointRadius: 0,
                            fill: false,
                            yAxisID: 'y-idx'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    plugins: {
                        legend: {
                            labels: { color: 'var(--text-primary)', usePointStyle: true, padding: 12, font: { size: 11 } }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0,0,0,0.85)',
                            padding: 12
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(255,255,255,0.05)' },
                            ticks: { color: 'var(--text-secondary)', maxRotation: 45 }
                        },
                        'y-idx': {
                            type: 'linear',
                            position: 'left',
                            title: { display: true, text: 'Slide model Index', color: '#f59e0b' },
                            grid: { color: 'rgba(255,255,255,0.05)' },
                            ticks: { color: '#f59e0b' }
                        },
                        'y-disp2': {
                            type: 'linear',
                            position: 'right',
                            title: { display: true, text: 'Dịch chuyển ngày (mm)', color: '#ec4899' },
                            grid: { drawOnChartArea: false },
                            ticks: { color: '#ec4899' }
                        }
                    }
                }
            });
        }
    }
}

// =========================================================================
// MULTI-WINDOW ANALYSIS SECTION (CALENDAR INTERVALS)
// =========================================================================
function formatDisplacementString(valMm, decimals = 1) {
    const val = parseFloat(valMm) || 0;
    if (Math.abs(val) >= 10) {
        return `${(val / 10).toFixed(decimals)} cm`;
    }
    return `${val.toFixed(decimals)} mm`;
}

function formatRateWithUnit(valueMm, periodLabel) {
    const absValue = Math.abs(valueMm);
    if (absValue >= 1000) {
        return { value: valueMm / 1000, unit: `m/${periodLabel}`, decimals: 2 };
    }
    if (absValue >= 10) {
        return { value: valueMm / 10, unit: `cm/${periodLabel}`, decimals: 2 };
    }
    return { value: valueMm, unit: `mm/${periodLabel}`, decimals: 2 };
}

function formatLongTermVelocityDisplay(metrics) {
    if (metrics && metrics.velocity_reliable === false) {
        const minDurationDays = parseFloat(metrics.min_reliable_duration_days) || (1 / 24);
        return {
            text: `Chờ đủ ${formatDurationString(minDurationDays)}`,
            ciText: `(${metrics.reliability_message || 'Chưa đủ thời lượng quan sát để kết luận vận tốc trung bình.'})`
        };
    }

    const durationDays = parseFloat(metrics?.duration_days) || 0;
    const mmYear = parseFloat(metrics?.velocity_mm_year) || 0;
    const mmDay = parseFloat(metrics?.velocity_mm_day) || (mmYear / 365);
    const mmSecond = parseFloat(metrics?.velocity_mm_second) || (mmDay / 86400);
    const ciYear = parseFloat(metrics?.velocity_ci_95) || 0;

    let primary;
    let ciValue;

    if (durationDays > 0 && durationDays < (1 / 24)) {
        if (Math.abs(mmSecond) >= 1) {
            primary = formatRateWithUnit(mmSecond, 's');
            ciValue = ciYear / 31536000;
        } else {
            primary = formatRateWithUnit(mmDay / 24, 'giờ');
            ciValue = ciYear / 8760;
        }
    } else if (durationDays > 0 && durationDays < 1) {
        primary = formatRateWithUnit(mmDay / 24, 'giờ');
        ciValue = ciYear / 8760;
    } else if (durationDays > 0 && durationDays < 30) {
        primary = formatRateWithUnit(mmDay, 'ngày');
        ciValue = ciYear / 365;
    } else {
        primary = formatRateWithUnit(mmYear, 'năm');
        ciValue = ciYear;
    }

    return {
        text: `${primary.value.toFixed(primary.decimals)} ${primary.unit}`,
        ciText: `(Độ tin cậy xu hướng OLS: ±${Math.abs(ciValue / (primary.unit.startsWith('m/') ? 1000 : primary.unit.startsWith('cm/') ? 10 : 1)).toFixed(primary.decimals)} ${primary.unit})`
    };
}

function formatDurationString(durationDays) {
    if (!durationDays || durationDays <= 0) return '0 phút';

    if (durationDays < 1 / 24) { // less than 1 hour
        const minutes = Math.round(durationDays * 24 * 60);
        return `${minutes} phút`;
    } else if (durationDays < 1) { // less than 1 day
        const hours = Math.floor(durationDays * 24);
        const minutes = Math.round((durationDays * 24 - hours) * 60);
        return minutes > 0 ? `${hours} giờ ${minutes} phút` : `${hours} giờ`;
    } else { // 1 day or more
        const days = Math.floor(durationDays);
        if (days >= 365) {
            const years = Math.floor(days / 365);
            const remainingDays = days % 365;
            return remainingDays > 0 ? `${years} năm ${remainingDays} ngày` : `${years} năm`;
        } else if (days >= 30) {
            const months = Math.floor(days / 30);
            const remainingDays = days % 30;
            return remainingDays > 0 ? `${months} tháng ${remainingDays} ngày` : `${months} tháng`;
        } else {
            const hours = Math.round((durationDays - days) * 24);
            return hours > 0 && days < 7 ? `${days} ngày ${hours} giờ` : `${days} ngày`;
        }
    }
}

function renderMultiWindowSection(data) {
    const section = document.getElementById('multi-window-section');
    if (!section) return;

    const mw = data.multi_window;
    if (!mw || !mw.available) {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';

    // Acceleration alert
    const alertEl = document.getElementById('multi-window-alert');
    const alertTextEl = document.getElementById('multi-window-alert-text');
    const warningTextEl = document.getElementById('warning-text');
    const warningEl = document.getElementById('longterm-warning');

    if (mw.acceleration_alert) {
        alertEl.style.display = 'block';
        alertEl.className = `alert ${mw.acceleration_alert.type === 'rapid_acceleration' ? 'alert-danger' : 'alert-warning'} mb-3`;
        alertTextEl.textContent = mw.acceleration_alert.message;
    } else {
        alertEl.style.display = 'none';
        alertTextEl.textContent = '';
    }

    // Unify CUSUM and Fukuzono models into overall alert if any
    let unifiedMsg = [];
    if (data.gnss?.analysis?.cusum_change) unifiedMsg.push(data.gnss.analysis.cusum_message);
    if (data.inverse_velocity && data.inverse_velocity.predicted_failure) {
        unifiedMsg.push(`Fukuzono (Ngịch đảo Vận tốc) dự báo sụp lún trong ~${data.inverse_velocity.days_to_failure} ngày.`);
    }
    if (unifiedMsg.length > 0 && warningEl) {
        warningEl.style.display = 'block';
        warningEl.className = 'alert alert-danger mb-3';
        warningTextEl.innerHTML = `<strong>KẾT HỢP PHÂN TÍCH:</strong><br>${unifiedMsg.join('<br>')}`;
    }

    // Window cards
    const cardsContainer = document.getElementById('multi-window-cards');
    if (!cardsContainer) return;

    const typeIcons = { 'day': 'bi-clock-history', 'week': 'bi-calendar-week', 'month': 'bi-calendar-month', 'year': 'bi-calendar3' };
    const trendIcons = { 'accelerating': '↗️', 'stable': '➡️', 'decelerating': '↘️' };
    const trendTexts = { 'accelerating': 'Tăng tốc', 'stable': 'Ổn định', 'decelerating': 'Giảm tốc' };

    cardsContainer.innerHTML = (mw.windows || []).map(w => {
        const icon = typeIcons[w.window_days] || 'bi-calendar';
        const label = w.label || (w.window_days + ' ngày');
        if (w.status === 'preliminary') {
            return `
                <div class="col-md-4 mb-2">
                    <div class="longterm-metric-card h-100 is-preliminary">
                        <div class="text-muted small mb-2"><i class="bi ${icon} me-1"></i>${label}</div>
                        <div class="fs-6 fw-semibold text-secondary">${formatLongTermVelocityDisplay(w).text}</div>
                        <div class="metric-inline-warning"><i class="bi bi-shield-exclamation"></i>Dữ liệu chưa đủ tin cậy</div>
                        <div class="small mt-1">Dịch chuyển đầu-cuối: <strong class="text-info">${formatDisplacementString(w.displacement_mm, 1)}</strong></div>
                        <div class="small text-muted">${formatDurationString(w.duration_days)} quan sát, ${w.data_points} điểm dữ liệu</div>
                        <div class="small text-muted mt-1">${w.reliability_message || 'Chưa đủ thời lượng để kết luận vận tốc.'}</div>
                    </div>
                </div>`;
        }

        if (w.status !== 'success') {
            return `
                <div class="col-md-4 mb-2">
                    <div class="longterm-metric-card text-center opacity-50 h-100">
                        <div class="text-muted small"><i class="bi ${icon} me-1"></i>${label}</div>
                        <div class="fs-6 mt-1">Chưa đủ dữ liệu hoặc chưa qua mốc thời gian</div>
                    </div>
                </div>`;
        }

        return `
            <div class="col-md-4 mb-2">
                <div class="longterm-metric-card h-100">
                    <div class="text-muted small mb-2"><i class="bi ${icon} me-1"></i>${label}</div>
                    <div class="fs-4 fw-bold text-primary">${formatLongTermVelocityDisplay({ velocity_mm_day: w.velocity_mm_day, velocity_mm_year: w.velocity_mm_year, duration_days: w.duration_days }).text}</div>
                    <div class="small mt-1">Dịch chuyển đầu-cuối: <strong class="text-info">${formatDisplacementString(w.displacement_mm, 1)}</strong></div>
                    <div class="small">Xu hướng: ${trendIcons[w.trend] || ''} ${trendTexts[w.trend] || '--'}</div>
                    <div class="small text-muted">${formatDurationString(w.duration_days)} quan sát, ${w.data_points} điểm dữ liệu</div>
                </div>
            </div>`;
    }).join('');
}

// ============================================================================
// CROSS-SENSOR CONSENSUS SECTION
// ============================================================================
function renderCrossConsensusSection(data) {
    const section = document.getElementById('cross-consensus-section');
    if (!section) return;

    const cs = data.cross_sensor_consensus;
    if (!cs || !cs.available) {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';

    const banner = document.getElementById('consensus-banner');
    const badge = document.getElementById('consensus-badge');
    const summaryEl = document.getElementById('consensus-summary');
    const sensorsEl = document.getElementById('consensus-sensors-with-data');
    const trendEl = document.getElementById('consensus-trend-agreement');
    const notesEl = document.getElementById('consensus-notes');

    // Badge + banner colour
    const levelConfig = {
        STRONG: { cls: 'consensus-strong', icon: 'bi-check-circle-fill', label: 'Đồng thuận mạnh' },
        PARTIAL: { cls: 'consensus-partial', icon: 'bi-question-circle-fill', label: 'Đồng thuận một phần' },
        CONFLICT: { cls: 'consensus-conflict', icon: 'bi-exclamation-circle-fill', label: 'Mâu thuẫn cảm biến' },
        NONE: { cls: 'consensus-none', icon: 'bi-dash-circle-fill', label: 'Không có bất thường' },
        UNAVAILABLE: { cls: 'consensus-unknown', icon: 'bi-info-circle-fill', label: 'Chưa đủ dữ liệu' },
    };
    const cfg = levelConfig[cs.consensus_level] || levelConfig.UNAVAILABLE;

    banner.className = `consensus-banner mb-3 ${cfg.cls}`;
    badge.className = `consensus-badge ${cfg.cls}`;
    badge.innerHTML = `<i class="bi ${cfg.icon} me-1"></i>${cfg.label}`;
    summaryEl.textContent = cs.summary || '';

    // Sensor chips
    const sensorLabels = { gnss: 'GNSS', imu: 'IMU', rain: 'Mưa' };
    const alertingSet = new Set(cs.sensors_alerting || []);
    const corrobSet = new Set(cs.sensors_corroborating || []);
    const conflictSet = new Set(cs.sensors_conflicting || []);
    sensorsEl.innerHTML = (cs.sensors_with_data || []).map(s => {
        let extra = '';
        if (conflictSet.has(s)) extra = 'sensor-chip-conflict';
        else if (corrobSet.has(s)) extra = 'sensor-chip-ok';
        else if (alertingSet.has(s)) extra = 'sensor-chip-alert';
        return `<span class="sensor-chip ${extra}">${sensorLabels[s] || s}</span>`;
    }).join('');

    // Trend agreement
    const trendMap = {
        full: { text: 'Cùng xu hướng ✓', cls: 'text-success' },
        partial: { text: 'Một phần cùng hướng', cls: 'text-warning' },
        conflict: { text: 'Ngược hướng ⚠️', cls: 'text-danger' },
    };
    const tm = trendMap[cs.trend_agreement];
    if (tm) {
        trendEl.textContent = tm.text;
        trendEl.className = `fs-5 fw-bold mt-1 ${tm.cls}`;
    } else {
        trendEl.textContent = 'Chưa xác định';
        trendEl.className = 'fs-5 fw-bold mt-1 text-muted';
    }

    // Notes list
    notesEl.innerHTML = (cs.notes || []).map(n =>
        `<div class="consensus-note-item"><i class="bi bi-arrow-right-short me-1"></i>${n}</div>`
    ).join('');
}

function sanitizeLongTermText(text) {
    return String(text || '')
        .replace(/[📈✅📉🚨]/g, '')
        .replace(/\s{2,}/g, ' ')
        .trim();
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.innerText = val || '--';
}

function setHTML(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
}

function getLatestSensorTimestamp(data) {
    const sensors = data?.sensors || {};
    let latestTs = Number(data?.last_update || 0);

    for (const sensor of Object.values(sensors)) {
        const ts = Number(sensor?.latest_timestamp || 0);
        if (ts > latestTs) latestTs = ts;
    }
    return latestTs;
}

function formatAgeFromTimestamp(ts) {
    if (!ts) return '--';
    const now = Math.floor(Date.now() / 1000);
    const diff = Math.max(0, now - Number(ts));

    if (diff < 60) return `${diff} giây trước`;
    if (diff < 3600) return `${Math.floor(diff / 60)} phút trước`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} giờ trước`;
    return `${Math.floor(diff / 86400)} ngày trước`;
}

function renderStaleInfo(data, mqttConnected, latestSensorTs) {
    const staleEl = document.getElementById('st-stale-info');
    if (!staleEl) return;

    if (!latestSensorTs) {
        staleEl.style.display = 'none';
        staleEl.innerHTML = '';
        return;
    }

    const ageText = formatAgeFromTimestamp(latestSensorTs);
    const localTime = new Date(latestSensorTs * 1000).toLocaleString('vi-VN');

    if (!mqttConnected) {
        staleEl.innerHTML = `<span class="badge-label">MẤT KẾT NỐI</span> Dữ liệu cuối: ${ageText} (${localTime})`;
        staleEl.style.display = 'flex';
        return;
    }

    if (data.status === 'offline') {
        staleEl.innerHTML = `<span class="badge-label">NGOẠI TUYẾN</span> Dữ liệu cuối: ${ageText} (${localTime})`;
        staleEl.style.display = 'flex';
        return;
    }

    staleEl.style.display = 'none';
    staleEl.innerHTML = '';
}

// =========================================================================
// IMU DRIFT CALCULATION
// =========================================================================
function updateImuDrift(rollVal, pitchVal) {
    if (rollVal === null || rollVal === undefined || pitchVal === null || pitchVal === undefined || isNaN(parseFloat(rollVal)) || isNaN(parseFloat(pitchVal))) {
        setText('val-imu-drift-len', '-- cm');
        setText('val-imu-drift-dir', '(--)');
        return;
    }
    const r = parseFloat(rollVal) || 0;
    const p = parseFloat(pitchVal) || 0;
    const r_rad = r * Math.PI / 180;
    const p_rad = p * Math.PI / 180;

    // Using 1.0 meter (1000mm) as virtual pole length
    // Use sin for spatial spherical coordinates instead of tan to prevent overestimation
    const total_tilt_rad = Math.sqrt(r_rad * r_rad + p_rad * p_rad);
    const drift = 1000 * Math.sin(total_tilt_rad);

    const dx = 1000 * Math.sin(r_rad);
    const dy = 1000 * Math.sin(p_rad);

    let dir_text = "--";
    if (drift > 0.1) {
        let angle_deg = Math.atan2(dy, dx) * 180 / Math.PI;
        if (angle_deg < 0) angle_deg += 360;
        const dirs = ["Đ", "ĐB", "B", "TB", "T", "TN", "N", "ĐN"];
        const idx = Math.round(angle_deg / 45) % 8;
        dir_text = dirs[idx];
    }

    animateValue('val-imu-drift-len', drift / 10, 1, ' cm', true);
    setText('val-imu-drift-dir', `(${dir_text})`);
}

// =========================================================================
// SMOOTH ANIMATED VALUE SYSTEM
// =========================================================================

// Store previous numeric values for lerp interpolation
const _prevValues = {};
// Store ongoing animation frame IDs to cancel previous animations
const _animFrames = {};

/**
 * Smoothly animate a sensor value from its current displayed number to a new value.
 * Uses requestAnimationFrame for 60fps lerp interpolation.
 *
 * @param {string} id - DOM element ID
 * @param {number|string|null} newValue - New numeric value
 * @param {number} decimals - Decimal places to display
 * @param {string} unit - Unit string (e.g. 'mm/s', '°')
 * @param {boolean} textOnly - If true, set innerText instead of innerHTML (for elements without unit spans)
 */
function animateValue(id, newValue, decimals = 2, unit = '', textOnly = false) {
    const el = document.getElementById(id);
    if (!el) return;

    const numVal = parseFloat(newValue);
    if (isNaN(numVal) || newValue === null || newValue === undefined) {
        // Non-numeric → direct set
        if (textOnly) {
            el.innerText = `--${unit}`;
        } else {
            el.innerHTML = `--<span class="sensor-unit">${unit}</span>`;
        }
        return;
    }

    const prevVal = _prevValues[id];

    // If no previous value or same value, just set directly (no animation needed)
    if (prevVal === undefined || prevVal === numVal) {
        _prevValues[id] = numVal;
        if (textOnly) {
            el.innerText = `${numVal.toFixed(decimals)}${unit}`;
        } else {
            el.innerHTML = `${numVal.toFixed(decimals)}<span class="sensor-unit">${unit}</span>`;
        }
        return;
    }

    // Cancel any ongoing animation for this element
    if (_animFrames[id]) {
        cancelAnimationFrame(_animFrames[id]);
    }

    // Trigger CSS glow effect on the parent sensor-item
    flashUpdate(el);

    const startVal = prevVal;
    const diff = numVal - startVal;
    const duration = 400; // ms
    const startTime = performance.now();

    function step(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);

        // Ease-out cubic for smooth deceleration
        const eased = 1 - Math.pow(1 - progress, 3);
        const currentVal = startVal + diff * eased;

        if (textOnly) {
            el.innerText = `${currentVal.toFixed(decimals)}${unit}`;
        } else {
            el.innerHTML = `${currentVal.toFixed(decimals)}<span class="sensor-unit">${unit}</span>`;
        }

        if (progress < 1) {
            _animFrames[id] = requestAnimationFrame(step);
        } else {
            _prevValues[id] = numVal;
            delete _animFrames[id];
        }
    }

    _prevValues[id] = numVal;
    _animFrames[id] = requestAnimationFrame(step);
}

/**
 * Trigger CSS glow flash on a value element's parent sensor-item.
 */
function flashUpdate(el) {
    // Find closest sensor-item parent for the glow effect
    const sensorItem = el.closest('.sensor-item') || el.closest('.axis-value');
    if (sensorItem) {
        sensorItem.classList.remove('value-updated');
        // Force reflow to restart animation
        void sensorItem.offsetWidth;
        sensorItem.classList.add('value-updated');
    }
}

function filterStations(searchTerm) {
    const items = document.querySelectorAll('.station-item');
    const term = searchTerm.toLowerCase();

    items.forEach(item => {
        const text = item.textContent.toLowerCase();
        item.style.display = text.includes(term) ? 'block' : 'none';
    });
}

// =========================================================================
// SIREN TOGGLE BUTTON STATE MANAGEMENT
// =========================================================================

/**
 * Cập nhật trạng thái nút còi
 * @param {'idle'|'alerting'|'muted'|'offline'} state
 *   - idle: xám, disabled (mặc định, chưa có cảnh báo)
 *   - alerting: đỏ, nhấp nháy (đang cảnh báo, bấm để tắt còi)
 *   - muted: xanh (đã tắt còi, bấm để bật lại)
 *   - offline: xám đen, disabled (thiết bị Pi mất kết nối)
 */
function setSirenButtonState(state, target = null) {
    const sirenSection = document.getElementById('siren-sidebar-section');

    const btns = target
        ? document.querySelectorAll(`.btn-siren-toggle[data-target="${target}"]`)
        : document.querySelectorAll('.btn-siren-toggle');

    btns.forEach(btn => {
        btn.setAttribute('data-siren-state', state);
        const iconBase = btn.getAttribute('data-target') === 'pi_center' ? 'Center' : 'Point';

        switch (state) {
            case 'idle':
                btn.disabled = true;
                btn.classList.remove('btn-danger', 'btn-success');
                btn.classList.add('disabled', 'btn-secondary');
                btn.style.opacity = '0.5';
                btn.innerHTML = `<i class="bi bi-volume-mute-fill me-1"></i>${iconBase}`;
                break;
            case 'alerting':
                btn.disabled = false;
                btn.classList.remove('disabled', 'btn-success', 'btn-secondary');
                btn.classList.add('btn-danger');
                btn.style.opacity = '1';
                btn.innerHTML = `<i class="bi bi-volume-mute-fill me-1"></i>Mute ${iconBase}`;
                break;
            case 'muted':
                btn.disabled = false;
                btn.classList.remove('disabled', 'btn-danger', 'btn-secondary');
                btn.classList.add('btn-success');
                btn.style.opacity = '1';
                btn.innerHTML = `<i class="bi bi-volume-up-fill me-1"></i>On ${iconBase}`;
                break;
            case 'offline':
                btn.disabled = true;
                btn.classList.remove('btn-danger', 'btn-success');
                btn.classList.add('btn-secondary', 'disabled');
                btn.style.opacity = '0.5';
                btn.innerHTML = `<i class="bi bi-plug-fill me-1"></i>Offline`;
                break;
        }
    });
}

// =========================================================================
// ALERT BANNER SYSTEM
// =========================================================================

let currentAlertStationId = null;
let lastAlertKey = null;
let latestAlertByStation = {};
let alertBannerSnoozeUntil = {};
let acknowledgedAlertKeyByStation = {};
let bannerSuppressedUntilByStation = {};

// Map sensor_type từ backend → id của sensor card trong HTML
const SENSOR_CARD_IDS = {
    gnss: 'sensor-card-gnss',
    rain: 'sensor-card-rain',
    water: 'sensor-card-water',
    imu: 'sensor-card-imu',
};

function setSensorCardAlert(sensorType, level) {
    const cardId = SENSOR_CARD_IDS[sensorType];
    if (!cardId) return;
    const card = document.getElementById(cardId);
    if (!card) return;
    card.classList.remove('sensor-alert-warning', 'sensor-alert-critical');
    const effectiveLevel = String(sensorType || '').toLowerCase() === 'imu' ? 'CRITICAL' : level;
    const normalized = normalizeAlertLevel(effectiveLevel);
    if (normalized === 'WARNING') {
        card.classList.add('sensor-alert-warning');
    } else if (normalized === 'CRITICAL') {
        card.classList.add('sensor-alert-critical');
    }
}

function clearAllSensorCardAlerts() {
    Object.values(SENSOR_CARD_IDS).forEach(id => {
        const card = document.getElementById(id);
        if (card) card.classList.remove('sensor-alert-warning', 'sensor-alert-critical');
    });
}

function applySensorCardAlertsFromAssessment(data) {
    clearAllSensorCardAlerts();
    const activeAlerts = data?.risk_assessment?.active_alerts || [];
    activeAlerts.forEach(alert => {
        const sensorType = mapAlertCategoryToSensorType(alert.category);
        if (SENSOR_CARD_IDS[sensorType]) {
            setSensorCardAlert(sensorType, alert.level || data?.risk_assessment?.overall_risk || 'WARNING');
        }
    });
}

function showAlertBanner(alertData, options = {}) {
    if (currentMapMode === 'rescue') return;

    const banner = document.getElementById('alert-banner');
    if (!banner) return;

    const safeAlertData = normalizeIncomingAlert(alertData);
    if (isBannerSuppressed(safeAlertData.station_id)) return;

    // ✅ Lookup station info từ allStations (đã load sẵn)
    const station = allStations.find(s => s.id === safeAlertData.station_id);
    const stationName = station?.name || `Station #${safeAlertData.station_id}`;
    const stationCode = station?.station_code || '';

    const normalizedLevel = normalizeAlertLevel(safeAlertData.level || safeAlertData.risk_level);
    const alertKey = buildAlertKey(safeAlertData);

    // Cập nhật nội dung — luôn phản ánh mức cảnh báo hiện tại
    updateAlertBannerTheme(normalizedLevel);

    document.getElementById('alert-title').textContent =
        options.silent ? `⚠️ ALERT (persistent)` : `${normalizedLevel} ALERT!`;

    document.getElementById('alert-station').textContent =
        `Station: ${stationName} (${stationCode})`;

    document.getElementById('alert-message').textContent =
        ` • ${safeAlertData.message || 'Anomaly detected!'}`;

    // Lưu station ID
    currentAlertStationId = safeAlertData.station_id;
    alertBannerSnoozeUntil[safeAlertData.station_id] = 0;
    banner.dataset.alertKey = alertKey;

    // Hiển thị banner (không auto-dismiss, user phải ấn X hoặc Theo dõi)
    // Lưu ý: siren button state được quản lý bởi _showSirenIfAlerting / WS handler,
    // không set ở đây để tránh override trạng thái offline của từng pi device.
    banner.classList.add('show');
}

// =====================================================
// ALERT SOUND MANAGER
// Phát âm thanh liên tục (loop) khi WARNING hoặc CRITICAL.
// Chỉ dừng khi tất cả trạm trở về trạng thái bình thường.
// WARNING  → /static/sounds/system_health_warning.mp3 (loop)
// CRITICAL → /static/sounds/siren.mp3                 (loop)
// =====================================================
const AlertSoundManager = (() => {
    const SOUND_WARNING = '/static/sounds/siren.mp3';
    const SOUND_CRITICAL = '/static/sounds/siren.mp3';

    // Trạng thái âm thanh hiện tại: null | 'WARNING' | 'CRITICAL'
    let _currentLevel = null;
    let _audio = null;
    let _unlocked = false;

    // Theo dõi mức cảnh báo của từng trạm: { stationId: 'WARNING'|'CRITICAL'|null }
    const _stationLevels = {};

    function _getSoundFile(level) {
        return level === 'CRITICAL' ? SOUND_CRITICAL : SOUND_WARNING;
    }

    function _getHighestLevel() {
        const levels = Object.values(_stationLevels).filter(Boolean);
        if (levels.includes('CRITICAL')) return 'CRITICAL';
        if (levels.includes('WARNING')) return 'WARNING';
        return null;
    }

    function _stopAudio() {
        if (_audio) {
            try {
                _audio.pause();
                _audio.src = '';
            } catch (_) { }
            _audio = null;
        }
        _currentLevel = null;
    }

    function _startAudio(level) {
        const src = _getSoundFile(level);
        // Nếu đang phát đúng cấp độ rồi thì không làm gì
        if (_audio && _currentLevel === level) return;
        // Dừng âm thanh hiện tại trước
        _stopAudio();

        _currentLevel = level;
        _audio = new Audio(src);
        _audio.loop = true; // Phát liên tục

        _audio.play().catch(e => {
            console.warn('[AlertSoundManager] Autoplay blocked:', e);
            if (navigator.vibrate) navigator.vibrate([300, 140, 300]);
            window.toast?.warning(
                'Trình duyệt đang chặn âm thanh tự động. Hãy chạm màn hình một lần để bật còi cảnh báo.'
            );
            _audio = null;
            _currentLevel = null;
        });
        console.log(`🔊 [AlertSoundManager] Playing ${level} sound (loop):`, src);
    }

    /** Cập nhật trạng thái cảnh báo của một trạm và điều chỉnh âm thanh. */
    function setStationAlert(stationId, level) {
        // level: 'WARNING', 'CRITICAL', hoặc null (bình thường)
        if (level) {
            _stationLevels[stationId] = level;
        } else {
            delete _stationLevels[stationId];
        }
        _syncSound();
    }

    /** Xóa cảnh báo cho một trạm (về bình thường). */
    function clearStationAlert(stationId) {
        delete _stationLevels[stationId];
        _syncSound();
    }

    /** Đồng bộ âm thanh với mức cảnh báo cao nhất hiện có. */
    function _syncSound() {
        const highest = _getHighestLevel();
        if (!highest) {
            // Không còn trạm nào đang báo → dừng âm thanh
            if (_audio) {
                console.log('✅ [AlertSoundManager] All stations normal — stopping sound.');
                _stopAudio();
            }
        } else if (highest !== _currentLevel) {
            // Chuyển cấp độ (ví dụ WARNING → CRITICAL hoặc ngược lại)
            _startAudio(highest);
        }
        // Nếu highest === _currentLevel → âm thanh đang đúng, không làm gì
    }

    /** Unlock AudioContext sau tương tác người dùng lần đầu. */
    function unlock() {
        if (_unlocked) return;
        _unlocked = true;
        // Nếu đang có cảnh báo mà chưa phát được, thử lại
        const highest = _getHighestLevel();
        if (highest && !_audio) {
            _startAudio(highest);
        }
    }

    /** Tắt thủ công (nút Mute), không xóa trạng thái cảnh báo. */
    function mute() {
        _stopAudio();
        console.log('🔇 [AlertSoundManager] Muted by user.');
    }

    return { setStationAlert, clearStationAlert, unlock, mute };
})();

/**
 * Tương thích ngược — các nơi gọi playSiren() sẽ báo CRITICAL cho trạm hiện tại.
 * @param {string|number} [stationId]
 * @param {string} [level='CRITICAL']
 */
function playSiren(stationId, level) {
    const sid = stationId ?? currentAlertStationId;
    const lvl = level ?? 'CRITICAL';
    if (sid != null) {
        AlertSoundManager.setStationAlert(sid, lvl);
    } else {
        // Không biết trạm nào — vẫn kêu CRITICAL nhưng chỉ tạm (sẽ bị dừng khi status cập nhật)
        AlertSoundManager.setStationAlert('_unknown', lvl);
    }
}

function playAlertSound() {
    try {
        // Beep đơn giản dùng Web Audio API (dùng khi autoplay bị block)
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioContext.createOscillator();
        const gainNode = audioContext.createGain();
        oscillator.connect(gainNode);
        gainNode.connect(audioContext.destination);
        oscillator.frequency.value = 800;
        oscillator.type = 'sine';
        gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.5);
        oscillator.start(audioContext.currentTime);
        oscillator.stop(audioContext.currentTime + 0.5);
    } catch (e) {
        console.warn('⚠️ [ALERT] Sound not available:', e);
    }
}

// Setup event listeners cho Alert Banner
runWhenDomReady(() => {
    // Unlock AudioContext sau tương tác người dùng đầu tiên
    const unlockSirenAudio = () => AlertSoundManager.unlock();
    document.addEventListener('touchstart', unlockSirenAudio, { once: true, passive: true });
    document.addEventListener('pointerdown', unlockSirenAudio, { once: true, passive: true });
    document.addEventListener('click', unlockSirenAudio, { once: true, passive: true });

    // Nút "Theo dõi" → Zoom vào trạm + ẩn banner + hiện siren popup sau khi zoom xong
    const btnFollow = document.getElementById('btn-alert-follow');
    if (btnFollow) {
        btnFollow.addEventListener('click', async () => {
            if (!currentAlertStationId) return;

            const alertStationId = currentAlertStationId;
            const currentAlertKey = buildAlertKey(latestAlertByStation[alertStationId] || {
                station_id: alertStationId,
                level: document.getElementById('alert-banner')?.dataset?.alertLevel || 'WARNING'
            });
            if (currentAlertKey) {
                acknowledgedAlertKeyByStation[alertStationId] = currentAlertKey;
            }
            bannerSuppressedUntilByStation[alertStationId] = Date.now() + 5 * 60 * 1000;

            // 1. Ẩn banner ngay
            const banner = document.getElementById('alert-banner');
            if (banner) banner.classList.remove('show');

            // 2. Load dữ liệu trạm (skip zoom và siren — tự quản lý bên dưới)
            await selectStation(alertStationId, { skipZoom: true, skipSiren: true, skipBannerRestore: true });

            // 3. Zoom vào trạm
            if (markers[alertStationId]) {
                map.flyTo(markers[alertStationId].getLatLng(), 16, { duration: 1.5 });

                // 4. Hiện siren popup SAU KHI zoom xong
                map.once('moveend', () => {
                    if (currentStationData && currentStationData.id === alertStationId) {
                        _showSirenIfAlerting(alertStationId, currentStationData);
                    }
                });
            }
        });
    }

    // Nút "Đóng" → Chỉ ẩn banner, không zoom, không ảnh hưởng gì khác
    const btnDismiss = document.getElementById('btn-alert-dismiss');
    if (btnDismiss) {
        btnDismiss.addEventListener('click', () => {
            const banner = document.getElementById('alert-banner');
            if (banner) {
                const stationId = currentAlertStationId;
                if (stationId) {
                    alertBannerSnoozeUntil[stationId] = Date.now() + 10000;
                }
                banner.classList.remove('show');
                banner.classList.remove('level-warning', 'level-critical');
            }
        });
    }
});

window.mapManager = {
    loadLongTermAnalysis,
    safeNumber,
    updateRealtimeSensorValues,
    updateSidebarUI,
    showAlertBanner,
    playAlertSound,
    playSiren,
    setMarkerAlert,
    clearMarkerAlert,
    AlertSoundManager,
    charts
};

// --- GUEST RESCUE PICK ON MAP LOGIC ---
let isPickingRescueLocation = false;
let rescueMapClickListener = null;

window.enablePickOnMap = function () {
    if (!window.map || !window.rescueFormModal) return;

    // Tạm ẩn modal
    window.rescueFormModal.hide();

    // Đổi con trỏ chuột
    isPickingRescueLocation = true;
    document.getElementById('map').style.cursor = 'crosshair';
    window.toast?.info('Click vào Bản đồ để chốt Vị trí Cứu hộ', 5000);

    // Huỷ listener cũ nếu có
    if (rescueMapClickListener) {
        window.map.off('click', rescueMapClickListener);
    }

    // Lắng nghe sự kiện click
    rescueMapClickListener = function (e) {
        if (!isPickingRescueLocation) return;

        const lat = e.latlng.lat;
        const lon = e.latlng.lng;

        // Cập nhật input
        const latEl = document.getElementById('guest-rescue-lat');
        const lonEl = document.getElementById('guest-rescue-lon');
        if (latEl) latEl.value = Number(lat).toFixed(6);
        if (lonEl) lonEl.value = Number(lon).toFixed(6);

        // Trả về trạng thái bình thường
        isPickingRescueLocation = false;
        document.getElementById('map').style.cursor = '';
        window.map.off('click', rescueMapClickListener);

        // Vẽ marker tạm cho vị trí vừa click
        if (window.userLocationMarker && window.map.hasLayer(window.userLocationMarker)) {
            window.map.removeLayer(window.userLocationMarker);
        }
        if (window.userLocationCircle && window.map.hasLayer(window.userLocationCircle)) {
            window.map.removeLayer(window.userLocationCircle);
        }

        window.userLocationMarker = L.marker([lat, lon], {
            icon: L.divIcon({
                className: 'user-location-marker',
                html: '<div style="width: 18px; height: 18px; background: #0d6efd; border-radius: 50%; border: 3px solid white; box-shadow: 0 0 15px rgba(13,110,253,0.8); animation: guestRescuePulse 1.5s infinite;"></div>',
                iconSize: [18, 18],
                iconAnchor: [9, 9]
            })
        }).addTo(window.map).bindPopup('Vị trí được chọn trên bản đồ');

        window.map.setView([lat, lon], 15, { animate: true });

        // Mở lại modal sau thời gian ngắn
        setTimeout(() => {
            window.toast?.success('Đã ghim toạ độ thành công!');
            if (window.rescueFormModal) window.rescueFormModal.show();
        }, 150);
    };

    // Đợi 1 chút để không bắt nhầm sự kiện click vào nút
    setTimeout(() => {
        window.map.on('click', rescueMapClickListener);
    }, 150);
};

// --- ADMIN DRAGGABLE MARKER UTILITY ---
/**
 * Dành cho Admin: Kéo thả một marker để lấy toạ độ mới
 * Cách dùng: window.makeMarkerDraggable(markerObj)
 */
window.makeMarkerDraggable = function (marker, latInputId = 'input-lat', lngInputId = 'input-lng') {
    if (!marker) return;

    // Kích hoạt tính năng kéo thả của marker
    if (marker.dragging) {
        marker.dragging.enable();
    }

    // Lắng nghe sự kiện kết thúc thả chuột
    marker.on('dragend', function (e) {
        const position = marker.getLatLng();
        const lat = position.lat.toFixed(6);
        const lng = position.lng.toFixed(6);

        // Cập nhật DOM
        const latInput = document.getElementById(latInputId);
        const lngInput = document.getElementById(lngInputId);

        if (latInput) latInput.value = lat;
        if (lngInput) lngInput.value = lng;

        // Thông báo cho Admin (Sử dụng SweetAlert2 nếu có)
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: 'Đã cập nhật vị trí!',
                html: `Vị trí mới:<br><b>Lat:</b> ${lat}<br><b>Lng:</b> ${lng}`,
                icon: 'success',
                timer: 2500,
                showConfirmButton: false,
                toast: true,
                position: 'bottom-end'
            });
        } else if (window.toast && window.toast.success) {
            window.toast.success(`Đã lấy vị trí: ${lat}, ${lng}`);
        } else {
            alert(`Đã cập nhật vị trí mới!\nLat: ${lat}\nLng: ${lng}`);
        }
    });
};

// --- FEATURE 2: VOICE ALERT (Web Speech API) ---
function playWarningVoice(stationName, level) {
    if (!('speechSynthesis' in window)) {
        console.warn('[VOICE] Web Speech API not supported');
        return;
    }
    const text = `Cảnh báo! Trạm ${stationName} đang ở mức ${level}. Yêu cầu chú ý.`;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'vi-VN';
    utterance.rate = 0.9;
    utterance.pitch = 1.1;
    utterance.volume = 1;

    // Ưu tiên giọng nữ tiếng Việt
    const voices = speechSynthesis.getVoices();
    const viVoice = voices.find(v => v.lang.startsWith('vi') && v.name.toLowerCase().includes('female'))
        || voices.find(v => v.lang.startsWith('vi'))
        || null;
    if (viVoice) utterance.voice = viVoice;

    speechSynthesis.cancel(); // Hủy giọng cũ nếu đang phát
    speechSynthesis.speak(utterance);
}
window.playWarningVoice = playWarningVoice;

// --- FEATURE 3: QR CODE SHARING ---
window.showStationQR = function (lat, lng, stationName) {
    // Xoá popup cũ nếu có
    let existing = document.getElementById('qr-popup-overlay');
    if (existing) existing.remove();

    const url = `${window.location.origin}/map?lat=${lat}&lng=${lng}`;

    const overlay = document.createElement('div');
    overlay.id = 'qr-popup-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.5);';
    overlay.innerHTML = `
        <div class="qr-popup-glass">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h6 class="mb-0 fw-bold"><i class="bi bi-qr-code me-2"></i>${stationName || 'Trạm'}</h6>
                <button class="btn btn-sm btn-close" id="qr-popup-close"></button>
            </div>
            <div id="qr-canvas-wrap" class="text-center mb-2"></div>
            <div class="text-center small opacity-75 text-break" style="font-size:0.7rem;">${url}</div>
        </div>
    `;
    document.body.appendChild(overlay);

    // Render QR (qrcode.js loaded from CDN)
    if (typeof QRCode !== 'undefined') {
        new QRCode(document.getElementById('qr-canvas-wrap'), {
            text: url, width: 180, height: 180, colorDark: '#0f172a', colorLight: '#ffffff'
        });
    } else {
        document.getElementById('qr-canvas-wrap').innerHTML = '<p class="text-muted">Thư viện QR chưa được tải.</p>';
    }

    document.getElementById('qr-popup-close').addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
};

// --- FEATURE 4: PDF EXPORT (Server-side) ---
window.exportStationPDF = function () {
    if (!currentStationData || !currentStationData.id) {
        // Fallback client-side
        const sidebar = document.getElementById('detail-sidebar');
        if (!sidebar || typeof html2pdf === 'undefined') {
            window.toast?.error('Không thể xuất PDF.');
            return;
        }
        const stName = document.getElementById('st-name')?.textContent || 'Tram';
        const fileName = `BaoCao_${stName.replace(/\s+/g, '_')}_${new Date().toISOString().slice(0, 10)}.pdf`;
        const clone = sidebar.cloneNode(true);
        clone.style.cssText = 'position:absolute;left:-9999px;top:0;width:700px;background:#fff;color:#1e293b;padding:24px;';
        clone.querySelectorAll('.sidebar-close-btn, .btn-export-pdf, .btn-qr-share').forEach(el => el.remove());
        document.body.appendChild(clone);
        html2pdf().set({
            margin: [10, 10, 10, 10], filename: fileName, image: { type: 'jpeg', quality: 0.95 },
            html2canvas: { scale: 2, useCORS: true, backgroundColor: '#ffffff' },
            jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
        }).from(clone).save().then(() => { clone.remove(); window.toast?.success(`Đã tải ${fileName}`); })
            .catch(() => { clone.remove(); window.toast?.error('Lỗi xuất PDF.'); });
        return;
    }

    // Server-side professional PDF
    const stationId = currentStationData.id;
    window.toast?.info('Đang tạo báo cáo PDF trên server...');
    const url = `/api/admin/export/station/${stationId}/pdf`;
    fetch(url).then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
    }).then(blob => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `BaoCao_${(currentStationData.name || 'Tram').replace(/\s+/g, '_')}_${new Date().toISOString().slice(0, 10)}.pdf`;
        a.click();
        URL.revokeObjectURL(a.href);
        window.toast?.success('Đã tải xuống báo cáo PDF!');
    }).catch(err => {
        console.error('[PDF Server]', err);
        window.toast?.error('Lỗi khi xuất PDF từ server. Thử phương án client-side...');
    });
};
// --- FEATURE 5: RESCUE HEATMAP LAYER ---
let rescueHeatLayer = null;
let heatmapVisible = false;

function buildHeatmapData() {
    // Sử dụng dữ liệu rescue thật nếu có, nếu không dùng mẫu
    if (rescueRequestsData && rescueRequestsData.length > 0) {
        return rescueRequestsData
            .filter(r => r.latitude && r.longitude)
            .map(r => [r.latitude, r.longitude, 0.8]);
    }
    // Dữ liệu mẫu 10 điểm quanh Đà Nẵng
    return [
        [16.047, 108.206, 0.9], [16.052, 108.212, 0.7], [16.041, 108.198, 0.8],
        [16.060, 108.220, 0.6], [16.035, 108.190, 0.95], [16.055, 108.200, 0.5],
        [16.043, 108.215, 0.85], [16.065, 108.208, 0.7], [16.038, 108.225, 0.6],
        [16.050, 108.195, 0.75]
    ];
}

function toggleHeatmap() {
    const btn = document.getElementById('heatmap-toggle');
    if (!map || typeof L.heatLayer === 'undefined') {
        window.toast?.error('Plugin heatmap chưa sẵn sàng.');
        return;
    }

    heatmapVisible = !heatmapVisible;

    if (heatmapVisible) {
        const data = buildHeatmapData();
        rescueHeatLayer = L.heatLayer(data, {
            radius: 30, blur: 20, maxZoom: 14,
            gradient: { 0.2: '#2196f3', 0.4: '#4caf50', 0.6: '#ffeb3b', 0.8: '#ff9800', 1: '#f44336' }
        }).addTo(window.map);
        btn?.classList.add('active');
        window.toast?.info('Heatmap đã bật');
    } else {
        if (rescueHeatLayer && window.map) {
            window.map.removeLayer(rescueHeatLayer);
            rescueHeatLayer = null;
        }
        btn?.classList.remove('active');
        window.toast?.info('Heatmap đã tắt');
    }
}

runWhenDomReady(() => {
    const heatBtn = document.getElementById('heatmap-toggle');
    if (heatBtn) heatBtn.addEventListener('click', toggleHeatmap);
});

// --- FEATURE 6: TIMELINE SLIDER ---
let timelineMarkers = []; // Sẽ được tạo từ rescueRequestsData

function setupTimelineSlider() {
    const slider = document.getElementById('timeline-slider');
    const label = document.getElementById('timeline-label');
    const wrap = document.getElementById('timeline-slider-wrap');
    if (!slider || !label || !wrap) return;

    slider.addEventListener('input', () => {
        const dayValue = parseInt(slider.value, 10);
        const targetDate = new Date();
        targetDate.setDate(targetDate.getDate() - (30 - dayValue));
        const dateStr = targetDate.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' });
        label.textContent = `Ngày ${dateStr}`;

        // Filter rescue markers: hiển thị marker thuộc ngày đó
        Object.entries(rescueMarkers).forEach(([id, marker]) => {
            const req = rescueRequestsData.find(r => String(r.id) === String(id));
            if (!req || !req.created_at) return;

            const reqDate = new Date(req.created_at);
            const daysDiff = Math.floor((Date.now() - reqDate.getTime()) / (1000 * 60 * 60 * 24));
            const reqDaySlot = 30 - daysDiff; // 1 = cũ nhất, 30 = mới nhất

            if (window.map) {
                if (reqDaySlot <= dayValue) {
                    if (!window.map.hasLayer(marker)) marker.addTo(window.map);
                } else {
                    if (window.map.hasLayer(marker)) window.map.removeLayer(marker);
                }
            }
        });
    });
}

// Hiển thị timeline khi có đủ dữ liệu
window.showTimelineSlider = function () {
    const wrap = document.getElementById('timeline-slider-wrap');
    if (wrap) {
        wrap.style.display = wrap.style.display === 'none' ? 'flex' : 'none';
        if (wrap.style.display === 'flex') setupTimelineSlider();
    }
};

console.log('[MAP] Script fully loaded');

