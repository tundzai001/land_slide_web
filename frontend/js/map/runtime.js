// =====================================================
// MAP MAIN - FIXED VERSION
// =====================================================

console.log('[MAP] Script loaded, waiting for DOM...');

let map;
let mapInitialized = false;
let mapRefreshIntervalIds = [];
let currentTileLayer = null;
let markers = {};
let charts = {};
let currentStationData = null;
let allStations = [];
let stationSelectionController = null;
let stationSelectionSequence = 0;
let stationHistoryController = null;
const stationDetailCache = new Map();
const stationHistoryCache = new Map();
const STATION_DETAIL_CACHE_MS = 15000;
const STATION_HISTORY_CACHE_MS = 60000;
let currentView = 'realtime';
let wsConnection = null;
let wsHeartbeatId = null;
let wsReconnectId = null;
let wsReconnectAttempt = 0;
let latestRealtimeSensorTs = {}; // key: `${stationId}_${sensorType}` -> unix timestamp
const pendingRealtimeSensorUi = new Map();
let realtimeSensorUiFrameId = null;

function scheduleRealtimeSensorUiUpdate(message) {
    const key = `${message.station_id || 'current'}_${message.sensor_type || message.type}`;
    pendingRealtimeSensorUi.set(key, message);
    if (realtimeSensorUiFrameId !== null) return;

    realtimeSensorUiFrameId = requestAnimationFrame(() => {
        realtimeSensorUiFrameId = null;
        const updates = Array.from(pendingRealtimeSensorUi.values());
        pendingRealtimeSensorUi.clear();
        updates.forEach(updateRealtimeSensorValues);
    });
}

function isMapViewActive() {
    return document.documentElement.dataset.appView === 'map' && Boolean(document.getElementById('map'));
}

function stopMapBackgroundWork() {
    mapRefreshIntervalIds.forEach(clearInterval);
    mapRefreshIntervalIds = [];
    if (wsHeartbeatId) clearInterval(wsHeartbeatId);
    if (wsReconnectId) clearTimeout(wsReconnectId);
    wsHeartbeatId = null;
    wsReconnectId = null;
    if (wsConnection) {
        const socket = wsConnection;
        wsConnection = null;
        socket.onclose = null;
        socket.close();
    }
    if (gnssAdjustmentDebugState.statusPollId) clearInterval(gnssAdjustmentDebugState.statusPollId);
    if (gnssAdjustmentDebugState.watchdogId) clearInterval(gnssAdjustmentDebugState.watchdogId);
    gnssAdjustmentDebugState.statusPollId = null;
    gnssAdjustmentDebugState.watchdogId = null;
    if (realtimeSensorUiFrameId !== null) cancelAnimationFrame(realtimeSensorUiFrameId);
    realtimeSensorUiFrameId = null;
    pendingRealtimeSensorUi.clear();
    window.unmountReactStationList?.();
    destroyStationCharts();
    stopLongTerm3DAnimations();
}
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
let rescueMarkersRenderSignature = '';
let corsBaseMarkers = {}; // key: station name -> marker
let corsBaseStateCache = {};
let corsBaseFetchInFlight = false;
let showStationMarkers = true;
let stationClusterGroup = null;
let clusterPolylines = [];
let showRescueMarkers = true;
let currentMapMode = 'station';
let stationsFetchInFlight = false;
let projectsFetchInFlight = false;
let rescueMarkersFetchInFlight = false;
let clusterRenderSignature = '';
let mapInteractionDepth = 0;
let mapInteractionActive = false;
let pendingStationsReload = false;
let pendingProjectsReload = false;
let pendingRescueMarkersReload = false;
let pendingCorsBaseReload = false;

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
    entriesGeneration: 0,
    entrySequence: 0,
    autoScroll: true,
    lastGnssStatusAtByStation: {},
    workflowNodes: [],
    workflowRevision: 0,
    workflowSeedStations: [],
    workflowSampleCounts: {},
    workflowStationIdByRoverName: {},
    workflowCurrentRover: null,
    statusPollId: null,
    statusPollInFlight: false,
    serverMessage: '',
    watchdogId: null,
};

const GNSS_DEBUG_MEMORY_LIMIT = 500;
const GNSS_DEBUG_DOM_LIMIT = 180;
let gnssDebugUiFrameId = null;
let gnssWorkflowFrameId = null;
let gnssLayoutInteractionActive = false;
let pendingGnssAdjustmentResult = null;

function normalizeGnssStationIds(stationIds) {
    return Array.isArray(stationIds)
        ? stationIds.map(Number).filter(Number.isFinite)
        : [];
}

function syncGnssExpectedStationIds(stationIds) {
    gnssAdjustmentDebugState.expectedStationIds = normalizeGnssStationIds(stationIds);
    window.gnssBoardState?.pruneToExpectedStations?.(
        gnssAdjustmentDebugState.expectedStationIds,
        gnssAdjustmentDebugState.workflowStationIdByRoverName,
    );
    const expectedRovers = gnssAdjustmentDebugState.expectedStationIds.map((stationId, index) => {
        const station = allStations.find(item => Number(item.id) === Number(stationId));
        const name = String(station?.station_code || station?.name || `Trạm ${stationId}`).trim();
        gnssAdjustmentDebugState.workflowStationIdByRoverName[name] = Number(stationId);
        return { stationId: Number(stationId), name, index };
    });
    window.gnssBoardState?.seedExpectedRovers?.(expectedRovers);
}

function isGnssAdjustmentExpectedStation(stationId) {
    const expected = gnssAdjustmentDebugState.expectedStationIds;
    if (!Array.isArray(expected) || expected.length === 0) return true;
    const numericStationId = Number(stationId);
    if (!Number.isFinite(numericStationId)) return true;
    return expected.includes(numericStationId);
}

function scheduleGnssAdjustmentDebugUiRefresh() {
    if (gnssLayoutInteractionActive) return;
    if (gnssDebugUiFrameId !== null) return;
    gnssDebugUiFrameId = requestAnimationFrame(() => {
        gnssDebugUiFrameId = null;
        refreshGnssAdjustmentDebugUi();
    });
}

function scheduleGnssAdjustmentWorkflowRender() {
    if (gnssLayoutInteractionActive) return;
    if (gnssWorkflowFrameId !== null) return;
    gnssWorkflowFrameId = requestAnimationFrame(() => {
        gnssWorkflowFrameId = null;
        renderGnssAdjustmentWorkflow();
    });
}

const GNSS_ADJUSTMENT_RUNNING_PHASES = new Set(['WAITING', 'COLLECTING_BASELINE', 'FREE_NETWORK']);

function isGnssAdjustmentRunning(projectId = null) {
    if (!gnssAdjustmentDebugState.active) return false;
    if (projectId && Number(projectId) !== Number(gnssAdjustmentDebugState.projectId)) return false;
    return GNSS_ADJUSTMENT_RUNNING_PHASES.has(gnssAdjustmentDebugState.phase);
}

function ensureGnssAdjustmentRunningPill() {
    let pill = document.getElementById('gnss-adjustment-running-pill');
    if (pill) return pill;
    pill = document.createElement('button');
    pill.id = 'gnss-adjustment-running-pill';
    pill.type = 'button';
    pill.style.cssText = [
        'position:fixed', 'right:22px', 'bottom:22px', 'z-index:1085',
        'display:none', 'align-items:center', 'gap:10px', 'padding:10px 16px',
        'border:1px solid rgba(45,212,191,.65)', 'border-radius:999px',
        'background:linear-gradient(135deg,#071a22,#0d3037)', 'color:#d5fffb',
        'box-shadow:0 12px 36px rgba(0,0,0,.38),0 0 24px rgba(45,212,191,.2)',
        'font:600 12px monospace', 'cursor:pointer'
    ].join(';');
    pill.innerHTML = '<span style="width:9px;height:9px;border-radius:50%;background:#2dd4bf;box-shadow:0 0 12px #2dd4bf"></span><span class="gnss-pill-label">Bình sai đang chạy</span>';
    pill.addEventListener('click', () => {
        const modal = window.ensureGnssTerminalModal?.();
        if (!modal || !window.bootstrap?.Modal) {
            console.error('[GNSS] Terminal modal is not initialized yet.');
            window.toast?.error?.('Cửa sổ Bình sai chưa khởi tạo xong, vui lòng thử lại.');
            return;
        }
        window.bootstrap.Modal.getOrCreateInstance(modal).show();
    });
    document.body.appendChild(pill);
    return pill;
}

function refreshGnssAdjustmentRunningPill() {
    const pill = ensureGnssAdjustmentRunningPill();
    const modal = document.getElementById('gnssTerminalModal');
    const modalVisible = Boolean(modal?.classList.contains('show'));
    const shouldShow = isGnssAdjustmentRunning() && !modalVisible;
    pill.style.display = shouldShow ? 'flex' : 'none';
    const label = pill.querySelector('.gnss-pill-label');
    if (label) label.textContent = `Bình sai đang chạy · ${gnssAdjustmentDebugState.phase} · Mở lại`;
}

function formatGnssDebugTime(date = new Date()) {
    return date.toLocaleTimeString('vi-VN', { hour12: false });
}

function phaseClassForGnssAdjustment(phase) {
    switch (String(phase || '').toUpperCase()) {
        case 'COLLECTING_BASELINE': return 'ms-4 text-info fw-bold font-monospace';
        case 'FREE_NETWORK': return 'ms-4 text-warning fw-bold font-monospace';
        case 'COMPLETED': return 'ms-4 text-success fw-bold font-monospace';
        case 'FAILED_QUALITY_GATE': return 'ms-4 text-danger fw-bold font-monospace';
        case 'ERROR': return 'ms-4 text-danger fw-bold font-monospace';
        default: return 'ms-4 text-warning fw-bold font-monospace';
    }
}

const GNSS_WORKFLOW_STATUS_LABELS = {
    running: 'Đang chạy',
    success: 'Hoàn tất',
    warning: 'Cần chú ý',
    error: 'Lỗi',
};

function upsertGnssWorkflowNode(key, options = {}) {
    if (!key) return null;
    let node = gnssAdjustmentDebugState.workflowNodes.find(item => item.key === key);
    if (!node) {
        node = {
            key,
            title: options.title || key,
            detail: options.detail || '',
            status: options.status || 'running',
            group: options.group || '',
            icon: options.icon || 'bi-circle',
            time: formatGnssDebugTime(),
        };
        gnssAdjustmentDebugState.workflowNodes.push(node);
    } else {
        ['title', 'detail', 'status', 'group', 'icon'].forEach(field => {
            if (options[field] !== undefined) node[field] = options[field];
        });
    }
    gnssAdjustmentDebugState.workflowRevision += 1;
    scheduleGnssAdjustmentWorkflowRender();
    return node;
}

function finishGnssWorkflowNode(key, detail = undefined) {
    const node = gnssAdjustmentDebugState.workflowNodes.find(item => item.key === key);
    if (!node) return;
    if (node.status !== 'warning') node.status = 'success';
    if (detail !== undefined) node.detail = detail;
    gnssAdjustmentDebugState.workflowRevision += 1;
    scheduleGnssAdjustmentWorkflowRender();
}

function finishRunningGnssWorkflowNodes(group = null) {
    let changed = false;
    gnssAdjustmentDebugState.workflowNodes.forEach(node => {
        if (node.status === 'running' && (!group || node.group === group)) {
            node.status = 'success';
            changed = true;
        }
    });
    if (changed) {
        gnssAdjustmentDebugState.workflowRevision += 1;
        scheduleGnssAdjustmentWorkflowRender();
    }
}

function renderGnssAdjustmentWorkflow() {
    const map = document.getElementById('gnss-workflow-map');
    if (!map) return;
    const revision = String(gnssAdjustmentDebugState.workflowRevision);
    if (map.dataset.workflowRevision === revision) return;

    map.innerHTML = '';
    gnssAdjustmentDebugState.workflowNodes.forEach((node, index) => {
        const item = document.createElement('article');
        item.className = `gnss-flow-node status-${node.status}${node.group ? ' is-branch' : ''}`;
        item.dataset.workflowKey = node.key;

        const rail = document.createElement('div');
        rail.className = 'gnss-flow-rail';
        const marker = document.createElement('span');
        marker.className = 'gnss-flow-marker';
        const markerIcon = document.createElement('i');
        markerIcon.className = `bi ${node.status === 'success' ? 'bi-check-lg' : node.status === 'error' ? 'bi-x-lg' : node.icon}`;
        marker.appendChild(markerIcon);
        rail.appendChild(marker);

        const card = document.createElement('div');
        card.className = 'gnss-flow-card';
        const meta = document.createElement('div');
        meta.className = 'gnss-flow-meta';
        const step = document.createElement('span');
        step.className = 'gnss-flow-step';
        step.textContent = node.group || `BƯỚC ${String(index + 1).padStart(2, '0')}`;
        const status = document.createElement('span');
        status.className = 'gnss-flow-status';
        status.textContent = GNSS_WORKFLOW_STATUS_LABELS[node.status] || node.status;
        meta.append(step, status);

        const title = document.createElement('h6');
        title.textContent = node.title;
        const detail = document.createElement('p');
        detail.textContent = node.detail || 'Đang chờ phản hồi từ hệ thống…';
        const time = document.createElement('time');
        time.textContent = node.time;
        card.append(meta, title, detail, time);
        item.append(rail, card);
        map.appendChild(item);
    });
    map.dataset.workflowRevision = revision;

    const nodes = gnssAdjustmentDebugState.workflowNodes;
    const completed = nodes.filter(node => node.status === 'success' || node.status === 'warning').length;
    const percent = nodes.length ? Math.round((completed / nodes.length) * 100) : 0;
    const bar = document.getElementById('gnss-workflow-progress-bar');
    const value = document.getElementById('gnss-workflow-progress-value');
    const current = [...nodes].reverse().find(node => node.status === 'running' || node.status === 'error') || nodes.at(-1);
    if (bar) bar.style.width = `${percent}%`;
    if (value) value.textContent = `${completed}/${nodes.length} mốc`;
    const currentLabel = document.getElementById('gnss-workflow-current');
    if (currentLabel) currentLabel.textContent = current?.title || 'Chưa bắt đầu';

    const scroller = document.getElementById('gnss-workflow-scroll');
    if (scroller && nodes.some(node => node.status === 'running')) {
        requestAnimationFrame(() => { scroller.scrollTop = scroller.scrollHeight; });
    }
}

function gnssWorkflowRoverFromMessage(message) {
    const match = String(message || '').match(/^([^:]{1,80}):\s*/);
    return match ? match[1].trim() : '';
}

function syncGnssWorkflowProgress(phase, rawMessage = '') {
    const normalizedPhase = String(phase || 'WAITING').toUpperCase();
    const message = String(rawMessage || '');
    const rover = gnssWorkflowRoverFromMessage(message);
    const group = rover ? `ROVER · ${rover}` : '';

    if (normalizedPhase === 'WAITING') {
        upsertGnssWorkflowNode('session', {
            title: 'Khởi tạo phiên bình sai', detail: message || 'Chuẩn bị kết nối API và WebSocket.',
            status: 'running', icon: 'bi-power',
        });
        return;
    }

    if (normalizedPhase === 'COLLECTING_BASELINE') {
        finishGnssWorkflowNode('session', 'API và kênh thời gian thực đã sẵn sàng.');
        upsertGnssWorkflowNode('seed', {
            title: 'Thu baseline từ Base cố định',
            detail: message || 'Chờ mỗi rover online gửi ít nhất một #AGRICA RTK Fixed hợp lệ.',
            status: 'running', icon: 'bi-broadcast-pin',
        });
        return;
    }

    if (normalizedPhase === 'ERROR' || normalizedPhase === 'FAILED_QUALITY_GATE') {
        const current = [...gnssAdjustmentDebugState.workflowNodes].reverse().find(node => node.status === 'running');
        if (current) {
            current.status = 'error';
            current.detail = message || current.detail;
            gnssAdjustmentDebugState.workflowRevision += 1;
        } else {
            upsertGnssWorkflowNode('error', {
                title: normalizedPhase === 'FAILED_QUALITY_GATE' ? 'Không đạt kiểm định chất lượng' : 'Quy trình bị dừng', detail: message || 'Máy chủ báo lỗi.', status: 'error', icon: 'bi-exclamation-triangle',
            });
        }
        renderGnssAdjustmentWorkflow();
        return;
    }

    if (normalizedPhase === 'COMPLETED') {
        finishRunningGnssWorkflowNodes();
        finishGnssWorkflowNode('solve');
        upsertGnssWorkflowNode('completed', {
            title: 'Hoàn tất bình sai mạng',
            detail: message || 'Đã lưu kết quả và tạo báo cáo XLSX cùng hồ sơ audit JSON.',
            status: 'success', icon: 'bi-flag-fill',
        });
        return;
    }

    if (normalizedPhase !== 'FREE_NETWORK') return;
    if (/starting round-robin|all selected rovers|remaining rovers/i.test(message)) {
        if (/skipped offline|no-data station/i.test(message)) {
            upsertGnssWorkflowNode('seed', {
                title: 'Thu baseline từ Base cố định', detail: message,
                status: 'warning', icon: 'bi-exclamation-diamond',
            });
        } else {
            finishGnssWorkflowNode('seed', 'Đã có baseline Base cố định cho toàn bộ rover tham gia.');
        }
    }
    if (/on-demand\/sleep|ngắt luồng ntrip/i.test(message)) {
        upsertGnssWorkflowNode('fixed-base-sleep', {
            title: 'Đưa Base cố định về chế độ ngủ', detail: message,
            status: 'running', icon: 'bi-moon-stars',
        });
        return;
    }
    if (/khôi phục.*base cố định|restor.*fixed base/i.test(message)) {
        finishRunningGnssWorkflowNodes(gnssAdjustmentDebugState.workflowCurrentRover ? `ROVER · ${gnssAdjustmentDebugState.workflowCurrentRover}` : null);
        upsertGnssWorkflowNode('fixed-base-restore', {
            title: 'Khôi phục stream Base cố định', detail: message,
            status: /success|thành công/i.test(message) ? 'success' : 'running', icon: 'bi-broadcast',
        });
        return;
    }
    if (/aggregating repeated baselines|gom.*baseline|giải bình sai/i.test(message)) {
        finishGnssWorkflowNode('fixed-base-restore');
        upsertGnssWorkflowNode('solve', {
            title: 'Gom trị đo và giải bình sai', detail: message,
            status: 'running', icon: 'bi-calculator',
        });
        return;
    }
    if (!rover) return;
    gnssAdjustmentDebugState.workflowCurrentRover = rover;
    const key = suffix => `rover:${rover}:${suffix}`;

    if (/querying .*active aicaster/i.test(message)) {
        finishGnssWorkflowNode('fixed-base-sleep', 'Base cố định đã ngắt luồng NTRIP để tránh xung đột nguồn hiệu chỉnh.');
        upsertGnssWorkflowNode(key('session'), {
            title: 'Tìm phiên điều khiển AICaster', detail: message, status: 'running', group, icon: 'bi-search',
        });
    } else if (/matched aicaster/i.test(message)) {
        finishGnssWorkflowNode(key('session'), message);
    } else if (/preflight .*mode rover/i.test(message)) {
        finishGnssWorkflowNode(key('session'));
        upsertGnssWorkflowNode(key('preflight'), {
            title: 'Kiểm tra đường lệnh và MQTT ACK', detail: message, status: 'running', group, icon: 'bi-shield-check',
        });
    } else if (/sending set base/i.test(message)) {
        finishGnssWorkflowNode(key('preflight'), 'MQTT đã xác nhận preflight ROVER; cho phép chuyển BASE tạm.');
        upsertGnssWorkflowNode(key('base'), {
            title: 'Cấu hình BASE tạm và RTCM', detail: message, status: 'running', group, icon: 'bi-antenna',
        });
    } else if (/set base accepted/i.test(message)) {
        upsertGnssWorkflowNode(key('base'), {
            title: 'Cấu hình BASE tạm và RTCM', detail: message,
            status: /optional rtcm fallback/i.test(message) ? 'warning' : 'success',
            group, icon: /optional rtcm fallback/i.test(message) ? 'bi-exclamation-diamond' : 'bi-check-lg',
        });
    } else if (/set base was not fully verified/i.test(message)) {
        upsertGnssWorkflowNode(key('base'), {
            title: 'Cấu hình BASE tạm và RTCM', detail: message,
            status: 'error', group, icon: 'bi-x-lg',
        });
        upsertGnssWorkflowNode(key('restore'), {
            title: 'Phục hồi ROVER an toàn',
            detail: 'Đang hoàn tác cấu hình BASE trước khi dừng chu kỳ.',
            status: 'running', group, icon: 'bi-life-preserver',
        });
    } else if (/restore step \d+\/\d+/i.test(message)) {
        upsertGnssWorkflowNode(key('restore'), {
            title: 'Phục hồi ROVER an toàn', detail: message,
            status: 'running', group, icon: 'bi-arrow-counterclockwise',
        });
    } else if (/ack received for/i.test(message)) {
        upsertGnssWorkflowNode(key('restore'), {
            title: 'Phục hồi ROVER an toàn', detail: message,
            status: /saveconfig/i.test(message) ? 'success' : 'running',
            group, icon: 'bi-arrow-counterclockwise',
        });
    } else if (/no ack for .*retrying/i.test(message)) {
        upsertGnssWorkflowNode(key('restore'), {
            title: 'Phục hồi ROVER an toàn', detail: message,
            status: 'running', group, icon: 'bi-exclamation-triangle',
        });
    } else if (/rotation skipped after safe rover recovery/i.test(message)) {
        upsertGnssWorkflowNode(key('restore'), {
            title: 'Bỏ lượt BASE, tiếp tục rover kế tiếp', detail: message,
            status: 'warning', group, icon: 'bi-skip-forward',
        });
    } else if (/waiting 10s .*emit rtcm/i.test(message)) {
        finishGnssWorkflowNode(key('base'));
        upsertGnssWorkflowNode(key('warmup'), {
            title: 'Chờ bộ thu phát RTCM', detail: message, status: 'running', group, icon: 'bi-hourglass-split',
        });
    } else if (/starting mqtt-to-ntrip route/i.test(message)) {
        finishGnssWorkflowNode(key('warmup'));
        upsertGnssWorkflowNode(key('route'), {
            title: 'Mở tuyến MQTT → NTRIP', detail: message, status: 'running', group, icon: 'bi-diagram-3',
        });
    } else if (/rtcm route is live/i.test(message)) {
        finishGnssWorkflowNode(key('route'), message);
        upsertGnssWorkflowNode(key('settle'), {
            title: 'Xác minh nguồn Base tạm', detail: message, status: 'running', group, icon: 'bi-crosshair',
        });
    } else if (/ntrip source accepted.*collecting cross-baselines/i.test(message)) {
        finishGnssWorkflowNode(key('settle'));
        upsertGnssWorkflowNode(key('collect'), {
            title: 'Thu baseline chéo', detail: message, status: 'running', group, icon: 'bi-bezier2',
        });
    } else if (/collection window closed/i.test(message)) {
        finishGnssWorkflowNode(key('collect'), message);
    } else if (/sending set rover/i.test(message)) {
        finishGnssWorkflowNode(key('collect'));
        upsertGnssWorkflowNode(key('restore'), {
            title: 'Trả thiết bị về ROVER', detail: message, status: 'running', group, icon: 'bi-arrow-counterclockwise',
        });
    } else if (/set rover accepted/i.test(message)) {
        finishGnssWorkflowNode(key('restore'), message);
    }
}

function syncGnssWorkflowBaseline(message) {
    const roverName = String(message.rover_name || '').trim();
    const fromPoint = String(message.from || 'BASE').trim();
    if (!roverName) return;
    const stationId = Number(message.station_id);
    if (Number.isFinite(stationId)) {
        gnssAdjustmentDebugState.workflowStationIdByRoverName[roverName] = stationId;
    }
    if (gnssAdjustmentDebugState.phase === 'COLLECTING_BASELINE' && fromPoint.toUpperCase() === 'BASE') {
        if (!gnssAdjustmentDebugState.workflowSeedStations.includes(roverName)) {
            gnssAdjustmentDebugState.workflowSeedStations.push(roverName);
        }
        const expected = gnssAdjustmentDebugState.expectedStationIds.length || '?';
        upsertGnssWorkflowNode('seed', {
            title: 'Thu baseline từ Base cố định',
            detail: `Đã nhận ${gnssAdjustmentDebugState.workflowSeedStations.length}/${expected} rover: ${gnssAdjustmentDebugState.workflowSeedStations.join(', ')}.`,
            status: 'running', icon: 'bi-broadcast-pin',
        });
        return;
    }
    if (fromPoint.toUpperCase() !== 'BASE') {
        const sampleKey = `${fromPoint}->${roverName}`;
        gnssAdjustmentDebugState.workflowSampleCounts[sampleKey] = (gnssAdjustmentDebugState.workflowSampleCounts[sampleKey] || 0) + 1;
        const collectKey = `rover:${fromPoint}:collect`;
        const related = Object.entries(gnssAdjustmentDebugState.workflowSampleCounts)
            .filter(([key]) => key.startsWith(`${fromPoint}->`));
        const total = related.reduce((sum, [, count]) => sum + count, 0);
        upsertGnssWorkflowNode(collectKey, {
            title: 'Thu baseline chéo',
            detail: `Đã nhận ${total} mẫu hợp lệ trên ${related.length} cạnh từ Base tạm ${fromPoint}; solver sẽ chỉ dùng một trị trung bình có trọng số cho mỗi cạnh.`,
            status: 'running', group: `ROVER · ${fromPoint}`, icon: 'bi-bezier2',
        });
    }
}

function refreshGnssAdjustmentDebugUi() {
    const indicator = document.getElementById('gnss-phase-indicator');
    if (indicator) {
        const phaseName = gnssAdjustmentDebugState.phase;
        let phaseMsg = '';
        if (gnssAdjustmentDebugState.entries) {
            const lastPhaseEntry = [...gnssAdjustmentDebugState.entries].reverse().find(e => e.label === 'PHASE');
            if (lastPhaseEntry && lastPhaseEntry.message) phaseMsg = lastPhaseEntry.message;
        }
        indicator.innerHTML = `<span class="opacity-75">Phase:</span> ${phaseName}${phaseMsg ? ` <span class="text-light ms-2 px-2 py-1 bg-dark rounded border border-secondary" style="font-size: 0.8em;">${phaseMsg}</span>` : ''}`;
        indicator.className = phaseClassForGnssAdjustment(phaseName);
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
    if (log && log.offsetParent !== null) {
        const revision = String(gnssAdjustmentDebugState.entriesRevision);
        if (log.dataset.entriesRevision !== revision) {
            const previousScrollTop = log.scrollTop;
            const shouldAutoScroll = gnssAdjustmentDebugState.autoScroll;
            const generation = String(gnssAdjustmentDebugState.entriesGeneration);
            const lastRenderedId = Number(log.dataset.lastEntryId || 0);
            const mustRebuild = log.dataset.entriesGeneration !== generation;
            const entriesToRender = mustRebuild
                ? gnssAdjustmentDebugState.entries.slice(-GNSS_DEBUG_DOM_LIMIT)
                : gnssAdjustmentDebugState.entries.filter(entry => entry.id > lastRenderedId);
            const fragment = document.createDocumentFragment();
            entriesToRender.forEach(entry => {
                const row = document.createElement('div');
                row.className = 'gnss-debug-row';
                const color = entry.level === 'error'
                    ? '#ff6b6b'
                    : entry.level === 'warning'
                        ? '#ffd166'
                        : entry.level === 'success'
                            ? '#5eead4'
                            : '#93c5fd';
                row.style.color = color;
                row.textContent = `[${entry.time}] ${entry.label}: ${entry.message}`;
                fragment.appendChild(row);
            });
            if (mustRebuild) log.replaceChildren();
            log.appendChild(fragment);
            let removedHeight = 0;
            while (log.childElementCount > GNSS_DEBUG_DOM_LIMIT) {
                removedHeight += log.firstElementChild?.offsetHeight || 0;
                log.firstElementChild?.remove();
            }
            const newestEntry = gnssAdjustmentDebugState.entries.at(-1);
            log.dataset.lastEntryId = String(newestEntry?.id || 0);
            log.dataset.entriesGeneration = generation;
            log.dataset.entriesRevision = revision;
            if (shouldAutoScroll) {
                log.scrollTop = log.scrollHeight;
            } else {
                log.scrollTop = Math.min(
                    Math.max(0, previousScrollTop - removedHeight),
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
    renderGnssAdjustmentWorkflow();
    refreshGnssAdjustmentRunningPill();
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
        id: ++gnssAdjustmentDebugState.entrySequence,
        time: formatGnssDebugTime(),
        label,
        message: String(message || '-'),
        level,
    });
    gnssAdjustmentDebugState.entriesRevision += 1;
    if (gnssAdjustmentDebugState.entries.length > GNSS_DEBUG_MEMORY_LIMIT) {
        gnssAdjustmentDebugState.entries.splice(0, gnssAdjustmentDebugState.entries.length - GNSS_DEBUG_MEMORY_LIMIT);
    }
    scheduleGnssAdjustmentDebugUiRefresh();
}

function setGnssAdjustmentPhase(phase, message = '') {
    const previousPhase = gnssAdjustmentDebugState.phase;
    gnssAdjustmentDebugState.phase = String(phase || 'WAITING').toUpperCase();
    if (message) gnssAdjustmentDebugState.serverMessage = String(message);
    syncGnssWorkflowProgress(gnssAdjustmentDebugState.phase, message);
    refreshGnssAdjustmentDebugUi();
    if (message) addGnssAdjustmentDebug('PHASE', message, gnssAdjustmentDebugState.phase === 'ERROR' ? 'error' : 'info');
    if (gnssAdjustmentDebugState.phase === 'ERROR' && previousPhase !== 'ERROR') {
        window.toast?.error?.(message || 'Quy trình bình sai đã dừng do lỗi.');
    }
    window.gnssBoardState?.draw?.(performance.now());
    if (['COMPLETED', 'FAILED_QUALITY_GATE', 'ERROR', 'IDLE'].includes(gnssAdjustmentDebugState.phase)) {
        if (gnssAdjustmentDebugState.statusPollId) clearInterval(gnssAdjustmentDebugState.statusPollId);
        gnssAdjustmentDebugState.statusPollId = null;
        if (gnssAdjustmentDebugState.watchdogId) clearInterval(gnssAdjustmentDebugState.watchdogId);
        gnssAdjustmentDebugState.watchdogId = null;
    }
}

async function syncGnssAdjustmentStatus() {
    const projectId = Number(gnssAdjustmentDebugState.projectId || 0);
    if (!gnssAdjustmentDebugState.active || !projectId) return;
    if (gnssAdjustmentDebugState.statusPollInFlight) return;
    gnssAdjustmentDebugState.statusPollInFlight = true;
    try {
        const url = `/api/admin/gnss/adjustment/status?project_id=${encodeURIComponent(projectId)}`;
        const response = window.authManager?.apiFetch
            ? await window.authManager.apiFetch(url)
            : await fetch(url);
        if (!response?.ok) return;
        const status = await response.json();
        if (Number(status.project_id) !== projectId) return;
        let phase = String(status.phase || 'IDLE').toUpperCase();
        let message = String(status.message || '');
        if (phase === 'IDLE' && GNSS_ADJUSTMENT_RUNNING_PHASES.has(gnssAdjustmentDebugState.phase)) {
            phase = 'ERROR';
            message = message || 'Phiên bình sai không còn tồn tại trên máy chủ; quy trình đã dừng.';
        }
        if (phase !== gnssAdjustmentDebugState.phase || (message && message !== gnssAdjustmentDebugState.serverMessage)) {
            setGnssAdjustmentPhase(phase, message || 'Đã đồng bộ trạng thái từ máy chủ.');
            addGnssAdjustmentDebug('SYNC', 'Đã khôi phục trạng thái qua API sau khi có thể bỏ lỡ WebSocket.', 'success');
        }
        if (status.data && ['COMPLETED', 'FAILED_QUALITY_GATE', 'ERROR'].includes(phase)) {
            const resultMessage = {
                sensor_type: 'gnss_adjusted',
                timestamp: status.data.computed_at || Math.floor(Date.now() / 1000),
                data: status.data,
            };
            if (phase === 'COMPLETED') {
                updateRealtimeSensorValues(resultMessage);
            } else {
                renderGnssAdjustmentAuditResult(resultMessage);
            }
        }
    } catch (error) {
        console.warn('[GNSS] Could not synchronize adjustment status:', error);
    } finally {
        gnssAdjustmentDebugState.statusPollInFlight = false;
    }
}

function startGnssAdjustmentStatusPolling() {
    if (gnssAdjustmentDebugState.statusPollId) clearInterval(gnssAdjustmentDebugState.statusPollId);
    gnssAdjustmentDebugState.statusPollId = setInterval(syncGnssAdjustmentStatus, 6000);
}

function resetGnssAdjustmentDebug({ projectId, stationIds } = {}) {
    if (gnssAdjustmentDebugState.watchdogId) clearInterval(gnssAdjustmentDebugState.watchdogId);
    if (gnssAdjustmentDebugState.statusPollId) clearInterval(gnssAdjustmentDebugState.statusPollId);
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
        entriesGeneration: gnssAdjustmentDebugState.entriesGeneration + 1,
        autoScroll: true,
        lastGnssStatusAtByStation: {},
        workflowNodes: [],
        workflowRevision: gnssAdjustmentDebugState.workflowRevision + 1,
        workflowSeedStations: [],
        workflowSampleCounts: {},
        workflowStationIdByRoverName: {},
        workflowCurrentRover: null,
        statusPollId: null,
        serverMessage: '',
    });
    const resultsSection = document.getElementById('adj-results-section');
    const pointsList = document.getElementById('adj-points-list');
    if (resultsSection) resultsSection.style.display = 'none';
    if (pointsList) pointsList.innerHTML = '';
    syncGnssWorkflowProgress('WAITING', 'Đang mở API và kênh WebSocket cho phiên mới.');
    addGnssAdjustmentDebug('UI', 'Đã mở phiên debug Bình sai.', 'info');
    gnssAdjustmentDebugState.watchdogId = setInterval(() => {
        if (!gnssAdjustmentDebugState.active) return;
        const elapsed = Math.floor((Date.now() - gnssAdjustmentDebugState.startedAt) / 1000);
        if (elapsed >= 10 && gnssAdjustmentDebugState.baselineCount === 0 && gnssAdjustmentDebugState.phase === 'COLLECTING_BASELINE') {
            const last = gnssAdjustmentDebugState.entries.at(-1);
            if (!last || last.label !== 'WAIT') {
                addGnssAdjustmentDebug('WAIT', 'Chưa nhận baseline hợp lệ. Đang kiểm tra #AGRICA, RTK Fixed và tiến độ seed trên máy chủ.', 'warning');
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
    light: {
        maxZoom: 20,
        subdomains: ['mt0', 'mt1', 'mt2', 'mt3'],
        updateWhenIdle: true,
        updateWhenZooming: false,
        keepBuffer: 2,
    },
    dark: {
        maxZoom: 20,
        subdomains: ['a', 'b', 'c', 'd'],
        updateWhenIdle: true,
        updateWhenZooming: false,
        keepBuffer: 2,
    }
};

function runWhenDomReady(callback) {
    if (window.__MAP_BUNDLE_LOADING__) {
        (window.__MAP_READY_QUEUE__ ||= []).push(callback);
        return;
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', callback, { once: true });
    } else {
        callback();
    }
}

window.flushMapReadyQueue = function flushMapReadyQueue() {
    const callbacks = window.__MAP_READY_QUEUE__ || [];
    window.__MAP_READY_QUEUE__ = [];
    callbacks.forEach(runWhenDomReady);
};

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
    if (mapInitialized || !isMapViewActive()) return;
    mapInitialized = true;
    console.log('✅ [MAP] DOM ready, initializing...');

    // Set global Chart.js animation defaults for smooth realtime updates
    if (window.Chart) {
        Chart.defaults.animation.duration = 160;
        Chart.defaults.animation.easing = 'easeOutQuart';
    }

    initMap();
    setupEventListeners();
    setupMobileMapNavigation();
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

    mapRefreshIntervalIds.push(setInterval(loadStations, 30000));
    // Physical base availability and automatic S1/S2 failover can change at
    // any time; five minutes left stale/incorrect marker states on the map.
    mapRefreshIntervalIds.push(setInterval(loadCorsBaseStations, 15000));
    mapRefreshIntervalIds.push(setInterval(loadRescueMarkers, 60000));

    // ✅ Refresh sensor online status of currently-viewed station every 30s
    // (handles case where a device goes offline while the sidebar is already open)
    mapRefreshIntervalIds.push(setInterval(refreshCurrentStationDetail, 30000));

    console.log('✅ [MAP] Initialization complete!');
}

function setupMobileMapNavigation() {
    const navigation = document.getElementById('map-bottom-nav');
    const stationSheet = document.getElementById('station-list-sidebar');
    const detailSheet = document.getElementById('detail-sidebar');
    if (!navigation || !stationSheet || !detailSheet) return;

    const closePrimarySheets = (except) => {
        if (except !== stationSheet) stationSheet.classList.add('hidden');
        if (except !== detailSheet) detailSheet.classList.remove('active');
    };
    navigation.addEventListener('click', (event) => {
        const button = event.target.closest('[data-map-action]');
        if (!button) return;
        const action = button.dataset.mapAction;
        navigation.querySelectorAll('button').forEach(item => item.classList.toggle('active', item === button));
        if (action === 'stations') {
            closePrimarySheets(stationSheet);
            stationSheet.classList.remove('hidden', 'force-hidden');
            stationSheet.classList.add('active');
        } else if (action === 'layers') {
            closePrimarySheets();
            document.getElementById('layer-mode-toggle')?.click();
        } else if (action === 'rescue') {
            closePrimarySheets();
            document.getElementById('btn-guest-rescue')?.click();
        } else if (action === 'account') {
            closePrimarySheets();
            document.getElementById('auth-btn')?.click();
        }
        setTimeout(() => map?.invalidateSize?.(), 220);
    });

    const header = detailSheet.querySelector('.sidebar-header');
    header?.addEventListener('click', (event) => {
        if (event.target.closest('button,a')) return;
        const states = ['map-sheet-35', 'map-sheet-65', 'map-sheet-full'];
        const current = states.findIndex(state => detailSheet.classList.contains(state));
        detailSheet.classList.remove(...states);
        detailSheet.classList.add(states[(current + 1) % states.length]);
        setTimeout(() => map?.invalidateSize?.(), 220);
    });
}
