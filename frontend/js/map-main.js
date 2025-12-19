// =====================================================
// MAP MAIN LOGIC ( frontend/js/map-main.js )
// =====================================================

console.log('🚀 [MAP] Script loaded, waiting for DOM...');

let map;
let markers = {};
let charts = {};
let currentStationData = null;
let allStations = [];
let currentView = 'realtime'; // 'realtime' or 'longterm'

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
    
    // ✅ FIXED: Ẩn sidebar khi vừa load trang
    const stationSidebar = document.getElementById('station-list-sidebar');
    if (stationSidebar) {
        stationSidebar.classList.add('hidden');
        console.log('✅ [MAP] Station sidebar hidden by default');
    }
    
    // ✅ FIXED: Đặt icon ban đầu là hamburger (list)
    const toggleBtn = document.getElementById('toggle-list-btn');
    if (toggleBtn) {
        toggleBtn.innerHTML = '<i class="bi bi-list"></i>';
        console.log('✅ [MAP] Toggle button initialized');
    }
    
    setInterval(loadStations, 30000);
    
    console.log('✅ [MAP] Initialization complete!');
}

// =====================================================
// EVENT LISTENERS SETUP
// =====================================================

function setupEventListeners() {
    console.log('🔧 [MAP] Setting up event listeners...');
    
    // ✅ Toggle station list sidebar
    const toggleListBtn = document.getElementById('toggle-list-btn');
    const sidebarCloseTab = document.getElementById('sidebar-close-tab');
    const stationSidebar = document.getElementById('station-list-sidebar');
    
    if (toggleListBtn && stationSidebar) {
        toggleListBtn.addEventListener('click', () => {
            stationSidebar.classList.remove('hidden');
            console.log('📂 [MAP] Sidebar opened');
        });
    }
    
    // ✅ NÚT ĐÓNG SIDEBAR (Close tab - trong sidebar)
    if (sidebarCloseTab && stationSidebar) {
        sidebarCloseTab.addEventListener('click', () => {
            stationSidebar.classList.add('hidden');
            console.log('📁 [MAP] Sidebar closed');
        });
    }
    
    // Close detail sidebar
    const closeDetailBtn = document.getElementById('close-btn');
    const detailSidebar = document.getElementById('detail-sidebar');
    
    if (closeDetailBtn && detailSidebar) {
        closeDetailBtn.addEventListener('click', () => {
            detailSidebar.classList.remove('active');
            detailSidebar.classList.remove('expanded');
            detailSidebar.classList.remove('fullwidth');
            
            // Reset views
            document.getElementById('realtime-view').style.display = 'block';
            document.getElementById('longterm-view').style.display = 'none';
            document.getElementById('charts-container').classList.remove('active');
            
            // Show station list again
            if (stationSidebar) {
                stationSidebar.classList.remove('hidden');
            }
        });
    }
    
    // Theme toggle
    const themeToggleBtn = document.getElementById('theme-toggle-btn');
    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', () => {
            if (window.themeManager) {
                window.themeManager.toggle();
            }
        });
    }
    
    // Search
    const searchInput = document.getElementById('search-station');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            filterStations(e.target.value);
        });
    }
    
    // ✅ "Xem biểu đồ" button
    const btnShowCharts = document.getElementById('btn-show-charts');
    if (btnShowCharts) {
        btnShowCharts.addEventListener('click', () => {
            const chartsContainer = document.getElementById('charts-container');
            const isActive = chartsContainer.classList.contains('active');
            
            if (isActive) {
                // Đóng charts
                detailSidebar.classList.remove('expanded');
                chartsContainer.classList.remove('active');
                stationSidebar.classList.remove('collapsed');
                btnShowCharts.innerHTML = '<i class="bi bi-graph-up me-2"></i>Xem biểu đồ';
            } else {
                // Mở charts
                detailSidebar.classList.add('expanded');
                chartsContainer.classList.add('active');
                stationSidebar.classList.add('collapsed');
                btnShowCharts.innerHTML = '<i class="bi bi-x me-2"></i>Đóng biểu đồ';
                
                if (currentStationData) {
                    renderCharts(currentStationData);
                }
            }
        });
    }
    
    // ✅ "Phân tích dài hạn" button
    const btnLongTerm = document.getElementById('btn-long-term');
    if (btnLongTerm) {
        btnLongTerm.addEventListener('click', () => {
            const longtermView = document.getElementById('longterm-view');
            const isActive = longtermView.style.display === 'block';
            
            if (isActive) {
                // Đóng long-term
                switchView('realtime');
                detailSidebar.classList.remove('fullwidth');
                stationSidebar.classList.remove('hidden');
                btnLongTerm.innerHTML = '<i class="bi bi-calendar-range me-2"></i>Phân tích dài hạn';
            } else {
                // Mở long-term
                switchView('longterm');
                detailSidebar.classList.add('fullwidth');
                stationSidebar.classList.add('hidden');
                btnLongTerm.innerHTML = '<i class="bi bi-x me-2"></i>Đóng phân tích';
                
                loadLongTermAnalysis();
            }
        });
    }
    
    console.log('✅ [MAP] All event listeners setup complete');
}

// =====================================================
// VIEW SWITCHING
// =====================================================

function switchView(view) {
    console.log(`🔄 [MAP] Switching to ${view} view`);
    
    currentView = view;
    
    const realtimeView = document.getElementById('realtime-view');
    const longtermView = document.getElementById('longterm-view');
    
    if (view === 'realtime') {
        realtimeView.style.display = 'block';
        longtermView.style.display = 'none';
    } else if (view === 'longterm') {
        realtimeView.style.display = 'none';
        longtermView.style.display = 'block';
    }
}

// =====================================================
// MAP INITIALIZATION
// =====================================================

function initMap() {
    try {
        map = L.map('map', { zoomControl: false }).setView([16.047079, 108.206230], 6);
        L.control.zoom({ position: 'bottomright' }).addTo(map);

        L.tileLayer('http://{s}.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', {
            maxZoom: 20,
            subdomains: ['mt0', 'mt1', 'mt2', 'mt3']
        }).addTo(map);
        
        console.log('✅ [MAP] Leaflet map initialized');
    } catch (error) {
        console.error('❌ [MAP] Failed to initialize map:', error);
    }
}

// =====================================================
// DATA LOADING
// =====================================================

async function loadStations() {
    try {
        console.log('📡 [MAP] Loading stations...');
        
        const res = await fetch('/api/stations');
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }
        
        const stations = await res.json();
        console.log(`✅ [MAP] Loaded ${stations.length} stations`);
        
        allStations = stations;

        stations.forEach(station => {
            if (station.location && station.location.lat && station.location.lon) {
                updateMarker(station);
            }
        });

        renderStationList(stations);

    } catch (e) {
        console.error('❌ [MAP] Error loading stations:', e);
        
        const container = document.getElementById('station-list-container');
        if (container) {
            container.innerHTML = `
                <div class="text-center text-muted mt-4">
                    <i class="bi bi-exclamation-triangle fs-1"></i>
                    <p class="mt-2">Không thể tải dữ liệu trạm</p>
                    <small>${e.message}</small>
                </div>
            `;
        }
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
        const div = document.createElement('div');
        div.className = 'station-item';
        div.innerHTML = `
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <div class="fw-bold text-white">${st.name}</div>
                    <small class="text-muted">${st.station_code}</small>
                </div>
                <span class="badge ${getRiskBadgeClass(st.risk_level)}">${st.risk_level || 'N/A'}</span>
            </div>
        `;
        
        div.addEventListener('click', () => {
            selectStation(st.id);
            
            // Auto-hide station list on mobile
            if (window.innerWidth < 768) {
                const sidebar = document.getElementById('station-list-sidebar');
                if (sidebar) {
                    sidebar.classList.add('hidden');
                }
            }
        });
        
        container.appendChild(div);
    });
    
    console.log(`✅ [MAP] Rendered ${stations.length} stations in list`);
}

function getRiskBadgeClass(level) {
    const classes = {
        'EXTREME': 'bg-danger',
        'HIGH': 'bg-warning text-dark',
        'MEDIUM': 'bg-warning text-dark',
        'LOW': 'bg-success'
    };
    return classes[level] || 'bg-success';
}

function updateMarker(station) {
    const colors = {
        'EXTREME': '#fa5252',
        'HIGH': '#ff922b',
        'MEDIUM': '#ffd43b',
        'LOW': '#51cf66'
    };
    const color = colors[station.risk_level] || '#adb5bd';
    
    if (markers[station.id]) {
        markers[station.id].setLatLng([station.location.lat, station.location.lon]);
        const el = markers[station.id].getElement();
        if (el) {
            const circle = el.querySelector('div');
            if (circle) circle.style.background = color;
        }
    } else {
        const div = document.createElement('div');
        div.style.cssText = `
            width: 18px; height: 18px; background: ${color};
            border-radius: 50%; border: 2px solid white;
            box-shadow: 0 0 8px rgba(0,0,0,0.5);
        `;
        
        const icon = L.divIcon({ 
            className: '', 
            html: div, 
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
// STATION SELECTION & UI
// =====================================================

async function selectStation(stationId) {
    console.log(`🎯 [MAP] Selecting station: ${stationId}`);
    
    // Reset to realtime view
    switchView('realtime');
    
    const sidebar = document.getElementById('detail-sidebar');
    if (sidebar) {
        sidebar.classList.add('active');
        sidebar.classList.remove('expanded');
        sidebar.classList.remove('fullwidth');
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
        console.log(`✅ [MAP] Station detail loaded: ${data.name}`);
        
    } catch (e) {
        console.error('❌ [MAP] Error loading station detail:', e);
        window.toast?.error('Không thể tải thông tin trạm');
    }
}

// ✅ FIXED: Safe number parsing to prevent toFixed errors
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
        const risk = data.risk_assessment?.overall_risk || 'UNKNOWN';
        riskEl.className = `risk-badge ${risk}`;
        riskEl.innerText = `Cảnh báo: ${risk}`;
    }

    // ✅ FIXED: Safe value extraction with proper null checks
    const gnssLatest = data.sensors?.gnss?.latest;
    const rainLatest = data.sensors?.rain?.latest;
    const waterLatest = data.sensors?.water?.latest;
    const imuLatest = data.sensors?.imu?.latest;

    // GNSS - Use speed_2d or fallback to 0
    const gnssSpeed = gnssLatest?.speed_2d ?? gnssLatest?.vel_2d ?? null;
    setHTML('val-gnss-vel', `${safeNumber(gnssSpeed, 4)}<span class="sensor-unit">mm/s</span>`);

    // Rain - Use intensity_mm_h
    const rainIntensity = rainLatest?.intensity_mm_h ?? null;
    setHTML('val-rain', `${safeNumber(rainIntensity, 1)}<span class="sensor-unit">mm/h</span>`);

    // Water - Use water_level or processed_value_meters
    const waterLevel = waterLatest?.water_level ?? waterLatest?.processed_value_meters ?? null;
    setHTML('val-water', `${safeNumber(waterLevel, 2)}<span class="sensor-unit">m</span>`);

    // IMU - Roll, Pitch, Yaw
    setText('val-imu-roll', `${safeNumber(imuLatest?.roll, 1)}°`);
    setText('val-imu-pitch', `${safeNumber(imuLatest?.pitch, 1)}°`);
    setText('val-imu-yaw', `${safeNumber(imuLatest?.yaw, 1)}°`);

    renderCharts(data);
}

// =====================================================
// LONG-TERM ANALYSIS
// =====================================================

async function loadLongTermAnalysis() {
    console.log('📊 [MAP] Loading long-term analysis...');
    
    if (!currentStationData) {
        console.error('❌ [MAP] No station selected');
        return;
    }
    
    const stationId = currentStationData.id;
    
    // Show loading
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
        console.log('✅ [MAP] Long-term analysis loaded:', data);
        
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
    
    // Warning banner
    const warningEl = document.getElementById('longterm-warning');
    const warningTextEl = document.getElementById('warning-text');
    
    if (data.risk_level === 'EXTREME' || data.risk_level === 'HIGH') {
        warningEl.style.display = 'block';
        warningEl.className = `alert ${data.risk_level === 'EXTREME' ? 'alert-danger' : 'alert-warning'}`;
        warningTextEl.textContent = data.warning_message;
    } else {
        warningEl.style.display = 'none';
    }
    
    // ✅ FIXED: Safe number rendering
    setText('lt-velocity', `${safeNumber(analysis.velocity_mm_year, 2)} mm/năm`);
    setText('lt-classification', analysis.classification || 'N/A');
    setText('lt-total-disp', `${safeNumber(analysis.total_displacement_mm, 1)} mm`);
    setText('lt-duration', `${safeNumber(analysis.duration_days, 1)} ngày`);
    
    // Trend indicator
    const trendEl = document.getElementById('trend-indicator');
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
    trendEl.className = `trend-indicator ${analysis.trend}`;
    
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

// =====================================================
// UTILITY FUNCTIONS
// =====================================================

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

// =====================================================
// CHARTS
// =====================================================

function renderCharts(data) {
    if (!data.sensors) return;
    
    renderChart('chart-gnss', data.sensors.gnss?.history, 'total_displacement_mm', '#fa5252', 'Displacement');
    renderChart('chart-rain', data.sensors.rain?.history, 'intensity_mm_h', '#06b6d4', 'Intensity');
    renderChart('chart-water', data.sensors.water?.history, 'water_level', '#10b981', 'Level');
}

function renderChart(id, history, key, color, label) {
    const ctx = document.getElementById(id);
    if (!ctx) return;
    
    const labels = (history || []).map(h => {
        const date = new Date(h.timestamp * 1000);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });
    
    // ✅ FIXED: Safe value extraction
    const values = (history || []).map(h => {
        const val = h.data?.[key];
        return val !== null && val !== undefined ? parseFloat(val) : 0;
    });

    if (charts[id]) {
        charts[id].destroy();
    }
    
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
                    grid: { color: '#333' },
                    ticks: { color: 'var(--text-secondary)' }
                }
            }
        }
    });
}

// =====================================================
// GLOBAL EXPORTS
// =====================================================

window.mapManager = {
    loadLongTermAnalysis,
    safeNumber
};

console.log('✅ [MAP] Script fully loaded');