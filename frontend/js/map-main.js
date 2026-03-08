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
    console.log('📡 [WS] Received:', message);

    if (message.type === 'sensor_data') {
        if (currentStationData && message.station_id === currentStationData.id) {
            updateRealtimeSensorValues(message);
        }
    }

    if (message.type === 'station_status') {
        const riskLevel = message.risk_level;
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

            // 3. Reset siren popup về idle nếu đang xem trạm này
            if (currentStationData && stationId === currentStationData.id) {
                setSirenButtonState('idle');
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
                } else if (riskLevel === 'MEDIUM' || riskLevel === 'HIGH') {
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
        // Drop message.message from the key so dynamic numbers don't bypass dedup
        const alertKey = `${message.station_id}_${message.level}`;
        if (alertKey !== lastAlertKey) {
            lastAlertKey = alertKey;
            showAlertBanner(message);
        }
        // ✅ Marker chuyển đỏ + nhấp nháy khi có cảnh báo
        setMarkerAlert(message.station_id, true);
        // Always attempt to play siren (it will handle its own dedup/overlap)
        playSiren();
    }
}

function updateRealtimeSensorValues(message) {
    const { sensor_type, data, timestamp } = message;

    console.log(`🔄 [REALTIME] ${sensor_type}:`, data);

    if (sensor_type === 'gnss' && data) {
        const velocityMmS = data.velocity_mm_s ||
            data.speed_2d_mm_s ||
            data.speed_mm_s ||
            (data.speed_2d ? data.speed_2d * 1000 : null) ||
            (data.velocity ? data.velocity * 1000 : null) ||
            (data.speed ? data.speed * 1000 : null) || 0;

        console.log('📍 [GNSS] Velocity value:', velocityMmS, 'from data:', data);
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
        animateValue('val-imu-roll', data.raw_roll, 1, '°', true);
        animateValue('val-imu-pitch', data.raw_pitch, 1, '°', true);
        animateValue('val-imu-yaw', data.raw_yaw, 1, '°', true);

        // Delta values (secondary display)
        animateValue('val-imu-delta-roll', data.roll, 1, '°', true);
        animateValue('val-imu-delta-pitch', data.pitch, 1, '°', true);
        animateValue('val-imu-delta-yaw', data.yaw, 1, '°', true);

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

    const colors = {
        'EXTREME': '#fa5252',
        'HIGH': '#ff922b',
        'MEDIUM': '#ffd43b',
        'LOW': '#51cf66'
    };

    // ✅ Online mà không có risk_level → mặc định xanh (LOW)
    const effectiveLevel = (riskLevel && colors[riskLevel]) ? riskLevel : 'LOW';
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
            stationSidebar.classList.add('force-hidden');

            console.log('📊 [CHARTS] Charts panel opened');

            if (currentStationData) {
                renderCharts(currentStationData);
            }
        });
    }

    if (closeChartsBtn && chartsPanel) {
        closeChartsBtn.addEventListener('click', () => {
            chartsPanel.classList.remove('active');

            // Mở lại sidebar trái
            stationSidebar.classList.remove('force-hidden');
            stationSidebar.classList.remove('hidden');

            console.log('📊 [CHARTS] Charts panel closed');
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
            stationSidebar.classList.add('force-hidden');

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

            // Mở lại sidebar trái
            stationSidebar.classList.remove('force-hidden');
            stationSidebar.classList.remove('hidden');

            console.log('📊 [LONGTERM] Analysis overlay closed');
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
    // Only show siren controls for admin and operator roles
    const user = window.authManager?.getUserInfo();
    const userRole = user?.role;
    if (userRole !== 'admin' && userRole !== 'operator') {
        const popup = document.getElementById('siren-bottom-popup');
        if (popup) popup.style.bottom = '-120px';
        return;
    }

    const risk = data.risk_assessment?.overall_risk || data.risk_level;
    const isAlerting = (risk === 'EXTREME' || risk === 'CRITICAL') && data.status !== 'offline';

    const popupStationName = document.getElementById('siren-popup-station');
    if (popupStationName) popupStationName.textContent = `${data.name} (${data.station_code})`;

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

    // ✅ Khi thiết bị offline → hiển thị '--' cho TẤT CẢ sensor
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

        // ✅ Khi offline, nút tắt còi chuyển xám (idle)
        setSirenButtonState('idle');

        // Ẩn battery khi offline
        const batteryContainer = document.getElementById('battery-container');
        if (batteryContainer) batteryContainer.style.display = 'none';
    } else {
        const gnssSpeed = gnssLatest?.speed_2d_mm_s || (gnssLatest?.speed_2d ? gnssLatest.speed_2d * 1000 : null) || null;
        setHTML('val-gnss-vel', `${safeNumber(gnssSpeed, 4)}<span class="sensor-unit">mm/s</span>`);

        const rainIntensity = rainLatest?.intensity_mm_h ?? null;
        setHTML('val-rain', `${safeNumber(rainIntensity, 1)}<span class="sensor-unit">mm/h</span>`);

        const waterLevel = waterLatest?.water_level ?? waterLatest?.processed_value_meters ?? null;
        setHTML('val-water', `${safeNumber(waterLevel, 2)}<span class="sensor-unit">m</span>`);

        setText('val-imu-roll', `${safeNumber(imuLatest?.raw_roll, 1)}°`);
        setText('val-imu-pitch', `${safeNumber(imuLatest?.raw_pitch, 1)}°`);
        setText('val-imu-yaw', `${safeNumber(imuLatest?.raw_yaw, 1)}°`);

        // ✅ Delta values (secondary display)
        setText('val-imu-delta-roll', `${safeNumber(imuLatest?.roll, 1)}°`);
        setText('val-imu-delta-pitch', `${safeNumber(imuLatest?.pitch, 1)}°`);
        setText('val-imu-delta-yaw', `${safeNumber(imuLatest?.yaw, 1)}°`);

        // ✅ Battery Voltage: hiển thị nếu có giá trị > 0
        const batteryContainer = document.getElementById('battery-container');
        const batteryVal = imuLatest?.battery;
        if (batteryVal !== undefined && batteryVal !== null && parseFloat(batteryVal) > 0) {
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

    document.getElementById('longterm-loading').style.display = 'block';
    document.getElementById('longterm-content').style.display = 'none';
    document.getElementById('longterm-error').style.display = 'none';

    try {
        const res = await fetch(`/api/stations/${stationId}/long-term-analysis?days=30`);

        if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || 'Failed to load analysis');
        }

        const data = await res.json();

        if (data.status === 'insufficient_data') {
            showLongTermError(data.message);
            return;
        }

        renderLongTermAnalysis(data);

    } catch (e) {
        console.error('❌ [MAP] Error loading long-term analysis:', e);
        showLongTermError(e.message);
    }
}

function renderLongTermAnalysis(data) {
    document.getElementById('longterm-loading').style.display = 'none';
    document.getElementById('longterm-content').style.display = 'block';
    document.getElementById('longterm-error').style.display = 'none';

    const analysis = data.analysis;

    const warningEl = document.getElementById('longterm-warning');
    const warningTextEl = document.getElementById('warning-text');

    if (data.risk_level === 'EXTREME' || data.risk_level === 'HIGH') {
        warningEl.style.display = 'block';
        warningEl.className = `alert ${data.risk_level === 'EXTREME' ? 'alert-danger' : 'alert-warning'}`;
        warningTextEl.textContent = data.warning_message;
    } else {
        warningEl.style.display = 'none';
    }

    setText('lt-velocity', `${safeNumber(analysis.velocity_mm_year, 2)} mm/năm`);
    setText('lt-classification', analysis.classification || 'N/A');
    setText('lt-total-disp', `${safeNumber(analysis.total_displacement_mm, 1)} mm`);
    setText('lt-duration', `${safeNumber(analysis.duration_days, 1)} ngày`);

    const trendIconEl = document.getElementById('trend-icon');
    const trendValueEl = document.getElementById('trend-value');

    const trendIcons = {
        'accelerating': '📈',
        'stable': '➡️',
        'decelerating': '📉'
    };

    const trendTexts = {
        'accelerating': 'Đang tăng tốc',
        'stable': 'Ổn định',
        'decelerating': 'Đang giảm tốc'
    };

    trendIconEl.textContent = trendIcons[analysis.trend] || '❓';
    trendValueEl.textContent = trendTexts[analysis.trend] || 'Không xác định';

    renderClassificationScale(analysis.classification, analysis.velocity_mm_year);
    renderLongTermChart(data);
}

function renderClassificationScale(currentClass, velocity) {
    const scaleContainer = document.getElementById('classification-scale');

    const classifications = [
        { name: 'Extremely rapid', color: '#dc2626', range: '> 5 m/s' },
        { name: 'Very rapid', color: '#ea580c', range: '3 m/min - 5 m/s' },
        { name: 'Rapid', color: '#f59e0b', range: '1.8 m/h - 3 m/min' },
        { name: 'Moderate', color: '#eab308', range: '13 mm/month - 1.8 m/h' },
        { name: 'Slow', color: '#84cc16', range: '1.6 m/year - 13 mm/month' },
        { name: 'Very slow', color: '#10b981', range: '16 mm/year - 1.6 m/year' },
        { name: 'Extremely slow', color: '#3b82f6', range: '< 16 mm/year' }
    ];

    scaleContainer.innerHTML = classifications.map(cls => `
                <div class="classification-item ${cls.name === currentClass ? 'active' : ''}">
                    <div class="classification-color" style="background: ${cls.color};"></div>
                    <div class="classification-name">${cls.name}</div>
                    <div class="classification-range">${cls.range}</div>
                </div>
            `).join('');
}

function renderLongTermChart(data) {
    const ctx = document.getElementById('chart-longterm');
    if (!ctx) return;

    if (charts['chart-longterm']) {
        charts['chart-longterm'].destroy();
    }

    const labels = ['Week 1', 'Week 2', 'Week 3', 'Week 4'];
    const values = [10, 25, 35, data.analysis.total_displacement_mm];

    charts['chart-longterm'] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Cumulative Displacement (mm)',
                data: values,
                borderColor: '#0ea5e9',
                backgroundColor: 'rgba(14, 165, 233, 0.1)',
                tension: 0.4,
                borderWidth: 3,
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    padding: 12
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: 'var(--text-secondary)' }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: 'var(--text-secondary)' }
                }
            }
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

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.innerText = val || '--';
}

function setHTML(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
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
    const popup = document.getElementById('siren-bottom-popup');
    if (!popup) return;

    const btns = target
        ? document.querySelectorAll(`.btn-siren-toggle[data-target="${target}"]`)
        : document.querySelectorAll('.btn-siren-toggle');

    btns.forEach(btn => {
        btn.setAttribute('data-siren-state', state);
        const iconBase = btn.getAttribute('data-target') === 'pi_center' ? 'Center' : 'Point';

        switch (state) {
            case 'idle':
                btn.disabled = true;
                btn.classList.add('disabled', 'btn-danger');
                btn.classList.remove('btn-success', 'btn-secondary');
                btn.style.opacity = '1';
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
                btn.style.opacity = '0.6';
                btn.innerHTML = `<i class="bi bi-plug-fill me-1"></i>Offline`;
                break;
        }
    });

    // Check if any button is NOT idle and NOT offline, if so, show popup
    const allBtns = document.querySelectorAll('.btn-siren-toggle');
    const anyActive = Array.from(allBtns).some(b => {
        const s = b.getAttribute('data-siren-state');
        return s !== 'idle' && s !== 'offline';
    });

    if (!anyActive) {
        popup.style.bottom = '-120px';
    } else {
        popup.style.bottom = '8px';
    }
}

// =========================================================================
// ALERT BANNER SYSTEM
// =========================================================================

let currentAlertStationId = null;
let lastAlertKey = null;

function showAlertBanner(alertData) {
    const banner = document.getElementById('alert-banner');
    if (!banner) return;

    // ✅ Lookup station info từ allStations (đã load sẵn)
    const station = allStations.find(s => s.id === alertData.station_id);
    const stationName = station?.name || `Station #${alertData.station_id}`;
    const stationCode = station?.station_code || '';

    // Cập nhật nội dung
    document.getElementById('alert-title').textContent =
        `${alertData.level.toUpperCase()} ALERT!`;

    document.getElementById('alert-station').textContent =
        `Station: ${stationName} (${stationCode})`;

    document.getElementById('alert-message').textContent =
        ` • ${alertData.message || 'Anomaly detected!'}`;

    // Lưu station ID
    currentAlertStationId = alertData.station_id;

    // ✅ Kích hoạt nút "Tắt âm báo" khi có cảnh báo
    setSirenButtonState('alerting');

    // Hiển thị banner (không auto-dismiss, user phải ấn X hoặc Theo dõi)
    banner.classList.add('show');
}

let currentSirenAudio = null;

function playSiren() {
    try {
        if (!currentSirenAudio) {
            currentSirenAudio = new Audio('/static/sounds/siren.mp3');
            currentSirenAudio.loop = false; // Phát 1 lần cho mỗi sự kiện alert

            // Xóa biến khi phát xong để cho phép phát lại
            currentSirenAudio.addEventListener('ended', () => {
                currentSirenAudio = null;
            });

            currentSirenAudio.play().catch(e => {
                console.error('[ERROR] Siren auto-play blocked:', e);
                currentSirenAudio = null;
            });
        }
    } catch (e) {
        console.error('[ERROR] playSiren error:', e);
        currentSirenAudio = null;
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