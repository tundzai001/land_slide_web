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
        updateStationMarker(message.station_id, message.risk_level);

        if (currentStationData && message.station_id === currentStationData.id) {
            const riskEl = document.getElementById('st-risk');
            if (riskEl) {
                riskEl.className = `risk-badge ${message.risk_level}`;
                riskEl.innerText = `Cảnh báo: ${message.risk_level}`;
            }
        }

        const listBadge = document.getElementById(`list-badge-${message.station_id}`);
        if (listBadge) {
            listBadge.className = `badge ${getRiskBadgeClass(message.risk_level)}`;
            listBadge.innerText = message.risk_level;

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
        setHTML('val-gnss-vel', `${safeNumber(velocityMmS, 4)}<span class="sensor-unit">mm/s</span>`);

        const displacement = data.total_displacement_mm || data.displacement_mm || data.displacement || 0;

        if (charts['chart-gnss']) {
            const chart = charts['chart-gnss'];
            chart.data.labels.push(new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
            chart.data.datasets[0].data.push(displacement);

            if (chart.data.labels.length > 50) {
                chart.data.labels.shift();
                chart.data.datasets[0].data.shift();
            }

            chart.update('none');
        }
    }

    if (sensor_type === 'rain' && data) {
        const intensity = data.intensity_mm_h || data.intensity || 0;
        setHTML('val-rain', `${safeNumber(intensity, 1)}<span class="sensor-unit">mm/h</span>`);

        if (charts['chart-rain']) {
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
        setHTML('val-water', `${safeNumber(level, 2)}<span class="sensor-unit">m</span>`);

        if (charts['chart-water']) {
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
        setText('val-imu-roll', `${safeNumber(data.roll, 1)}°`);
        setText('val-imu-pitch', `${safeNumber(data.pitch, 1)}°`);
        setText('val-imu-yaw', `${safeNumber(data.yaw, 1)}°`);

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

            chart.update('none');
        }
    }
}

function updateStationMarker(stationId, riskLevel) {
    const marker = markers[stationId];
    if (!marker) return;

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

function updateSidebarUI(data) {
    setText('st-name', data.name);
    setText('st-code', data.station_code);

    const riskEl = document.getElementById('st-risk');
    if (riskEl) {
        let risk = data.risk_assessment?.overall_risk || 'UNKNOWN';

        if (data.status === 'offline') {
            risk = 'OFFLINE';
        }

        riskEl.className = `risk-badge ${risk}`;
        riskEl.innerText = `Cảnh báo: ${risk}`;
    }

    const gnssLatest = data.sensors?.gnss?.latest;
    const rainLatest = data.sensors?.rain?.latest;
    const waterLatest = data.sensors?.water?.latest;
    const imuLatest = data.sensors?.imu?.latest;

    // GNSS
    const gnssSpeed = gnssLatest?.speed_2d_mm_s || (gnssLatest?.speed_2d ? gnssLatest.speed_2d * 1000 : null) || null;
    setHTML('val-gnss-vel', `${safeNumber(gnssSpeed, 4)}<span class="sensor-unit">mm/s</span>`);

    // Rain
    const rainIntensity = rainLatest?.intensity_mm_h ?? null;
    setHTML('val-rain', `${safeNumber(rainIntensity, 1)}<span class="sensor-unit">mm/h</span>`);

    // Water
    const waterLevel = waterLatest?.water_level ?? waterLatest?.processed_value_meters ?? null;
    setHTML('val-water', `${safeNumber(waterLevel, 2)}<span class="sensor-unit">m</span>`);

    // IMU Angles
    setText('val-imu-roll', `${safeNumber(imuLatest?.roll, 1)}°`);
    setText('val-imu-pitch', `${safeNumber(imuLatest?.pitch, 1)}°`);
    setText('val-imu-yaw', `${safeNumber(imuLatest?.yaw, 1)}°`);

    // ✅ LOGIC MỚI: Kiểm tra và hiển thị Pin
    const batteryContainer = document.getElementById('battery-container');
    const batteryVal = imuLatest?.battery; // Lấy giá trị Pin từ dữ liệu mới nhất

    // Nếu có Pin và Pin > 0 thì hiển thị, ngược lại thì ẩn
    if (batteryVal !== undefined && batteryVal !== null && parseFloat(batteryVal) > 0) {
        if (batteryContainer) batteryContainer.style.display = 'flex'; // Hiện
        setHTML('val-battery', `${safeNumber(batteryVal, 2)}<span class="sensor-unit">V</span>`);
    } else {
        if (batteryContainer) batteryContainer.style.display = 'none'; // Ẩn
    }
}

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
        let displayLevel = st.risk_level;
        if (st.status === 'offline') {
            displayLevel = 'OFFLINE';
        }

        const div = document.createElement('div');
        div.className = 'station-item';
        div.innerHTML = `
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <div class="fw-bold" style="color: var(--text-primary)">${st.name}</div>
                            <small style="color: var(--text-secondary)">${st.station_code}</small>
                        </div>
                        <span id="list-badge-${st.id}" class="badge ${getRiskBadgeClass(displayLevel)}">
                            ${displayLevel || 'N/A'}
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
        'EXTREME': 'bg-danger',
        'HIGH': 'bg-warning text-dark',
        'MEDIUM': 'bg-warning text-dark',
        'LOW': 'bg-success',
        'OFFLINE': 'bg-secondary'
    };
    return classes[level] || 'bg-success';
}

// ✅ BOOST 3: Cache trạng thái marker để tránh vẽ lại không cần thiết
let stationStateCache = {};

function updateMarker(station) {
    const colors = {
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
    const shouldPulse = currentLevel === 'EXTREME' || currentLevel === 'HIGH';

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

async function selectStation(stationId) {
    console.log(`🎯 [MAP] Selecting station: ${stationId}`);

    const sidebar = document.getElementById('detail-sidebar');
    if (sidebar) {
        sidebar.classList.add('active');
    }

    try {
        const res = await fetch(`/api/stations/${stationId}/detail`);
        if (!res.ok) throw new Error('Failed to load station detail');

        const data = await res.json();
        currentStationData = data;

        if (markers[stationId]) {
            map.flyTo(markers[stationId].getLatLng(), 16, { duration: 1 });
        }

        updateSidebarUI(data);

    } catch (e) {
        console.error('❌ [MAP] Error loading station detail:', e);
        window.toast?.error('Không thể tải thông tin trạm');
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
        let risk = data.risk_assessment?.overall_risk || 'UNKNOWN';

        if (data.status === 'offline') {
            risk = 'OFFLINE';
        }

        riskEl.className = `risk-badge ${risk}`;
        riskEl.innerText = `Cảnh báo: ${risk}`;
    }

    const gnssLatest = data.sensors?.gnss?.latest;
    const rainLatest = data.sensors?.rain?.latest;
    const waterLatest = data.sensors?.water?.latest;
    const imuLatest = data.sensors?.imu?.latest;

    const gnssSpeed = gnssLatest?.speed_2d_mm_s || (gnssLatest?.speed_2d ? gnssLatest.speed_2d * 1000 : null) || null;
    setHTML('val-gnss-vel', `${safeNumber(gnssSpeed, 4)}<span class="sensor-unit">mm/s</span>`);

    const rainIntensity = rainLatest?.intensity_mm_h ?? null;
    setHTML('val-rain', `${safeNumber(rainIntensity, 1)}<span class="sensor-unit">mm/h</span>`);

    const waterLevel = waterLatest?.water_level ?? waterLatest?.processed_value_meters ?? null;
    setHTML('val-water', `${safeNumber(waterLevel, 2)}<span class="sensor-unit">m</span>`);

    // IMU — only show values if station is online
    if (data.status === 'offline') {
        setText('val-imu-roll', '--°');
        setText('val-imu-pitch', '--°');
        setText('val-imu-yaw', '--°');
    } else {
        setText('val-imu-roll', `${safeNumber(imuLatest?.roll, 1)}°`);
        setText('val-imu-pitch', `${safeNumber(imuLatest?.pitch, 1)}°`);
        setText('val-imu-yaw', `${safeNumber(imuLatest?.yaw, 1)}°`);
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

function filterStations(searchTerm) {
    const items = document.querySelectorAll('.station-item');
    const term = searchTerm.toLowerCase();

    items.forEach(item => {
        const text = item.textContent.toLowerCase();
        item.style.display = text.includes(term) ? 'block' : 'none';
    });
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
        `⚠️ ${alertData.level.toUpperCase()} ALERT!`;

    document.getElementById('alert-station').textContent =
        `Trạm: ${stationName} (${stationCode})`;

    document.getElementById('alert-message').textContent =
        alertData.message || 'Phát hiện bất thường!';

    // Lưu station ID
    currentAlertStationId = alertData.station_id;


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
    // Nút "Theo dõi"
    const btnFollow = document.getElementById('btn-alert-follow');
    if (btnFollow) {
        btnFollow.addEventListener('click', () => {
            if (currentAlertStationId) {
                // Zoom vào trạm (banner vẫn hiện, chỉ tắt khi bấm "X")
                selectStation(currentAlertStationId);

                // Nếu có marker, zoom vào nó
                if (markers[currentAlertStationId]) {
                    map.flyTo(markers[currentAlertStationId].getLatLng(), 16, {
                        duration: 1.5
                    });
                }
            }
        });
    }

    // Nút "Đóng"
    const btnDismiss = document.getElementById('btn-alert-dismiss');
    if (btnDismiss) {
        btnDismiss.addEventListener('click', () => {
            document.getElementById('alert-banner').classList.remove('show');
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
    charts
};

console.log('[MAP] Script fully loaded');