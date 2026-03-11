// =====================================================
// MAP MAIN - FIXED VERSION
// =====================================================

console.log('[MAP] Script loaded, waiting for DOM...');

let map;
let markers = {};
let charts = {};
let currentStationData = null;
let allStations = [];
let currentView = 'realtime';
let wsConnection = null;
let latestRealtimeSensorTs = {}; // key: `${stationId}_${sensorType}` -> unix timestamp

// Realtime 3D state
let realtimeImuScene, realtimeImuCamera, realtimeImuRenderer, realtimeImuControls, realtimeImuAnimationId;
let realtimeImuSensorBlock = null;
let realtimeImuTargetQuaternion = null;
let realtimeImuActive = false;
let _THREE = null; // Cached Three.js module for use outside async import scope

// =====================================================
// MAIN INITIALIZATION
// =====================================================

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize);
} else {
    initialize();
}

function initialize() {
    console.log('✅ [MAP] DOM ready, initializing...');

    // Set global Chart.js animation defaults for smooth realtime updates
    if (window.Chart) {
        Chart.defaults.animation.duration = 300;
        Chart.defaults.animation.easing = 'easeOutQuart';
    }

    initMap();
    setupEventListeners();
    loadStations();
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
    };

    wsConnection.onclose = () => {
        console.warn('⚠️ [WS] Disconnected, reconnecting in 5s...');
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
        if (currentStationData && message.station_id === currentStationData.id && message.sensor_type === 'gnss') {
            updateGnssFixBadge(message.data?.fix_mode, message.data?.fix_quality);
            // Low-trust GNSS fixes should not keep stale velocity visible
            setHTML('val-gnss-vel', `--<span class="sensor-unit">mm/s</span>`);
        }
    }

    if (message.type === 'station_status') {
        const riskLevel = String(message.risk_level || 'LOW').toUpperCase();
        const stationId = message.station_id;

        // ✅ Nếu trạm về AN TOÀN → Reset tất cả UI state liên quan
        if (riskLevel === 'LOW') {
            // 1. Clear marker flashing (phải gọi TRƯỚC updateStationMarker)
            if (markerAlertState[stationId]) {
                clearMarkerAlert(stationId);
            }

            // 2. Dismiss alert banner nếu đang hiện cho trạm này
            if (currentAlertStationId === stationId) {
                const banner = document.getElementById('alert-banner');
                if (banner) banner.classList.remove('show');
                currentAlertStationId = null;
                lastAlertKey = null; // Reset dedup để alert mới có thể hiện lại
            }
            // Clear tất cả sensor card highlight khi trạm về safe
            clearAllSensorCardAlerts();

            // 3. Reset siren buttons to idle if viewing this station
            if (currentStationData && stationId === currentStationData.id) {
                setSirenButtonState('idle');
            }
        }

        // ✅ Nếu trạm chuyển sang EXTREME/CRITICAL → Cập nhật siren buttons
        if ((riskLevel === 'EXTREME' || riskLevel === 'CRITICAL') && currentStationData && stationId === currentStationData.id) {
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
        updateStationMarker(stationId, riskLevel);

        // Update status badge in sidebar
        if (currentStationData && stationId === currentStationData.id) {
            const riskEl = document.getElementById('st-risk');
            if (riskEl) {
                let displayRisk = riskLevel;
                let riskClass = riskLevel;

                if (riskLevel === 'LOW') {
                    displayRisk = 'SAFE';
                    riskClass = 'LOW';
                } else if (riskLevel === 'WARNING' || riskLevel === 'MEDIUM' || riskLevel === 'HIGH') {
                    displayRisk = 'WARNING';
                    riskClass = 'MEDIUM';
                } else if (riskLevel === 'EXTREME' || riskLevel === 'CRITICAL') {
                    displayRisk = 'CRITICAL';
                    riskClass = 'CRITICAL';
                }

                riskEl.className = `status-badge ${riskClass}`;
                riskEl.innerHTML = `<span class="status-dot"></span> ${displayRisk}`;
            }
        }

        // Update station list badge
        const listBadge = document.getElementById(`list-badge-${stationId}`);
        if (listBadge) {
            const displayText = riskLevel === 'LOW' ? 'SAFE' : riskLevel;
            listBadge.className = `badge ${getRiskBadgeClass(riskLevel)}`;
            listBadge.innerText = displayText;

            listBadge.style.transition = '0.3s';
            listBadge.style.transform = 'scale(1.2)';
            setTimeout(() => listBadge.style.transform = 'scale(1)', 300);
        }
    }

    // ✅ XỬ LÝ CẢNH BÁO MỚI — Chỉ hiện 1 lần per alert (dedup)
    if (message.type === 'alert') {
        // Dedup theo station + sensor + level để không nuốt cảnh báo mới cùng level từ sensor khác.
        const alertKey = `${message.station_id}_${message.sensor_type || 'unknown'}_${message.level}`;
        if (alertKey !== lastAlertKey) {
            lastAlertKey = alertKey;
            showAlertBanner(message);
        }
        // Highlight sensor card nếu đang xem trạm đang báo
        if (currentStationData && message.station_id === currentStationData.id && message.sensor_type) {
            setSensorCardAlert(message.sensor_type, message.level);
        }
        // ✅ Marker chuyển đỏ + nhấp nháy khi có cảnh báo
        setMarkerAlert(message.station_id, true);
        // Always attempt to play siren (it will handle its own dedup/overlap)
        playSiren();

        // ✅ Cập nhật siren buttons nếu đang xem trạm này
        // Phân biệt pi_point / pi_center — chỉ set 'alerting' nếu thiết bị online
        if (currentStationData && message.station_id === currentStationData.id) {
            const user = window.authManager?.getUserInfo();
            const userRole = user?.role;
            if (userRole === 'admin' || userRole === 'operator') {
                currentAlertStationId = message.station_id;
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
}

function updateRealtimeSensorValues(message) {
    const { sensor_type, data, timestamp, station_id } = message;
    const stationId = station_id || currentStationData?.id;

    if (stationId && sensor_type && timestamp) {
        latestRealtimeSensorTs[`${stationId}_${sensor_type}`] = Number(timestamp);
    }

    //console.log(`🔄 [REALTIME] ${sensor_type}:`, data);

    if (sensor_type === 'gnss' && data) {
        updateGnssFixBadge(data.fix_mode, data.fix_quality);

        const velocityMmS = data.velocity_mm_s ||
            data.speed_2d_mm_s ||
            data.speed_mm_s ||
            (data.speed_2d ? data.speed_2d * 1000 : null) ||
            (data.velocity ? data.velocity * 1000 : null) ||
            (data.speed ? data.speed * 1000 : null) || 0;

        //console.log('📍 [GNSS] Velocity value:', velocityMmS, 'from data:', data);
        animateValue('val-gnss-vel', velocityMmS, 4, 'mm/s');

        const displacement = data.total_displacement_mm || data.displacement_mm || data.displacement || 0;

        if (charts['chart-gnss']) {
            const chart = charts['chart-gnss'];
            chart.data.labels.push(new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
            chart.data.datasets[0].data.push(displacement);

            if (chart.data.labels.length > 50) {
                chart.data.labels.shift();
                chart.data.datasets[0].data.shift();
            }

            chart.update();
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
        animateValue('val-water', level, 2, 'm');

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
        animateValue('val-imu-roll', data.raw_roll, 1, '°', true);
        animateValue('val-imu-pitch', data.raw_pitch, 1, '°', true);
        animateValue('val-imu-yaw', data.raw_yaw, 1, '°', true);

        // Delta values (secondary display)
        animateValue('val-imu-delta-roll', data.roll, 1, '°', true);
        animateValue('val-imu-delta-pitch', data.pitch, 1, '°', true);
        animateValue('val-imu-delta-yaw', data.yaw, 1, '°', true);

        // Use backend drift calculation if available, fallback to JS
        if (data.drift_len_mm !== undefined && data.drift_dir !== undefined) {
            animateValue('val-imu-drift-len', data.drift_len_mm, 1, ' mm', true);
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
        if (charts['chart-imu']) {
            const chart = charts['chart-imu'];
            const timeLabel = new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
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
    }
}

function updateStationMarker(stationId, riskLevel) {
    const marker = markers[stationId];
    if (!marker) return;

    // ✅ Nếu marker đang trong trạng thái alert (đỏ nhấp nháy), không cập nhật
    if (markerAlertState[stationId]) return;

    const normalized = String(riskLevel || 'LOW').toUpperCase();
    const riskToColorKey = {
        'LOW': 'LOW',
        'WARNING': 'MEDIUM',
        'MEDIUM': 'MEDIUM',
        'HIGH': 'HIGH',
        'CRITICAL': 'EXTREME',
        'EXTREME': 'EXTREME'
    };

    const colors = {
        'EXTREME': '#fa5252',
        'HIGH': '#ff922b',
        'MEDIUM': '#ffd43b',
        'LOW': '#51cf66'
    };

    // ✅ Map WARNING/CRITICAL về palette nội bộ, tránh rơi về SAFE khi nhận nhãn khác.
    const mappedLevel = riskToColorKey[normalized] || 'LOW';
    const effectiveLevel = (mappedLevel && colors[mappedLevel]) ? mappedLevel : 'LOW';
    const color = colors[effectiveLevel];
    const shouldPulse = effectiveLevel === 'EXTREME' || effectiveLevel === 'HIGH';
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

function setupEventListeners() {
    console.log('🔧 [MAP] Setting up event listeners...');

    const toggleListBtn = document.getElementById('toggle-list-btn');
    const sidebarCloseTab = document.getElementById('sidebar-close-tab');
    const stationSidebar = document.getElementById('station-list-sidebar');

    // Toggle sidebar trái
    if (toggleListBtn && stationSidebar) {
        toggleListBtn.addEventListener('click', () => {
            stationSidebar.classList.remove('hidden');
            stationSidebar.classList.remove('force-hidden');
        });
    }

    if (sidebarCloseTab && stationSidebar) {
        sidebarCloseTab.addEventListener('click', () => {
            stationSidebar.classList.add('hidden');
        });
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
            if (chartsPanel) chartsPanel.classList.remove('active');
            if (longtermOverlay) longtermOverlay.classList.remove('active');

            // Mở lại sidebar trái
            if (stationSidebar) {
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

    if (closeChartsBtn && chartsPanel) {
        closeChartsBtn.addEventListener('click', () => {
            chartsPanel.classList.remove('active');

            // Chỉ bỏ force-hidden, giữ hidden (sidebar vẫn đóng)
            if (stationSidebar) {
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

    // Phân tích dài hạn -> Mở fullscreen
    const btnLongTerm = document.getElementById('btn-long-term');
    const longtermOverlay = document.getElementById('longterm-overlay');
    const closeLongtermBtn = document.getElementById('close-longterm-btn');

    if (btnLongTerm && longtermOverlay) {
        btnLongTerm.addEventListener('click', () => {
            longtermOverlay.classList.add('active');

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

    if (closeLongtermBtn && longtermOverlay) {
        closeLongtermBtn.addEventListener('click', () => {
            longtermOverlay.classList.remove('active');

            // Chỉ bỏ force-hidden, giữ hidden (sidebar vẫn đóng)
            if (stationSidebar) {
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
                loadLongTermAnalysis();
            });
        });
    }

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
                    const response = await fetch(`/api/field/stations/${currentAlertStationId}/stop-siren?target=${target}`, {
                        method: 'POST'
                    });
                    if (response.ok) {
                        window.toast?.success(`Mute command sent (${iconBase})`);
                        setSirenButtonState('muted', target);
                        // Tắt siren trên web (chỉ tắt khi mute center/point tùy logic, tạm thời cứ tắt JS audio)
                        if (currentSirenAudio) {
                            currentSirenAudio.pause();
                            currentSirenAudio.currentTime = 0;
                            currentSirenAudio = null;
                        }
                    } else {
                        window.toast?.error(`Failed to mute (${iconBase})`);
                        setSirenButtonState('alerting', target);
                    }
                } else if (state === 'muted') {
                    // Đã tắt → Bật lại còi
                    const response = await fetch(`/api/field/stations/${currentAlertStationId}/enable-siren?target=${target}`, {
                        method: 'POST'
                    });
                    if (response.ok) {
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

function initMap() {
    try {
        map = L.map('map', { zoomControl: false }).setView([16.047079, 108.206230], 6);
        L.control.zoom({ position: 'bottomright' }).addTo(map);

        L.tileLayer('https://{s}.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', {
            maxZoom: 20,
            subdomains: ['mt0', 'mt1', 'mt2', 'mt3']
        }).addTo(map);

        console.log('✅ [MAP] Leaflet map initialized');
    } catch (error) {
        console.error('❌ [MAP] Failed to initialize map:', error);
    }
}

async function loadStations() {
    try {
        const res = await fetch('/api/stations');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const stations = await res.json();
        allStations = stations;

        stations.forEach(station => {
            if (station.location && station.location.lat && station.location.lon) {
                updateMarker(station);
            }

            // ✅ Sync marker blinking state từ risk_level API (restore sau reload)
            const _isAlertingRisk = (station.risk_level === 'EXTREME' || station.risk_level === 'HIGH')
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

    } catch (e) {
        console.error('❌ [MAP] Error loading stations:', e);
    }
}

// ✅ Silently re-fetch current station detail to refresh per-sensor is_online status
async function refreshCurrentStationDetail() {
    if (!currentStationData) return;
    const sidebar = document.getElementById('detail-sidebar');
    if (!sidebar || !sidebar.classList.contains('active')) return;

    try {
        const res = await fetch(`/api/stations/${currentStationData.id}/detail`);
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

    container.innerHTML = '';

    stations.forEach(st => {
        let rawLevel = st.risk_level || 'LOW';
        if (st.status === 'offline') {
            rawLevel = 'OFFLINE';
        }

        let displayString = rawLevel;
        let classLevel = rawLevel;

        if (rawLevel === 'LOW') {
            displayString = 'SAFE';
            classLevel = 'LOW';
        } else if (rawLevel === 'MEDIUM' || rawLevel === 'HIGH') {
            displayString = 'WARNING';
            classLevel = 'MEDIUM'; // maps to warning classes
        } else if (rawLevel === 'EXTREME' || rawLevel === 'CRITICAL') {
            displayString = 'CRITICAL';
            classLevel = 'CRITICAL';
        } else if (rawLevel === 'OFFLINE') {
            displayString = 'OFFLINE';
            classLevel = 'OFFLINE';
        } else {
            displayString = 'SAFE';
        }

        const div = document.createElement('div');
        div.className = 'station-item';
        div.innerHTML = `
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <div class="fw-bold" style="color: var(--text-primary)">${st.name}</div>
                            <small style="color: var(--text-secondary)">${st.station_code}</small>
                        </div>
                        <span id="list-badge-${st.id}" class="badge ${getRiskBadgeClass(classLevel)}">
                            ${displayString}
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
    });
}

function getRiskBadgeClass(level) {
    const classes = {
        'CRITICAL': 'bg-danger',
        'EXTREME': 'bg-danger', // fallback
        'MEDIUM': 'bg-warning text-dark',
        'HIGH': 'bg-warning text-dark', // fallback
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
        'EXTREME': '#fa5252',
        'HIGH': '#ff922b',
        'MEDIUM': '#ffd43b',
        'LOW': '#51cf66',
        'OFFLINE': '#6c757d'
    };

    let currentLevel = station.risk_level;
    if (station.status === 'offline') {
        currentLevel = 'OFFLINE';
    } else if (!currentLevel || !colors[currentLevel]) {
        // ✅ Online mà không có risk_level → mặc định xanh (LOW)
        currentLevel = 'LOW';
    }
    const color = colors[currentLevel] || '#adb5bd';
    const shouldPulse = currentLevel === 'CRITICAL' || currentLevel === 'EXTREME' || currentLevel === 'HIGH' || currentLevel === 'MEDIUM';

    // ✅ KIỂM TRA CACHE: Nếu trạng thái không đổi thì KHÔNG LÀM GÌ CẢ
    const cacheKey = `${station.id}_${currentLevel}_${station.location.lat}_${station.location.lon}`;
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
            .addTo(map)
            .bindTooltip(station.name, { direction: 'top', offset: [0, -10] });

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
    const { skipZoom = false, skipSiren = false } = options;
    console.log(`🎯 [MAP] Selecting station: ${stationId}`, options);

    const sidebar = document.getElementById('detail-sidebar');
    if (sidebar) {
        sidebar.classList.add('active');
    }

    try {
        const res = await fetch(`/api/stations/${stationId}/detail`);
        if (!res.ok) throw new Error('Failed to load station detail');

        const data = await res.json();
        currentStationData = data;

        if (!skipZoom && markers[stationId]) {
            map.flyTo(markers[stationId].getLatLng(), 16, { duration: 1 });
        }

        updateSidebarUI(data);

        // ✅ Siren popup logic — có thể bị skip bởi caller (ví dụ: Track button tự quản lý)
        if (!skipSiren) {
            _showSirenIfAlerting(stationId, data);
        }

        // ✅ Restore alert banner + siren buttons im lặng nếu trạm đang có alert từ DB (sau reload)
        const _banner = document.getElementById('alert-banner');
        const _riskLevel = data.risk_assessment?.overall_risk || 'LOW';
        const _activeAlerts = data.risk_assessment?.active_alerts || [];
        if (!_banner?.classList.contains('show') &&
            (_riskLevel === 'HIGH' || _riskLevel === 'EXTREME') &&
            _activeAlerts.length > 0 &&
            data.status !== 'offline') {
            const _topAlert = _activeAlerts.find(a => a.level === 'CRITICAL') || _activeAlerts[0];
            // Show banner (silent — không kêu còi browser)
            showAlertBanner({
                station_id: data.id,
                level: _topAlert.level,
                message: _topAlert.message,
                sensor_type: _topAlert.category
            }, { silent: true });
            // Sync siren buttons đúng per-device (đã handle offline/online trong _showSirenIfAlerting)
            _showSirenIfAlerting(data.id, data);
        }

    } catch (e) {
        console.error('❌ [MAP] Error loading station detail:', e);
        window.toast?.error('Failed to load station info');
    }
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

function updateGnssFixBadge(fixMode, fixQuality) {
    const badge = document.getElementById('gnss-fix-badge');
    if (!badge) return;

    const normalizedMode = (fixMode || '').toString().trim().toUpperCase();
    const quality = Number(fixQuality);

    let cls = 'GNSS_UNKNOWN';
    let text = 'NO DATA';

    switch (normalizedMode) {
        case 'RTK_FIXED':
            cls = 'GNSS_RTK_FIXED';
            text = 'RTK FIXED';
            break;
        case 'RTK_FLOAT':
            cls = 'GNSS_RTK_FLOAT';
            text = 'RTK FLOAT';
            break;
        case 'DGPS_FLOAT':
            cls = 'GNSS_DGPS_FLOAT';
            text = 'DGPS FLOAT';
            break;
        case 'GPS_SINGLE_NO_RTK':
        case 'SINGLE':
        case 'NO_RTK':
            cls = 'GNSS_SINGLE';
            text = 'NO RTK';
            break;
        case 'INVALID':
            cls = 'GNSS_INVALID';
            text = 'INVALID';
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

function updateSidebarUI(data) {
    setText('st-name', data.name);
    setText('st-code', data.station_code);

    const riskEl = document.getElementById('st-risk');
    if (riskEl) {
        let rawRisk = data.risk_assessment?.overall_risk || data.risk_level || 'UNKNOWN';

        if (data.status === 'offline') {
            rawRisk = 'OFFLINE';
        }

        let displayRisk = rawRisk;
        let riskClass = rawRisk;

        if (rawRisk === 'LOW') {
            displayRisk = 'SAFE';
            riskClass = 'LOW';
        } else if (rawRisk === 'MEDIUM' || rawRisk === 'HIGH') {
            displayRisk = 'WARNING';
            riskClass = 'MEDIUM'; // Will use yellow/orange warning CSS
        } else if (rawRisk === 'EXTREME' || rawRisk === 'CRITICAL') {
            displayRisk = 'CRITICAL';
            riskClass = 'CRITICAL';
        } else if (rawRisk === 'OFFLINE') {
            displayRisk = 'OFFLINE';
            riskClass = 'OFFLINE';
        } else {
            displayRisk = 'SAFE'; // Default fallback
            riskClass = 'LOW';
        }

        riskEl.className = `status-badge ${riskClass}`;
        riskEl.innerHTML = `<span class="status-dot"></span> ${displayRisk}`;
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
    const gnssOnline  = mqttConnected && data.status !== 'offline' && (data.sensors?.gnss?.is_online  ?? false);
    const rainOnline  = mqttConnected && data.status !== 'offline' && (data.sensors?.rain?.is_online  ?? false);
    const waterOnline = mqttConnected && data.status !== 'offline' && (data.sensors?.water?.is_online ?? false);
    const imuOnline   = mqttConnected && data.status !== 'offline' && (data.sensors?.imu?.is_online   ?? false);

    if (gnssOnline) {
        updateGnssFixBadge(gnssLatest?.fix_mode, gnssLatest?.fix_quality);
    } else {
        updateGnssFixBadge('UNKNOWN', 0);
    }

    // ✅ Khi toàn trạm offline → hiển thị '--' cho TẤT CẢ sensor
    if (data.status === 'offline') {
        setHTML('val-gnss-vel', `--<span class="sensor-unit">mm/s</span>`);
        setHTML('val-rain', `--<span class="sensor-unit">mm/h</span>`);
        setHTML('val-water', `--<span class="sensor-unit">m</span>`);
        setText('val-imu-roll', '--°');
        setText('val-imu-pitch', '--°');
        setText('val-imu-yaw', '--°');
        setText('val-imu-delta-roll', '--°');
        setText('val-imu-delta-pitch', '--°');
        setText('val-imu-delta-yaw', '--°');
        updateImuDrift(null, null);

        // ✅ Khi offline, nút tắt còi chuyển xám (idle)
        setSirenButtonState('idle');

        // Ẩn battery khi offline
        const batteryContainer = document.getElementById('battery-container');
        if (batteryContainer) batteryContainer.style.display = 'none';
    } else {
        // GNSS: chỉ hiện giá trị khi sensor đang online
        if (gnssOnline) {
            const gnssSpeed = gnssLatest?.speed_2d_mm_s || (gnssLatest?.speed_2d ? gnssLatest.speed_2d * 1000 : null) || null;
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
            const waterLevel = waterLatest?.water_level ?? waterLatest?.processed_value_meters ?? null;
            setHTML('val-water', `${safeNumber(waterLevel, 2)}<span class="sensor-unit">m</span>`);
        } else {
            setHTML('val-water', `--<span class="sensor-unit">m</span>`);
        }

        // IMU
        if (imuOnline) {
            const useApiImu = !imuRealtimeTs || !imuApiTs || imuApiTs >= imuRealtimeTs;
            console.debug(`🧭 [IMU][MERGE] station=${stationId} api_ts=${imuApiTs || 'none'} ws_ts=${imuRealtimeTs || 'none'} source=${useApiImu ? 'api' : 'ws-cache'}`);

            if (useApiImu) {
                setText('val-imu-roll', `${safeNumber(imuLatest?.raw_roll, 1)}°`);
                setText('val-imu-pitch', `${safeNumber(imuLatest?.raw_pitch, 1)}°`);
                setText('val-imu-yaw', `${safeNumber(imuLatest?.raw_yaw, 1)}°`);
                setText('val-imu-delta-roll', `${safeNumber(imuLatest?.roll, 1)}°`);
                setText('val-imu-delta-pitch', `${safeNumber(imuLatest?.pitch, 1)}°`);
                setText('val-imu-delta-yaw', `${safeNumber(imuLatest?.yaw, 1)}°`);
            } else {
                console.warn(`⏭️ [IMU] Skip stale API overwrite station=${stationId} api_ts=${imuApiTs} < ws_ts=${imuRealtimeTs}`);
            }

            // Use backend drift calculation if available
            if (useApiImu) {
                if (imuLatest?.drift_len_mm !== undefined && imuLatest?.drift_dir !== undefined) {
                    setText('val-imu-drift-len', `${safeNumber(imuLatest.drift_len_mm, 1)} mm`);
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
            setText('val-imu-delta-roll', '--°');
            setText('val-imu-delta-pitch', '--°');
            setText('val-imu-delta-yaw', '--°');
            updateImuDrift(null, null);
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
        renderChart('chart-gnss', history, 'total_displacement_mm', '#fa5252', 'Displacement (mm)');
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
    const ctx = document.getElementById(id);
    if (!ctx) return;

    const labels = (history || []).map(h => {
        const date = new Date(h.timestamp * 1000);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });

    const values = (history || []).map(h => {
        const val = h.data?.[key];
        return val !== null && val !== undefined ? parseFloat(val) : 0;
    });

    if (charts[id]) {
        charts[id].destroy();
    }

    // Theme-aware colors
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const gridColor = isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)';
    const tickColor = isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.5)';

    charts[id] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: label,
                data: values,
                borderColor: color,
                tension: 0.3,
                borderWidth: 2,
                pointRadius: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { display: false },
                y: {
                    grid: { color: gridColor },
                    ticks: { color: tickColor }
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

async function loadLongTermAnalysis() {
    console.log('📊 [MAP] Loading long-term analysis...');

    if (!currentStationData) {
        console.error('❌ [MAP] No station selected');
        return;
    }

    const stationId = currentStationData.id;

    // Get selected days from range selector
    const activeBtn = document.querySelector('#longterm-range-selector .btn.active');
    const days = activeBtn ? parseFloat(activeBtn.dataset.days) || 30 : 30;

    document.getElementById('longterm-loading').style.display = 'block';
    document.getElementById('longterm-content').style.display = 'none';
    document.getElementById('longterm-error').style.display = 'none';

    try {
        const res = await fetch(`/api/stations/${stationId}/long-term-analysis?days=${days}`);

        if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || 'Failed to load analysis');
        }

        const data = await res.json();

        renderLongTermAnalysis(data);

    } catch (e) {
        console.error('❌ [MAP] Error loading long-term analysis:', e);
        showLongTermError(e.message);
    }
}

// Store last analysis data for re-rendering on time range change
let _lastLongTermData = null;

function renderLongTermAnalysis(data) {
    document.getElementById('longterm-loading').style.display = 'none';
    document.getElementById('longterm-content').style.display = 'block';
    document.getElementById('longterm-error').style.display = 'none';

    _lastLongTermData = data;

    // === GNSS Section ===
    const gnss = data.gnss;
    if (gnss && gnss.status === 'success') {
        const analysis = gnss.analysis;

        const warningEl = document.getElementById('longterm-warning');
        const warningTextEl = document.getElementById('warning-text');

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

        setText('lt-velocity', `${safeNumber(analysis.velocity_mm_year, 2)} mm/năm`);
        const ciVal = safeNumber(analysis.velocity_ci_95, 2);
        setText('lt-velocity-ci', `(Khoảng tin cậy: ±${ciVal})`);
        setText('lt-classification', analysis.classification || 'N/A');
        setText('lt-total-disp', `${safeNumber(analysis.total_displacement_mm, 1)} mm`);
        setText('lt-duration', `${safeNumber(analysis.duration_days, 1)} ngày`);

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
        if (warningEl) warningEl.style.display = 'none';
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

    // === NEW: Multi-Window Analysis ===
    renderMultiWindowSection(data);
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

    let progress = 0;
    const speed = 0.005;

    function animate() {
        gnssAnimationId = requestAnimationFrame(animate);

        // Animate sphere along the path
        if (points.length > 1) {
            progress += speed;
            if (progress >= 1) progress = 0; // loop

            const totalSegments = points.length - 1;
            const floatIndex = progress * totalSegments;
            const index = Math.floor(floatIndex);
            const remainder = floatIndex - index;

            if (index < totalSegments) {
                const p1 = points[index];
                const p2 = points[index + 1];
                sphere.position.lerpVectors(p1, p2, remainder);
            }
        } else if (points.length === 1) {
            sphere.position.copy(points[0]);
        }

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
    const boxDepth = 1.4;
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
    const screwGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.15, 16);
    const screwMat = new THREE.MeshStandardMaterial({ color: 0x999999, metalness: 0.9, roughness: 0.2 });

    for (let i = 0; i < 4; i++) {
        const angle = (i * Math.PI) / 2 + Math.PI / 4;
        const screw = new THREE.Mesh(screwGeo, screwMat);
        const radius = plateRadius - 0.3;
        screw.position.set(Math.cos(angle) * radius, plateThickness, Math.sin(angle) * radius);
        sensorBlock.add(screw);
    }

    // 5. Add visual XYZ axis indicators
    const origin = new THREE.Vector3(0, plateThickness + boxHeight + 0.2, 0);
    const xArrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), origin, 1.2, 0xff2a5f, 0.2, 0.15); // Red X
    const yArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), origin, 1.2, 0x00e5ff, 0.2, 0.15); // Cyan Y (Up)
    const zArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), origin, 1.2, 0x00ff88, 0.2, 0.15); // Green Z
    sensorBlock.add(xArrow, yArrow, zArrow);

    imuScene.add(sensorBlock);

    // Data parsing (backend sends 'rolls'/'pitches' plural)
    const rollData = timeSeries.rolls || timeSeries.roll || [];
    const pitchData = timeSeries.pitches || timeSeries.pitch || [];

    let progress = 0;
    const speed = 0.003; // Smooth flow

    // Hover animation variables
    let clock = new THREE.Clock();

    function animate() {
        imuAnimationId = requestAnimationFrame(animate);

        const delta = clock.getDelta();
        const elapsedTime = clock.getElapsedTime();

        // Removed vertical hover and glowing effect to keep the sensor realistic and grounded

        // 2. Playback IMU Tilt
        if (rollData.length > 1) {
            progress += speed;
            if (progress >= 1) progress = 0;

            const total = rollData.length - 1;
            const floatIndex = progress * total;
            const index = Math.floor(floatIndex);
            const remainder = floatIndex - index;

            if (index < total) {
                // Degrees to Radians
                const r1 = rollData[index] * Math.PI / 180;
                const r2 = rollData[index + 1] * Math.PI / 180;
                const p1 = pitchData[index] * Math.PI / 180;
                const p2 = pitchData[index + 1] * Math.PI / 180;

                const currRoll = r1 + (r2 - r1) * remainder;
                const currPitch = p1 + (p2 - p1) * remainder;

                // Typical aviation/IMU mapping: X=Pitch, Z=Roll
                const targetQuaternion = new THREE.Quaternion();
                const euler = new THREE.Euler(currPitch, 0, currRoll, 'XYZ');
                targetQuaternion.setFromEuler(euler);

                // Smooth interpolation to avoid jitter
                sensorBlock.quaternion.slerp(targetQuaternion, 0.1);
            }
        } else if (rollData.length === 1) {
            const currPitch = pitchData[0] * Math.PI / 180;
            const currRoll = rollData[0] * Math.PI / 180;
            const targetQuaternion = new THREE.Quaternion();
            const euler = new THREE.Euler(currPitch, 0, currRoll, 'XYZ');
            targetQuaternion.setFromEuler(euler);
            sensorBlock.quaternion.slerp(targetQuaternion, 0.1);
        }

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
        const boxDepth = 1.4;
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
        const screwGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.15, 16);
        const screwMat = new THREE.MeshStandardMaterial({ color: 0x999999, metalness: 0.9, roughness: 0.2 });
        for (let i = 0; i < 4; i++) {
            const angle = (i * Math.PI) / 2 + Math.PI / 4;
            const screw = new THREE.Mesh(screwGeo, screwMat);
            const radius = plateRadius - 0.3;
            screw.position.set(Math.cos(angle) * radius, plateThickness, Math.sin(angle) * radius);
            realtimeImuSensorBlock.add(screw);
        }

        // Axes Support
        const origin = new THREE.Vector3(0, plateThickness + boxHeight + 0.2, 0);
        const xArrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), origin, 1.2, 0xff2a5f, 0.2, 0.15);
        const yArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), origin, 1.2, 0x00e5ff, 0.2, 0.15);
        const zArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), origin, 1.2, 0x00ff88, 0.2, 0.15);
        realtimeImuSensorBlock.add(xArrow, yArrow, zArrow);

        realtimeImuScene.add(realtimeImuSensorBlock);

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
    setText('lt-imu-duration', `${safeNumber(analysis.duration_days, 1)} ngày`);

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
    if (!rainCorr || !rainCorr.available) {
        section.style.display = 'none';
        return;
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
    setText('rain-assessment', rainCorr.assessment || '--');

    // Chart: Dual-axis — cumulative displacement + cumulative/daily rainfall
    if (rainCorr.time_series) {
        const ctx = document.getElementById('chart-rainfall-correlation');
        if (!ctx) return;
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
}

// =========================================================================
// MULTI-WINDOW ANALYSIS SECTION
// =========================================================================
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
    if (mw.acceleration_alert) {
        alertEl.style.display = 'block';
        alertEl.className = `alert ${mw.acceleration_alert.type === 'rapid_acceleration' ? 'alert-danger' : 'alert-warning'} mb-3`;
        alertTextEl.textContent = mw.acceleration_alert.message;
    } else {
        alertEl.style.display = 'none';
    }

    // Window cards
    const cardsContainer = document.getElementById('multi-window-cards');
    if (!cardsContainer) return;

    const windowLabels = { 7: '7 ngày', 30: '30 ngày', 90: '90 ngày' };
    const windowIcons = { 7: 'bi-calendar-day', 30: 'bi-calendar-month', 90: 'bi-calendar3' };
    const trendIcons = { 'accelerating': '', 'stable': '', 'decelerating': '' };
    const trendTexts = { 'accelerating': 'Tăng tốc', 'stable': 'Ổn định', 'decelerating': 'Giảm tốc' };

    cardsContainer.innerHTML = (mw.windows || []).map(w => {
        if (w.status !== 'success') {
            return `
                <div class="col-md-4">
                    <div class="longterm-metric-card text-center opacity-50">
                        <div class="text-muted small"><i class="bi ${windowIcons[w.window_days] || 'bi-calendar'} me-1"></i>${windowLabels[w.window_days] || w.window_days + ' ngày'}</div>
                        <div class="fs-6 mt-1">Không đủ dữ liệu</div>
                    </div>
                </div>`;
        }

        return `
            <div class="col-md-4">
                <div class="longterm-metric-card">
                    <div class="text-muted small mb-2"><i class="bi ${windowIcons[w.window_days] || 'bi-calendar'} me-1"></i>${windowLabels[w.window_days] || w.window_days + ' ngày'}</div>
                    <div class="fs-4 fw-bold text-primary">${w.velocity_mm_year.toFixed(1)} <small class="fs-6 text-muted">mm/năm</small></div>
                    <div class="small mt-1">Dịch chuyển: <strong>${w.displacement_mm.toFixed(1)} mm</strong></div>
                    <div class="small">Xu hướng: ${trendIcons[w.trend] || ''} ${trendTexts[w.trend] || '--'}</div>
                    <div class="small text-muted">${w.data_points} điểm dữ liệu</div>
                </div>
            </div>`;
    }).join('');
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

    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
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
    const localTime = new Date(latestSensorTs * 1000).toLocaleString();

    if (!mqttConnected) {
        staleEl.innerHTML = `<span class="badge-label">STALE</span> Last data ${ageText} (${localTime})`;
        staleEl.style.display = 'block';
        return;
    }

    if (data.status === 'offline') {
        staleEl.innerHTML = `<span class="badge-label">OFFLINE</span> Last data ${ageText} (${localTime})`;
        staleEl.style.display = 'block';
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
        setText('val-imu-drift-len', '-- mm');
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

    animateValue('val-imu-drift-len', drift, 1, ' mm', true);
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
    if (level === 'WARNING') {
        card.classList.add('sensor-alert-warning');
    } else if (level === 'CRITICAL' || level === 'EXTREME') {
        card.classList.add('sensor-alert-critical');
    }
}

function clearAllSensorCardAlerts() {
    Object.values(SENSOR_CARD_IDS).forEach(id => {
        const card = document.getElementById(id);
        if (card) card.classList.remove('sensor-alert-warning', 'sensor-alert-critical');
    });
}

function showAlertBanner(alertData, options = {}) {
    const banner = document.getElementById('alert-banner');
    if (!banner) return;

    // ✅ Lookup station info từ allStations (đã load sẵn)
    const station = allStations.find(s => s.id === alertData.station_id);
    const stationName = station?.name || `Station #${alertData.station_id}`;
    const stationCode = station?.station_code || '';

    // Cập nhật nội dung
    document.getElementById('alert-title').textContent =
        options.silent ? `⚠️ ALERT (persistent)` : `${alertData.level.toUpperCase()} ALERT!`;

    document.getElementById('alert-station').textContent =
        `Station: ${stationName} (${stationCode})`;

    document.getElementById('alert-message').textContent =
        ` • ${alertData.message || 'Anomaly detected!'}`;

    // Lưu station ID
    currentAlertStationId = alertData.station_id;

    // Hiển thị banner (không auto-dismiss, user phải ấn X hoặc Theo dõi)
    // Lưu ý: siren button state được quản lý bởi _showSirenIfAlerting / WS handler,
    // không set ở đây để tránh override trạng thái offline của từng pi device.
    banner.classList.add('show');
}

let currentSirenAudio = null;
let pendingSirenReplay = false;

function playSiren() {
    try {
        if (!currentSirenAudio) {
            currentSirenAudio = new Audio('/static/sounds/siren.mp3');
            currentSirenAudio.loop = false; // Phát 1 lần cho mỗi sự kiện alert

            // Nếu có alert mới trong lúc đang phát, phát nối tiếp thêm 1 lần.
            currentSirenAudio.addEventListener('ended', () => {
                currentSirenAudio = null;
                if (pendingSirenReplay) {
                    pendingSirenReplay = false;
                    playSiren();
                }
            });

            currentSirenAudio.play().catch(e => {
                console.error('[ERROR] Siren auto-play blocked:', e);
                currentSirenAudio = null;
                pendingSirenReplay = false;
            });
        } else {
            pendingSirenReplay = true;
        }
    } catch (e) {
        console.error('[ERROR] playSiren error:', e);
        currentSirenAudio = null;
        pendingSirenReplay = false;
    }
}

function playAlertSound() {
    try {
        // Tạo beep sound đơn giản
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
document.addEventListener('DOMContentLoaded', () => {
    // Nút "Theo dõi" → Zoom vào trạm + ẩn banner + hiện siren popup sau khi zoom xong
    const btnFollow = document.getElementById('btn-alert-follow');
    if (btnFollow) {
        btnFollow.addEventListener('click', async () => {
            if (!currentAlertStationId) return;

            const alertStationId = currentAlertStationId;

            // 1. Ẩn banner ngay
            const banner = document.getElementById('alert-banner');
            if (banner) banner.classList.remove('show');

            // 2. Load dữ liệu trạm (skip zoom và siren — tự quản lý bên dưới)
            await selectStation(alertStationId, { skipZoom: true, skipSiren: true });

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
            if (banner) banner.classList.remove('show');
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
    charts
};

console.log('[MAP] Script fully loaded');