// Generated legacy HTML templates used by the React CDN shell.
// Keep this readable: each template is stored as a real multiline string.
window.LegacyTemplates = {
  "map": String.raw`
<!-- TOP NAVBAR -->
    <nav class="top-navbar">
        <div class="d-flex align-items-center gap-3">
            <!-- Hamburger Menu -->
            <button class="navbar-hamburger" id="navbar-hamburger-btn" title="Danh sách trạm">
                <i class="bi bi-list"></i>
            </button>

            <a href="#" class="brand-text" data-map-home>
                <i class="bi bi-activity"></i>
                <span>Landslide Monitor</span>
            </a>

            <a href="/management" id="admin-nav-btn" class="btn btn-sm btn-outline-primary"
                style="display: none;">
                <i class="bi bi-stars me-1"></i> Management
            </a>
        </div>

        <div class="d-flex align-items-center gap-3">
            <!-- Compact Layer Toggle Switch -->
            <div class="layer-toggle-switch" title="Chế độ hiển thị">
                <i class="bi bi-hdd-network-fill layer-toggle-icon" id="icon-layer-station"></i>
                <label class="toggle-switch-track">
                    <input type="checkbox" id="layer-mode-toggle">
                    <span class="toggle-switch-thumb"></span>
                </label>
                <i class="bi bi-exclamation-diamond-fill layer-toggle-icon text-rescue" id="icon-layer-rescue"></i>
            </div>

            <!-- Hidden checkboxes for JS compatibility -->
            <input type="checkbox" id="layer-station" class="d-none" checked>
            <input type="checkbox" id="layer-rescue" class="d-none" checked>

            <button id="theme-toggle-btn" class="btn btn-link p-0"
                style="color: var(--text-primary); font-size: 1.2rem;">
                <i class="bi bi-moon-stars-fill"></i>
            </button>

            <!-- Auth Button -->
            <button id="auth-btn" class="btn btn-primary btn-sm">
                <i class="bi bi-person-circle me-1"></i> Account
            </button>
        </div>
    </nav>

    <!-- ALERT BANNER -->
    <div class="alert-banner" id="alert-banner">
        <div class="alert-banner-content">
            <div class="alert-icon">
                <i class="bi bi-exclamation-triangle-fill"></i>
            </div>
            <div class="alert-details">
                <h4 class="alert-title" id="alert-title">CRITICAL ALERT!</h4>
                <div class="alert-info-line">
                    <span class="alert-station" id="alert-station">Station: Loading...</span>
                    <span class="alert-message" id="alert-message"> â€¢ Message...</span>
                </div>
            </div>
            <div class="alert-actions">
                <button class="btn-alert-follow" id="btn-alert-follow">
                    <i class="bi bi-geo-alt-fill me-1"></i> Track
                </button>
                <button class="btn-alert-dismiss" id="btn-alert-dismiss">
                    <i class="bi bi-x-lg"></i>
                </button>
            </div>
        </div>
    </div>

    <!-- LEFT SIDEBAR (Station List) -->
    <div class="station-list-sidebar" id="station-list-sidebar">
        <div class="sidebar-header">
            <h6><i class="bi bi-hdd-network me-2"></i>Station List</h6>
        </div>

        <button class="sidebar-close-tab" id="sidebar-close-tab">
            <i class="bi bi-chevron-left"></i>
        </button>

        <div class="sidebar-search">
            <input type="text" class="form-control form-control-sm" placeholder="Search station..." id="search-station">
        </div>

        <div class="station-list-content" id="station-list-container">
            <!-- Station list here -->
        </div>
    </div>

    <!-- MAP -->
    <div id="map">
    </div>

    <!-- CUSTOM GLASS ZOOM CONTROLS (Bottom-Right) -->
    <div class="custom-map-controls">
        <button class="map-ctrl-btn" id="map-zoom-in" title="Phóng to">
            <i class="bi bi-plus-lg"></i>
        </button>
        <button class="map-ctrl-btn" id="map-zoom-out" title="Thu nhỏ">
            <i class="bi bi-dash-lg"></i>
        </button>
    </div>

    <!-- HEATMAP TOGGLE -->
    <div class="heatmap-toggle-wrap">
        <button class="heatmap-toggle-btn" id="heatmap-toggle" title="Bật/Tắt Heatmap cứu hộ">
            <i class="bi bi-fire"></i>
        </button>
    </div>

    <!-- TIMELINE SLIDER -->
    <div class="timeline-slider-container" id="timeline-slider-wrap" style="display: none;">
        <span class="timeline-label" id="timeline-label">Ngày 30</span>
        <input type="range" min="1" max="30" value="30" id="timeline-slider">
        <span class="timeline-label opacity-50" style="font-size:0.65rem;">30 Ngày</span>
    </div>

    <div class="gnss-advanced-sidepanel" id="gnss-advanced-sidepanel">
        <div class="sidepanel-header">
            <h6><i class="bi bi-gear-wide-connected me-2"></i>Advanced GNSS Info</h6>
            <button class="sidepanel-close" id="gnss-sidepanel-close"><i class="bi bi-x-lg"></i></button>
        </div>
        <div class="sidepanel-body">
            <!-- Nhóm 1: Vị trí hiện tại (VN2000) -->
            <div class="adv-section">
                <div class="adv-section-title">Vị trí hiện tại (VN2000 NEH)</div>
                <div class="adv-item">
                    <span class="adv-label">VN2000 North (m)</span>
                    <div class="adv-value-row"><span class="adv-value" id="adv-val-lat">--</span><span
                            class="adv-unit">m</span></div>
                </div>
                <div class="adv-item">
                    <span class="adv-label">VN2000 East (m)</span>
                    <div class="adv-value-row"><span class="adv-value" id="adv-val-lon">--</span><span
                            class="adv-unit">m</span></div>
                </div>
                <div class="adv-item">
                    <span class="adv-label">Elevation H (m)</span>
                    <div class="adv-value-row"><span class="adv-value" id="adv-val-alt">--</span><span
                            class="adv-unit">m</span></div>
                </div>
            </div>

            <!-- Nhóm 2: Biến dạng lÅ©y kế -->
            <div class="adv-section">
                <div class="adv-section-title">Biến dạng lÅ©y kế (cm)</div>
                <div class="adv-item">
                    <span class="adv-label">Biến dạng &Delta;X (East)</span>
                    <div class="adv-value-row"><span class="adv-value highlight-dx" id="adv-val-dx">--</span><span
                            class="adv-unit">cm</span></div>
                </div>
                <div class="adv-item">
                    <span class="adv-label">Biến dạng &Delta;Y (North)</span>
                    <div class="adv-value-row"><span class="adv-value highlight-dy" id="adv-val-dy">--</span><span
                            class="adv-unit">cm</span></div>
                </div>
                <div class="adv-item">
                    <span class="adv-label">Biến dạng &Delta;H (Up)</span>
                    <div class="adv-value-row"><span class="adv-value highlight-dh" id="adv-val-dh">--</span><span
                            class="adv-unit">cm</span></div>
                </div>
            </div>

            <!-- Nhóm 3: Vận tốc biến dạng -->
            <div class="adv-section">
                <div class="adv-section-title">Vận tốc biến dạng</div>
                <div class="adv-item">
                    <span class="adv-label">Vận tốc V<sub>&Delta;X</sub></span>
                    <div class="adv-value-row"><span class="adv-value" id="adv-val-vdx">--</span><span
                            class="adv-unit">mm/phút</span></div>
                </div>
                <div class="adv-item">
                    <span class="adv-label">Vận tốc V<sub>&Delta;Y</sub></span>
                    <div class="adv-value-row"><span class="adv-value" id="adv-val-vdy">--</span><span
                            class="adv-unit">mm/phút</span></div>
                </div>
                <div class="adv-item">
                    <span class="adv-label">Vận tốc V<sub>&Delta;H</sub></span>
                    <div class="adv-value-row"><span class="adv-value" id="adv-val-vdh">--</span><span
                            class="adv-unit">mm/phút</span></div>
                </div>
            </div>

            <div class="mt-4 small text-muted text-center italic" style="font-size: 0.65rem;">
                * Hệ tọa độ VN2000.
            </div>
        </div>
    </div>

    <!-- RIGHT DETAIL SIDEBAR -->
    <div class="detail-sidebar" id="detail-sidebar">
        <button class="sidebar-close-btn" id="close-btn">
            <i class="bi bi-x-lg"></i>
        </button>
        <div class="sidebar-header" style="padding: 12px 20px;">
            <div class="d-flex align-items-center justify-content-between">
                <div class="d-flex align-items-baseline gap-2">
                    <h5 id="st-name" class="mb-0" style="font-size: 1.1rem;">Station Name</h5>
                    <small class="text-muted" id="st-code">CODE</small>
                </div>
                <div class="d-flex gap-1">
                    <button class="btn btn-sm btn-outline-secondary btn-qr-share" title="Chia sẻ QR"
                        onclick="if(currentStationData) window.showStationQR(currentStationData.location?.lat, currentStationData.location?.lon, currentStationData.name)">
                        <i class="bi bi-qr-code"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-secondary btn-export-pdf" title="Xuất PDF"
                        onclick="window.exportStationPDF()">
                        <i class="bi bi-file-earmark-pdf"></i>
                    </button>
                </div>
            </div>
        </div>

        <div class="sidebar-content">
            <!-- Status Badge -->
            <div class="status-bar">
                <span class="status-label">Status:</span>
                <span id="st-risk" class="status-badge">...</span>
            </div>
            <div id="st-stale-info" class="stale-info" style="display: none;"></div>

            <!--REALTIME VIEW -->
            <div id="realtime-view">
                <!-- COMPACT SENSOR DATA -->
                <div class="sensor-compact">
                    <!-- GNSS -->
                    <div class="sensor-item sensor-clickable" id="sensor-card-gnss" title="Xem chi tiết (Advanced)">
                        <div class="sensor-label d-flex justify-content-between align-items-center">
                            <span><i class="bi bi-geo-alt-fill me-1"></i>GNSS Velocity <i
                                    class="bi bi-info-circle ms-1 small opacity-50"></i></span>
                            <span id="gnss-fix-badge" class="gnss-fix-badge GNSS_UNKNOWN">NO DATA</span>
                            <span id="gnss-offline-badge" class="sensor-offline-badge"
                                style="display:none;">OFFLINE</span>
                        </div>
                        <div class="sensor-value-large" id="val-gnss-vel">--<span class="sensor-unit">mm/s</span></div>
                    </div>

                    <!-- Rain Intensity -->
                    <div class="sensor-item" id="sensor-card-rain">
                        <div class="sensor-label d-flex justify-content-between align-items-center">
                            <span><i class="bi bi-cloud-rain-fill me-1"></i>Rain Intensity</span>
                            <span id="rain-offline-badge" class="sensor-offline-badge"
                                style="display:none;">OFFLINE</span>
                        </div>
                        <div class="sensor-value-large" id="val-rain">--<span class="sensor-unit">mm/h</span></div>
                    </div>

                    <!-- Water Level -->
                    <div class="sensor-item sensor-full-width" id="sensor-card-water">
                        <div class="sensor-label d-flex justify-content-between align-items-center">
                            <span><i class="bi bi-water me-1"></i>Water Level</span>
                            <span id="water-offline-badge" class="sensor-offline-badge"
                                style="display:none;">OFFLINE</span>
                        </div>
                        <div class="sensor-value-large" id="val-water">--<span class="sensor-unit">m</span></div>
                    </div>

                    <!-- IMU (3 axes) -->
                    <div class="sensor-item sensor-full-width" id="sensor-card-imu">
                        <div class="sensor-label d-flex justify-content-between align-items-center">
                            <span><i class="bi bi-compass-fill me-1"></i>IMU (ROLL/PITCH/YAW)</span>
                            <span id="imu-offline-badge" class="imu-offline-badge" style="display:none;">OFFLINE</span>
                        </div>
                        <div class="imu-axes">
                            <div class="axis-value">
                                <div class="axis-label">Roll</div>
                                <div class="axis-num" id="val-imu-roll">--°</div>
                            </div>
                            <div class="axis-value">
                                <div class="axis-label">Pitch</div>
                                <div class="axis-num" id="val-imu-pitch">--°</div>
                            </div>
                            <div class="axis-value">
                                <div class="axis-label">Yaw</div>
                                <div class="axis-num" id="val-imu-yaw">--°</div>
                            </div>
                        </div>

                        <!-- Delta values â€” hiển thị hướng lệch rõ ràng -->
                        <div class="mt-2 pt-1 border-top">
                            <div class="imu-delta-header">Chuyển vị từ Baseline</div>
                            <div class="imu-delta-grid">
                                <div class="imu-delta-item">
                                    <span class="imu-delta-axis">Roll (X)</span>
                                    <span class="imu-delta-hint">â† Trái / Phải â†’</span>
                                    <span class="imu-delta-num" id="val-imu-delta-roll">-- mm</span>
                                </div>
                                <div class="imu-delta-item">
                                    <span class="imu-delta-axis">Pitch (Y)</span>
                                    <span class="imu-delta-hint">â†“ Trước / Sau â†‘</span>
                                    <span class="imu-delta-num" id="val-imu-delta-pitch">-- mm</span>
                                </div>
                                <div class="imu-delta-item">
                                    <span class="imu-delta-axis">Yaw (Z)</span>
                                    <span class="imu-delta-hint">â†º Trái / Phải â†»</span>
                                    <span class="imu-delta-num" id="val-imu-delta-yaw">-- mm</span>
                                </div>
                            </div>
                        </div>

                        <!-- Thêm khoảng cách dịch nghiêng -->
                        <div class="mt-1 pt-1 border-top" style="opacity: 0.8;">
                            <div class="d-flex justify-content-between small px-1">
                                <span style="font-size: 0.7rem;"><i class="bi bi-arrows-move me-1"></i>Độ lệch tâm
                                    (tùy chỉnh):</span>
                                <div class="d-flex gap-2"
                                    style="font-size: 0.75rem; font-weight: bold; color: var(--accent-warning, #f59e0b);">
                                    <span id="val-imu-drift-len">-- cm</span>
                                    <span id="val-imu-drift-dir">(--)</span>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="sensor-item sensor-full-width" id="battery-container"
                        style="display: none; padding: 8px 12px;">
                        <div class="d-flex align-items-center justify-content-between">
                            <div class="sensor-label mb-0"><i class="bi bi-battery-charging me-1"></i>Battery Voltage
                            </div>
                            <div class="sensor-value-large" id="val-battery" style="font-size: 1.1rem;">--<span
                                    class="sensor-unit">V</span></div>
                        </div>
                    </div>
                </div>

                <!--ACTION BUTTONS -->
                <div class="action-buttons">
                    <button class="btn-action" id="btn-show-charts">
                        <i class="bi bi-graph-up me-2"></i>View Chart
                    </button>
                    <button class="btn-action secondary d-none" id="btn-long-term">
                        <i class="bi bi-calendar-range me-2"></i>Analysis
                    </button>
                    <button class="btn-action" id="btn-digital-twin" style="background: linear-gradient(135deg, #f43f5e, #e11d48); color: white; border: none; text-decoration: none; text-align: center;">
                        <i class="bi bi-globe-americas me-2"></i>Mô phỏng 3D
                    </button>
                </div>

                <!-- SIREN CONTROL (in sidebar) -->
                <div id="siren-sidebar-section" class="siren-sidebar-control">
                    <div class="d-flex align-items-center justify-content-between">
                        <div class="d-flex align-items-center gap-2">
                            <i class="bi bi-speaker-fill"
                                style="color: var(--accent-danger, #fa5252); font-size: 0.9rem;"></i>
                            <span class="fw-bold" style="font-size: 0.8rem; color: var(--text-secondary);">Siren
                                Control</span>
                        </div>
                        <div class="d-flex gap-2">
                            <button class="btn btn-sm btn-secondary rounded-pill px-3 fw-bold btn-siren-toggle"
                                data-siren-state="idle" data-target="pi_center" disabled
                                style="transition: all 0.2s; font-size: 0.7rem; opacity: 0.5;">
                                <i class="bi bi-volume-mute-fill me-1"></i>Center
                            </button>
                            <button class="btn btn-sm btn-secondary rounded-pill px-3 fw-bold btn-siren-toggle"
                                data-siren-state="idle" data-target="pi_point" disabled
                                style="transition: all 0.2s; font-size: 0.7rem; opacity: 0.5;">
                                <i class="bi bi-volume-mute-fill me-1"></i>Point
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!--CENTER CHARTS PANEL (Tách biệt ở giữa màn hình) -->
    <div class="charts-panel" id="charts-panel">
        <div class="charts-panel-header">
            <h5><i class="bi bi-graph-up me-2"></i>Biểu đồ 24h</h5>
            <button class="btn btn-sm btn-outline-light" id="close-charts-btn">
                <i class="bi bi-chevron-right"></i>
            </button>
        </div>

        <div class="charts-panel-content">
            <!-- GNSS Chart -->
            <div class="chart-box" id="chart-box-gnss">
                <div class="chart-title">📈 GNSS Displacement (24h)</div>
                <div style="height: 250px;">
                    <canvas id="chart-gnss"></canvas>
                </div>
            </div>

            <!-- Rain Chart -->
            <div class="chart-box" id="chart-box-rain">
                <div class="chart-title">🌧ï¸ Rain Intensity (24h)</div>
                <div style="height: 250px;">
                    <canvas id="chart-rain"></canvas>
                </div>
            </div>

            <!-- Water Chart -->
            <div class="chart-box" id="chart-box-water">
                <div class="chart-title">🌊 Water Level (24h)</div>
                <div style="height: 250px;">
                    <canvas id="chart-water"></canvas>
                </div>
            </div>

            <!-- IMU Chart (3-axis) -->
            <div class="chart-box" id="chart-box-imu">
                <div class="chart-title d-flex justify-content-between align-items-center">
                    <span>🧭 IMU Roll / Pitch / Yaw (24h)</span>
                    <button class="btn btn-sm btn-outline-primary" id="btn-toggle-imu-3d"
                        style="font-size: 0.7rem; padding: 2px 6px;">
                        <i class="bi bi-box me-1"></i>3D View
                    </button>
                </div>
                <div id="chart-imu-wrapper" style="height: 250px;">
                    <canvas id="chart-imu"></canvas>
                </div>
                <div id="realtime-imu-3d-wrapper"
                    style="height: 250px; display: none; position: relative; border-radius: 8px; overflow: hidden;">
                    <div id="realtime-imu-3d-scene" style="width: 100%; height: 100%;"></div>
                </div>
            </div>

            <!-- Empty State -->
            <div class="text-center py-5" id="charts-empty-state" style="display: none;">
                <i class="bi bi-inbox fs-1 text-muted"></i>
                <p class="text-muted mt-2">Chưa có dữ liệu biểu đồ</p>
            </div>
        </div>
    </div>

    <!--LONG-TERM ANALYSIS FULLSCREEN OVERLAY -->
    <div class="longterm-overlay" id="longterm-overlay">
        <div class="longterm-container">
            <div class="longterm-header">
                <div>
                    <h4><i class="bi bi-calendar-range me-2"></i>Phân tích dài hạn</h4>
                    <small class="text-muted" id="longterm-station-name">Station Name</small>
                </div>
                <button class="btn btn-lg btn-outline-light" id="close-longterm-btn">
                    <i class="bi bi-x-lg"></i>
                </button>
            </div>

            <div class="longterm-content-wrapper">
                <!-- Time Range Selector (Always visible) -->
                <div class="d-flex justify-content-center mb-4">
                    <div class="btn-group btn-group-sm shadow-sm" id="longterm-range-selector">
                        <button class="btn btn-outline-primary fw-medium px-4" data-days="1">1 Ngày</button>
                        <button class="btn btn-outline-primary fw-medium px-4" data-days="7">1 tuần</button>
                        <button class="btn btn-outline-primary fw-medium px-4 active" data-days="30">1 tháng</button>
                        <button class="btn btn-outline-primary fw-medium px-4" data-days="365">1 năm</button>
                    </div>
                </div>

                <!-- Loading State -->
                <div id="longterm-loading" style="display: none;">
                    <div class="text-center my-5">
                        <div class="spinner-border text-primary mb-3" style="width: 3rem; height: 3rem;"></div>
                        <p class="fs-5">Đang phân tích dữ liệu...</p>
                    </div>
                </div>

                <!-- Error State -->
                <div id="longterm-error" style="display: none;">
                    <div class="alert alert-warning">
                        <i class="bi bi-exclamation-triangle me-2"></i>
                        <strong>Không đủ dữ liệu</strong>
                        <p id="error-message" class="mb-0 mt-2">Cần ít nhất 7 Ngày dữ liệu GNSS để phân
                            tích.</p>
                    </div>
                </div>

                <!-- Content State -->
                <div id="longterm-content" style="display: none;">
                    <!-- Warning Banner -->
                    <div id="longterm-warning" class="alert alert-warning" style="display: none;">
                        <i class="bi bi-exclamation-triangle me-2"></i>
                        <strong id="warning-text">Cảnh báo!</strong>
                    </div>

                    <!-- ============================================ -->
                    <!-- TOP SECTION: ALL METRICS -->
                    <!-- ============================================ -->

                    <h5 class="mb-3 text-primary border-bottom pb-2"><i class="bi bi-geo-alt me-2"></i>Thông số GNSS
                    </h5>
                    <div id="lt-reliability-note" class="reliability-note reliability-note-warning"
                        style="display: none;">
                        <i class="bi bi-shield-exclamation me-2"></i>
                        <strong>Dữ liệu chưa đủ tin cậy để kết luận vận tốc.</strong>
                        <span id="lt-reliability-text" class="ms-1"></span>
                    </div>
                    <div id="lt-gnss-source-note" class="analysis-source-note" style="display: none;"></div>
                    <!-- GNSS Metrics -->
                    <div class="row g-3 mb-4">
                        <div class="col-md-3 col-6">
                            <div class="longterm-metric-card">
                                <div class="text-muted small">Vận tốc trung bình</div>
                                <div class="fs-4 fw-bold text-primary mt-1" id="lt-velocity">-- mm/năm</div>
                                <div class="text-muted" id="lt-velocity-ci"
                                    style="font-size: 0.75rem; margin-top: 2px;">(Khoảng tin cậy: ± --)</div>
                            </div>
                        </div>
                        <div class="col-md-3 col-6">
                            <div class="longterm-metric-card">
                                <div class="text-muted small">Phân loại</div>
                                <div class="fs-5 fw-bold mt-1" id="lt-classification">--</div>
                            </div>
                        </div>
                        <div class="col-md-3 col-6">
                            <div class="longterm-metric-card">
                                <div class="text-muted small">Tổng chuyển dịch</div>
                                <div class="fs-5 fw-bold text-danger mt-1" id="lt-total-disp">-- mm</div>
                            </div>
                        </div>
                        <div class="col-md-3 col-6">
                            <div class="longterm-metric-card">
                                <div class="text-muted small">Thời gian theo dõi</div>
                                <div class="fs-5 fw-bold mt-1" id="lt-duration">-- Ngày</div>
                            </div>
                        </div>
                    </div>

                    <div class="row g-3 mb-4">
                        <!-- Trend Indicator -->
                        <div class="col-md-12">
                            <div class="card h-100 border-0 shadow-sm">
                                <div class="card-body">
                                    <div class="d-flex justify-content-between align-items-start">
                                        <h6 class="card-title text-muted mb-0">Xu hướng GNSS</h6>
                                        <span id="cusum-badge" class="badge bg-danger" style="display: none;">Biến
                                            động
                                            CUSUM</span>
                                    </div>
                                    <div id="trend-indicator" class="d-flex align-items-center gap-2 mt-2">
                                        <span id="trend-icon" class="fs-3"></span>
                                        <span id="trend-value" class="fs-5 fw-bold">Không xác định</span>
                                        <span id="cusum-message" class="text-danger small ms-2"
                                            style="display: none;"></span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <h5 class="mb-3 mt-4 text-warning border-bottom pb-2"><i class="bi bi-compass me-2"></i>Thông số
                        IMU
                    </h5>
                    <div id="imu-longterm-section">
                        <!-- IMU insufficient data message -->
                        <div id="imu-longterm-nodata" style="display: none;">
                            <div class="alert alert-warning">
                                <i class="bi bi-info-circle me-2"></i>
                                <span id="imu-nodata-msg">Không đủ dữ liệu IMU để phân tích.</span>
                            </div>
                        </div>

                        <!-- IMU metrics content -->
                        <div id="imu-longterm-content" style="display: none;">
                            <!-- IMU Warning -->
                            <div id="imu-longterm-warning" class="alert alert-warning mb-3 border-0 shadow-sm"
                                style="display: none;">
                                <i class="bi bi-exclamation-triangle-fill fs-4 me-2 align-middle"></i>
                                <strong id="imu-warning-text" class="align-middle"></strong>
                            </div>

                            <!-- IMU Metrics -->
                            <div class="row g-3 mb-4">
                                <div class="col-md-3 col-6">
                                    <div
                                        class="longterm-metric-card bg-warning bg-opacity-10 border-warning border-opacity-25">
                                        <div class="text-muted small">Tổng thay đổi góc</div>
                                        <div class="fs-4 fw-bold text-warning mt-1" id="lt-imu-tilt-change">-- °</div>
                                    </div>
                                </div>
                                <div class="col-md-3 col-6">
                                    <div class="longterm-metric-card border-0 shadow-sm">
                                        <div class="text-muted small">Tốc độ nghiêng TB</div>
                                        <div class="fs-5 fw-bold mt-1" id="lt-imu-rate">-- °/Ngày</div>
                                    </div>
                                </div>
                                <div class="col-md-3 col-6">
                                    <div class="longterm-metric-card border-0 shadow-sm">
                                        <div class="text-muted small">Roll max</div>
                                        <div class="fs-5 fw-bold text-info mt-1" id="lt-imu-max-roll">-- °</div>
                                    </div>
                                </div>
                                <div class="col-md-3 col-6">
                                    <div class="longterm-metric-card border-0 shadow-sm">
                                        <div class="text-muted small">Pitch max</div>
                                        <div class="fs-5 fw-bold text-info mt-1" id="lt-imu-max-pitch">-- °</div>
                                    </div>
                                </div>
                            </div>

                            <!-- IMU Trend -->
                            <div class="row g-3 mb-4">
                                <div class="col-md-6">
                                    <div class="card h-100 border-0 shadow-sm">
                                        <div class="card-body">
                                            <h6 class="card-title text-muted">Xu hướng nghiêng</h6>
                                            <div class="d-flex align-items-center gap-2 mt-2">
                                                <span id="imu-trend-icon" class="fs-3"></span>
                                                <span id="imu-trend-value" class="fs-5 fw-bold">Không xác
                                                    định</span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <div class="card h-100 border-0 shadow-sm">
                                        <div class="card-body">
                                            <h6 class="card-title text-muted">Thời gian & Dữ liệu IMU</h6>
                                            <div class="d-flex flex-column gap-2 mt-2">
                                                <span class="fs-6"><i class="bi bi-database me-2 text-primary"></i>Số
                                                    điểm: <strong id="lt-imu-points">--</strong></span>
                                                <span class="fs-6"><i
                                                        class="bi bi-clock-history me-2 text-info"></i>Thời gian:
                                                    <strong id="lt-imu-duration">-- Ngày</strong></span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- ============================================ -->
                    <!-- BOTTOM SECTION: GRAPHICS (3D & 2D) -->
                    <!-- ============================================ -->
                    <hr class="my-5">
                    <h5 class="mb-4 text-center text-uppercase fw-bold"><i class="bi bi-display me-2"></i>Mô phỏng &
                        Biểu đồ</h5>

                    <!-- Time Range Selector -->
                    <!-- 3D Simulations Row -->
                    <div class="row g-4 mb-4">
                        <div class="col-lg-6">
                            <div class="chart-box border-0 shadow-sm h-100 text-center">
                                <div class="chart-title text-primary"><i class="bi bi-box me-2"></i>Mô phỏng Chuyển
                                    dịch
                                    GNSS (3D)</div>
                                <div id="container-3d-gnss"
                                    style="width: 100%; height: 350px; background: #0a0e17; border-radius: 8px; overflow: hidden; position: relative;">
                                    <!-- Three.js Canvas will be inserted here -->
                                    <div id="gnss-3d-loading"
                                        class="position-absolute top-50 start-50 translate-middle text-white z-2"
                                        style="display: none;">
                                        <div class="spinner-border mb-2" role="status"></div><br><small>Đang tạo
                                            3D...</small>
                                    </div>
                                </div>
                                <div class="mt-2 text-muted small d-flex justify-content-center gap-3">
                                    <span><span style="color:#ff0000;">â– </span> X (East)</span>
                                    <span><span style="color:#00ff00;">â– </span> Z (North)</span>
                                    <span><span style="color:#0000ff;">â– </span> Y (Up)</span>
                                </div>
                            </div>
                        </div>
                        <div class="col-lg-6">
                            <div class="chart-box border-0 shadow-sm h-100 text-center">
                                <div class="chart-title text-warning"><i class="bi bi-box me-2"></i>Mô phỏng Độ
                                    nghiêng
                                    IMU (3D)</div>
                                <div id="container-3d-imu"
                                    style="width: 100%; height: 350px; background: #0a0e17; border-radius: 8px; overflow: hidden; position: relative;">
                                    <!-- Three.js Canvas will be inserted here -->
                                    <div id="imu-3d-loading"
                                        class="position-absolute top-50 start-50 translate-middle text-white z-2"
                                        style="display: none;">
                                        <div class="spinner-border mb-2" role="status"></div><br><small>Đang tạo
                                            3D...</small>
                                    </div>
                                </div>
                                <div class="mt-2 text-muted small">Sử dụng chuột trái để xoay, lăn chuột
                                    để zoom</div>
                            </div>
                        </div>
                    </div>

                    <!-- COMBINED 2D CHART -->
                    <div class="chart-box border-0 shadow-sm">
                        <div class="chart-title"><i class="bi bi-graph-up me-2"></i>Biểu đồ tổng hợp chuỗi
                            thời gian
                            GNSS & IMU</div>
                        <div style="height: 400px; padding: 10px;">
                            <canvas id="chart-longterm-combined"></canvas>
                        </div>
                    </div>

                    <!-- ============================================ -->
                    <!-- INVERSE VELOCITY (FUKUZONO) SECTION -->
                    <!-- ============================================ -->
                    <div id="inverse-velocity-section" class="mt-4" style="display: none;">
                        <h5 class="mb-3 text-danger border-bottom pb-2">
                            <i class="bi bi-exclamation-diamond me-2"></i>Phương pháp phân tích động học
                            nghịch đảo -
                            Inverse Velocity
                        </h5>
                        <div id="inv-vel-warning" class="alert alert-danger mb-3" style="display: none;">
                            <i class="bi bi-exclamation-triangle-fill me-2"></i>
                            <strong id="inv-vel-warning-text"></strong>
                        </div>
                        <div class="row g-3 mb-3">
                            <div class="col-md-3 col-6">
                                <div class="longterm-metric-card">
                                    <div class="text-muted small">Dự báo sụp lún</div>
                                    <div class="fs-5 fw-bold mt-1" id="inv-vel-prediction">--</div>
                                </div>
                            </div>
                            <div class="col-md-3 col-6">
                                <div class="longterm-metric-card">
                                    <div class="text-muted small">Thời gian còn lại</div>
                                    <div class="fs-5 fw-bold text-danger mt-1" id="inv-vel-days">--</div>
                                </div>
                            </div>
                            <div class="col-md-3 col-6">
                                <div class="longterm-metric-card">
                                    <div class="text-muted small">Độ tin cậy (R²)</div>
                                    <div class="fs-5 fw-bold mt-1" id="inv-vel-r2">--</div>
                                </div>
                            </div>
                            <div class="col-md-3 col-6">
                                <div class="longterm-metric-card">
                                    <div class="text-muted small">Đánh giá</div>
                                    <div class="fs-6 fw-bold mt-1" id="inv-vel-confidence">--</div>
                                </div>
                            </div>
                        </div>
                        <div class="chart-box border-0 shadow-sm">
                            <div class="chart-title"><i class="bi bi-graph-down me-2"></i>Biểu đồ 1/Velocity theo
                                thời
                                gian</div>
                            <div style="height: 300px; padding: 10px;">
                                <canvas id="chart-inverse-velocity"></canvas>
                            </div>
                        </div>
                    </div>

                    <!-- ============================================ -->
                    <!-- RAINFALL-DISPLACEMENT CORRELATION SECTION -->
                    <!-- ============================================ -->
                    <div id="rainfall-correlation-section" class="mt-4" style="display: none;">
                        <h5 class="mb-3 text-info border-bottom pb-2">
                            <i class="bi bi-cloud-rain me-2"></i>Tương quan Mưa - Dịch chuyển (LS-RAPID v2)
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
                                    <div class="chart-title"><i class="bi bi-moisture me-2"></i>Mưa tích lÅ©y vs
                                        Dịch
                                        chuyển tích lÅ©y</div>
                                    <div style="height: 350px; padding: 10px;">
                                        <canvas id="chart-rainfall-correlation"></canvas>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="chart-box border-0 shadow-sm">
                                    <div class="chart-title"><i class="bi bi-graph-up-arrow me-2"></i>LS-RAPID Index vs
                                        Dịch chuyển Ngày</div>
                                    <div style="height: 350px; padding: 10px;">
                                        <canvas id="chart-lsrapid-index"></canvas>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div id="rainfall-correlation-controls" class="mt-3 mb-4 text-center">
                        <button class="btn btn-info fw-semibold" id="btn-run-rain-correlation">
                            <i class="bi bi-stars me-2"></i>Chạy AI LS-RAPID
                        </button>
                        <div id="rain-correlation-hint" class="text-muted small mt-2">
                            Tương quan mưa - dịch chuyển dùng model LS-RAPID và chỉ chạy khi bạn bấm
                            nút AI.
                        </div>
                    </div>

                    <!-- ============================================ -->
                    <!-- MULTI-WINDOW ANALYSIS SECTION -->
                    <!-- ============================================ -->
                    <div id="multi-window-section" class="mt-4" style="display: none;">
                        <h5 class="mb-3 text-success border-bottom pb-2">
                            <i class="bi bi-window-stack me-2"></i>Phân tích xu hướng theo kỳ
                        </h5>
                        <div id="multi-window-alert" class="alert alert-warning mb-3" style="display: none;">
                            <i class="bi bi-lightning me-2"></i>
                            <strong id="multi-window-alert-text"></strong>
                        </div>
                        <div class="row g-3 mb-3" id="multi-window-cards"></div>
                    </div>

                    <!-- ============================================ -->
                    <!-- CROSS-SENSOR CONSENSUS SECTION -->
                    <!-- ============================================ -->
                    <div id="cross-consensus-section" class="mt-4" style="display: none;">
                        <h5 class="mb-3 border-bottom pb-2" style="color: var(--text-primary);">
                            <i class="bi bi-intersect me-2"></i>Đồng thuận đa cảm biến
                        </h5>
                        <div id="consensus-banner" class="consensus-banner mb-3">
                            <div class="d-flex align-items-center gap-3 flex-wrap">
                                <span id="consensus-badge" class="consensus-badge">--</span>
                                <span id="consensus-summary" class="fw-semibold"></span>
                            </div>
                        </div>
                        <div class="row g-3 mb-3">
                            <div class="col-md-6">
                                <div class="longterm-metric-card">
                                    <div class="text-muted small mb-2">Cảm biến có dữ liệu</div>
                                    <div id="consensus-sensors-with-data"
                                        class="d-flex flex-wrap gap-2 justify-content-center mt-1"></div>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="longterm-metric-card">
                                    <div class="text-muted small mb-2">Xu hướng GNSS vs IMU</div>
                                    <div id="consensus-trend-agreement" class="fs-5 fw-bold mt-1">--</div>
                                </div>
                            </div>
                        </div>
                        <div class="consensus-notes-list" id="consensus-notes"></div>
                    </div>

                </div>
            </div>
        </div>

        <!-- LS-RAPID RESULT POPUP (v2 â€” comprehensive dashboard) -->
        <div id="lsrapid-popup-overlay" class="lsrapid-popup-overlay" aria-hidden="true">
            <div class="lsrapid-popup-card" role="dialog" aria-modal="true" aria-labelledby="lsrapid-popup-title">
                <button class="lsrapid-popup-close" id="lsrapid-popup-close"
                    aria-label="Đóng popup kết quả LS-RAPID">
                    <i class="bi bi-x-lg"></i>
                </button>

                <div class="lsrapid-popup-head">
                    <div class="lsrapid-popup-kicker">AI LS-RAPID Engine v2</div>
                    <h5 id="lsrapid-popup-title" class="mb-1">Phân tích tương quan Mưa â€” Dịch chuyển</h5>
                    <div id="lsrapid-popup-status" class="lsrapid-popup-status">READY</div>
                </div>

                <div class="lsrapid-popup-body">
                    <!-- Tab navigation -->
                    <div class="lsrapid-tabs">
                        <button class="lsrapid-tab active" data-tab="lsrapid-tab-overview">
                            <i class="bi bi-speedometer2"></i> Tổng quan
                        </button>
                        <button class="lsrapid-tab" data-tab="lsrapid-tab-rain">
                            <i class="bi bi-cloud-rain"></i> Mưa
                        </button>
                        <button class="lsrapid-tab" data-tab="lsrapid-tab-disp">
                            <i class="bi bi-arrows-move"></i> Dịch chuyển
                        </button>
                        <button class="lsrapid-tab" data-tab="lsrapid-tab-events">
                            <i class="bi bi-calendar-event"></i> Sự kiện
                        </button>
                        <button class="lsrapid-tab" data-tab="lsrapid-tab-risk">
                            <i class="bi bi-shield-exclamation"></i> Rủi ro
                        </button>
                    </div>

                    <!-- Tab: Overview -->
                    <div id="lsrapid-tab-overview" class="lsrapid-tab-pane active">
                        <div class="lsrapid-popup-grid">
                            <div class="lsrapid-popup-metric">
                                <span class="label">Hệ số tương quan (r)</span>
                                <span class="value" id="lsrapid-popup-r">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">R² (hệ số xác định)</span>
                                <span class="value" id="lsrapid-popup-r2">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">Lag tốt nhất</span>
                                <span class="value" id="lsrapid-popup-lag">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">Mức kích hoạt</span>
                                <span class="value" id="lsrapid-popup-trigger">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">Mức tương quan</span>
                                <span class="value" id="lsrapid-popup-strength">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">Slope (mm/day / index)</span>
                                <span class="value" id="lsrapid-popup-slope">--</span>
                            </div>
                        </div>
                        <div class="lsrapid-popup-message" id="lsrapid-popup-message">--</div>
                    </div>

                    <!-- Tab: Rain statistics -->
                    <div id="lsrapid-tab-rain" class="lsrapid-tab-pane">
                        <div class="lsrapid-popup-grid lsrapid-grid-3">
                            <div class="lsrapid-popup-metric">
                                <span class="label">Tổng lượng mưa</span>
                                <span class="value" id="lsrapid-rain-total">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">Mưa max/Ngày</span>
                                <span class="value" id="lsrapid-rain-max">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">Ngày mưa max</span>
                                <span class="value" id="lsrapid-rain-max-day">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">Số Ngày mưa</span>
                                <span class="value" id="lsrapid-rain-days">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">Số Ngày khô</span>
                                <span class="value" id="lsrapid-dry-days">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">TB Ngày mưa</span>
                                <span class="value" id="lsrapid-rain-avg">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">LS-RAPID Index max</span>
                                <span class="value" id="lsrapid-idx-max">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">LS-RAPID Index TB</span>
                                <span class="value" id="lsrapid-idx-mean">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">Ngày phân tích</span>
                                <span class="value" id="lsrapid-common-days">--</span>
                            </div>
                        </div>
                    </div>

                    <!-- Tab: Displacement statistics -->
                    <div id="lsrapid-tab-disp" class="lsrapid-tab-pane">
                        <div class="lsrapid-popup-grid lsrapid-grid-3">
                            <div class="lsrapid-popup-metric">
                                <span class="label">Tổng dịch chuyển</span>
                                <span class="value" id="lsrapid-disp-total">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">Max/Ngày</span>
                                <span class="value" id="lsrapid-disp-max">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">Ngày dịch max</span>
                                <span class="value" id="lsrapid-disp-max-day">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">TB/Ngày</span>
                                <span class="value" id="lsrapid-disp-avg">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">TB Ngày mưa</span>
                                <span class="value" id="lsrapid-disp-rain">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">TB Ngày khô</span>
                                <span class="value" id="lsrapid-disp-dry">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">Hệ số gia tốc mưa</span>
                                <span class="value" id="lsrapid-accel-ratio">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">Độ nhạy</span>
                                <span class="value" id="lsrapid-sensitivity">--</span>
                            </div>
                            <div class="lsrapid-popup-metric">
                                <span class="label">Lag scan</span>
                                <span class="value" id="lsrapid-lag-scan">--</span>
                            </div>
                        </div>
                    </div>

                    <!-- Tab: Events (CWD + Peak rain) -->
                    <div id="lsrapid-tab-events" class="lsrapid-tab-pane">
                        <h6 class="lsrapid-section-title"><i class="bi bi-cloud-drizzle me-1"></i> Đợt mưa kéo dài
                            (CWD)
                        </h6>
                        <div id="lsrapid-cwd-events" class="lsrapid-events-list">
                            <div class="text-muted small">Không có đợt mưa kéo dài</div>
                        </div>
                        <h6 class="lsrapid-section-title mt-3"><i class="bi bi-cloud-lightning-rain me-1"></i> Ngày
                            mưa
                            lớn (â‰¥20mm)</h6>
                        <div id="lsrapid-peak-events" class="lsrapid-events-list">
                            <div class="text-muted small">Không có Ngày mưa lớn</div>
                        </div>
                    </div>

                    <!-- Tab: Risk insights -->
                    <div id="lsrapid-tab-risk" class="lsrapid-tab-pane">
                        <div id="lsrapid-risk-insights" class="lsrapid-insights-list">
                            <div class="text-muted small">Chưa có nhận xét rủi ro</div>
                        </div>
                    </div>
                </div>

                <div class="lsrapid-popup-actions">
                    <button class="btn btn-outline-secondary" id="lsrapid-popup-close-btn">Đóng</button>
                    <button class="btn btn-info" id="lsrapid-popup-ok-btn">OK</button>
                </div>
            </div>
        </div>
    </div>

    <!-- FLOATING RESCUE FAB -->
    <button id="btn-guest-rescue" class="rescue-fab" aria-label="Yêu cầu cứu hộ">
        <span class="rescue-fab-icon">
            <i class="bi bi-exclamation-triangle-fill"></i>
        </span>
        <span class="rescue-fab-label">Yêu cầu cứu hộ</span>
    </button>

    <div class="modal fade" id="guestRescueModal" tabindex="-1" aria-labelledby="guestRescueModalLabel"
        aria-hidden="true">
        <div class="modal-dialog modal-dialog-centered modal-dialog-scrollable">
            <div class="modal-content glass-modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="guestRescueModalLabel"><i class="bi bi-geo-alt-fill me-2"></i>Yêu cầu
                        cứu hộ</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body">
                    <!-- Khu vực 1: Thông tin cơ bản & Phân loại -->
                    <h6 class="fw-bold mt-2 mb-3 text-primary border-bottom pb-2"><i
                            class="bi bi-person-lines-fill me-2"></i>Khu vực 1: Thông tin cơ bản</h6>
                    <div class="row g-2 mb-3">
                        <div class="col-sm-6">
                            <label for="guest-rescue-name" class="form-label" style="font-size: 0.85rem;">Họ tên
                                <span class="text-danger">*</span></label>
                            <input id="guest-rescue-name" class="form-control form-control-sm" maxlength="120"
                                placeholder="Người cần hỗ trợ">
                        </div>
                        <div class="col-sm-6">
                            <label for="guest-rescue-phone" class="form-label" style="font-size: 0.85rem;">Số điện
                                thoại
                                <span class="text-danger">*</span></label>
                            <input id="guest-rescue-phone" class="form-control form-control-sm" maxlength="32"
                                placeholder="Liên hệ khẩn">
                        </div>
                    </div>

                    <div class="mb-3">
                        <label class="form-label" style="font-size: 0.85rem;">Phân loại <span
                                class="text-danger">*</span></label>
                        <div class="d-flex flex-wrap gap-2" id="guest-rescue-type-group">
                            <input type="radio" class="btn-check" name="guest-rescue-type"
                                id="guest-rescue-type-emergency" value="can_cuu_ho" checked>
                            <label class="btn btn-outline-danger btn-sm rounded-pill"
                                for="guest-rescue-type-emergency">Cần Cứu Hộ</label>

                            <input type="radio" class="btn-check" name="guest-rescue-type"
                                id="guest-rescue-type-medical" value="can_nhu_yeu_pham">
                            <label class="btn btn-outline-success btn-sm rounded-pill"
                                for="guest-rescue-type-medical">Cần Nhu Yếu Phẩm</label>

                            <input type="radio" class="btn-check" name="guest-rescue-type"
                                id="guest-rescue-type-vehicle" value="can_cuu_ho_xe">
                            <label class="btn btn-outline-warning btn-sm rounded-pill"
                                for="guest-rescue-type-vehicle">Cần Cứu Hộ Xe</label>

                            <input type="radio" class="btn-check" name="guest-rescue-type" id="guest-rescue-type-other"
                                value="khac">
                            <label class="btn btn-outline-info btn-sm rounded-pill"
                                for="guest-rescue-type-other">Khác</label>
                        </div>
                        <div id="guest-rescue-other-wrap" class="mt-2"
                            style="display: none; transition: opacity 0.3s ease; opacity: 0;">
                            <input type="text" id="guest-rescue-other-input" class="form-control form-control-sm"
                                placeholder="Nhập yêu cầu khác..." maxlength="100">
                        </div>
                    </div>

                    <div class="mb-3">
                        <label for="guest-rescue-note" class="form-label" style="font-size: 0.85rem;">Mô tả ngắn
                            <span class="text-danger">*</span></label>
                        <textarea id="guest-rescue-note" class="form-control form-control-sm" rows="2" maxlength="500"
                            placeholder="Tình trạng hiện trường, đường bao xa, có vật cản gì..."></textarea>
                    </div>

                    <!-- Khu vực 2: Xác định Vị trí -->
                    <h6 class="fw-bold mt-4 mb-3 text-primary border-bottom pb-2"><i
                            class="bi bi-geo-alt-fill me-2"></i>Khu vực 2: Xác định Vị trí</h6>
                    <div class="card bg-transparent border-primary border-opacity-25 mb-4 shadow-sm"
                        style="border-radius: 12px; overflow: hidden;">
                        <div class="card-body p-3" style="background: rgba(13, 110, 253, 0.03);">

                            <!-- Bấm chọn vị trí trên Bản đồ -->
                            <button type="button"
                                class="btn btn-primary w-100 mb-3 shadow-sm position-relative overflow-hidden"
                                style="border-radius: 8px; padding: 12px; font-weight: 700; border: none; background: linear-gradient(135deg, #0d6efd 0%, #0a58ca 100%);"
                                onclick="enablePickOnMap()">
                                <i class="bi bi-pin-map-fill fs-5 me-2" style="vertical-align: middle;"></i> BẤM
                                CHỌN VỊ
                                TRÍ TRÊN BẢN ĐỒ
                            </button>

                            <!-- Cụm công cụ: GPS & Search -->
                            <div class="row g-2 mb-3">
                                <div class="col-md-5">
                                    <button id="btn-guest-rescue-locate" type="button"
                                        class="btn btn-outline-primary btn-sm w-100 h-100 fw-semibold text-truncate">
                                        <i class="bi bi-crosshair me-1"></i> Lấy GPS tự động
                                    </button>
                                </div>
                                <div class="col-md-7 position-relative">
                                    <div class="input-group input-group-sm h-100">
                                        <input type="text" id="guest-rescue-address-search" class="form-control"
                                            placeholder="Tìm Xã, Huyện, Tỉnh...">
                                        <button class="btn btn-outline-primary" type="button"
                                            id="btn-guest-rescue-search-address-action">
                                            <i class="bi bi-search"></i>
                                        </button>
                                    </div>
                                    <div id="guest-rescue-address-results"
                                        class="list-group position-absolute w-100 mt-1"
                                        style="z-index: 1060; display: none; max-height: 180px; overflow-y: auto; box-shadow: 0 8px 24px rgba(0,0,0,0.2); border-radius: 6px;">
                                    </div>
                                </div>
                            </div>

                            <!-- Vị trí chi tiết & Tỉnh thành -->
                            <div class="row g-2 mb-3">
                                <div class="col-sm-5">
                                    <label for="guest-rescue-province" class="form-label"
                                        style="font-size: 0.75rem; font-weight: 600; opacity: 0.8;">Tỉnh/Thành
                                        phố</label>
                                    <select id="guest-rescue-province" class="form-select form-select-sm">
                                        <option value="">Chọn tỉnh/thành phố...</option>
                                        <option value="Ha Noi">Hà Nội</option>
                                        <option value="TP Ho Chi Minh">TP. Hồ Chí Minh</option>
                                        <option value="Da Nang">Đà Nẵng</option>
                                        <option value="Hai Phong">Hải Phòng</option>
                                        <option value="Can Tho">Cần Thơ</option>
                                        <option value="Nghe An">Nghệ An</option>
                                        <option value="Thanh Hoa">Thanh Hóa</option>
                                        <option value="Quang Nam">Quảng Nam</option>
                                        <option value="Quang Ngai">Quảng Ngãi</option>
                                        <option value="Khac">Khác (Miền Trung/Nam)</option>
                                    </select>
                                </div>
                                <div class="col-sm-7">
                                    <label for="guest-rescue-address-manual" class="form-label"
                                        style="font-size: 0.75rem; font-weight: 600; opacity: 0.8;">Địa chỉ chi
                                        tiết
                                        (nếu cần)</label>
                                    <input id="guest-rescue-address-manual" type="text"
                                        class="form-control form-control-sm" maxlength="255"
                                        placeholder="Hẻm, ngõ, số nhà, làng, xã...">
                                </div>
                            </div>

                            <!-- Tọa độ hiển thị Readonly -->
                            <div class="row g-2 pt-2 border-top border-primary border-opacity-10 opacity-75">
                                <div class="col-6 d-flex align-items-center gap-2">
                                    <label class="form-label mb-0 fw-bold text-danger text-opacity-75"
                                        style="font-size: 0.7rem; width: 25px;">LAT</label>
                                    <input id="guest-rescue-lat"
                                        class="form-control form-control-sm bg-transparent border-0 px-0 shadow-none text-muted"
                                        style="font-size: 0.75rem; cursor: default;" readonly placeholder="Chưa có">
                                </div>
                                <div class="col-6 d-flex align-items-center gap-2">
                                    <label class="form-label mb-0 fw-bold text-danger text-opacity-75"
                                        style="font-size: 0.7rem; width: 25px;">LNG</label>
                                    <input id="guest-rescue-lon"
                                        class="form-control form-control-sm bg-transparent border-0 px-0 shadow-none text-muted"
                                        style="font-size: 0.75rem; cursor: default;" readonly placeholder="Chưa có">
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Khu vực 3: Bằng chứng -->
                    <h6 class="fw-bold mt-4 mb-3 text-primary border-bottom pb-2"><i
                            class="bi bi-camera-fill me-2"></i>Khu vực 3: Bằng chứng</h6>
                    <div class="row g-3">
                        <div class="col-12">
                            <label for="guest-rescue-image" class="form-label"
                                style="font-size: 0.8rem; font-weight: 600;">Ảnh hiện trường <span
                                    class="text-muted fw-normal">(tùy chọn)</span></label>
                            <div class="input-group input-group-sm">
                                <input id="guest-rescue-image" type="file" class="form-control" accept="image/*">
                                <button class="btn btn-outline-danger" type="button" id="btn-guest-rescue-image-clear"
                                    style="display: none;"><i class="bi bi-trash"></i></button>
                            </div>
                            <div class="form-text mt-1" style="font-size: 0.7rem;">Ảnh giúp đội cứu hộ xác
                                định tính
                                chất. Nén tự động để tiết kiệm mạng.</div>
                            <div id="guest-rescue-image-preview-wrap" class="mt-2 text-center"
                                style="display:none; background: rgba(0,0,0,0.03); border-radius: 8px; padding: 10px;">
                                <img id="guest-rescue-image-preview" alt="Preview ảnh"
                                    style="max-width:100%; max-height:140px; object-fit:contain; border-radius:6px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                            </div>
                        </div>
                        <div class="col-12">
                            <label for="guest-rescue-source-link" class="form-label"
                                style="font-size: 0.8rem; font-weight: 600;">Link nguồn <span
                                    class="text-muted fw-normal">(tùy báo mxh, zalo...)</span></label>
                            <div class="input-group input-group-sm">
                                <span class="input-group-text bg-transparent"><i class="bi bi-link-45deg"></i></span>
                                <input id="guest-rescue-source-link" type="url" class="form-control" maxlength="500"
                                    placeholder="https://facebook.com/...">
                            </div>
                        </div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Đóng</button>
                    <button type="button" class="btn btn-danger" id="btn-guest-rescue-submit">
                        <i class="bi bi-send-fill me-1"></i>Gửi yêu cầu
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- ==================== DIGITAL TWIN OVERLAY ==================== -->
    <div id="dt-overlay-container" class="dt-overlay-container">
        <header id="dt-header">
            <div class="dt-header-left">
                <div class="dt-logo">
                    <div class="dt-logo-icon"><i class="bi bi-tsunami"></i></div>
                    <span class="dt-logo-text">LS-RAPID Digital Twin</span>
                </div>
                <div class="dt-status-badge" id="sim-status-badge">
                    <span class="dt-status-dot"></span>
                    <span class="dt-status-text">STABLE</span>
                </div>
            </div>
            <div class="dt-header-center">
                <div class="dt-fos-mini" id="fos-mini-display">
                    <span class="dt-fos-label">FoS</span>
                    <span class="dt-fos-value" id="fos-value-header">--</span>
                </div>
            </div>
            <div class="dt-header-right">
                <button class="dt-btn-icon" id="btn-toggle-panel" title="Toggle Panel">
                    <i class="bi bi-layout-sidebar"></i>
                </button>
                <button class="dt-btn-icon" id="btn-fullscreen-dt" title="Fullscreen">
                    <i class="bi bi-arrows-fullscreen"></i>
                </button>
                <button class="dt-btn-back" id="btn-close-dt" style="cursor:pointer; background:rgba(244,63,94,0.1); border-color:rgba(244,63,94,0.3); color:#f43f5e;">
                    <i class="bi bi-x-lg"></i> Đóng 3D
                </button>
            </div>
        </header>

        <div id="dt-main">
            <aside id="dt-panel" class="dt-panel-open">
                <div class="dt-panel-section">
                    <div class="dt-section-header"><i class="bi bi-layers-half"></i><span>Thông số Địa chất</span></div>
                    <div class="dt-param-group">
                        <label class="dt-param-label"><span>Lực dính c' (kPa)</span><output id="val-cohesion">15</output></label>
                        <input type="range" id="param-cohesion" min="0" max="50" value="15" step="1" class="dt-slider">
                    </div>
                    <div class="dt-param-group">
                        <label class="dt-param-label"><span>Góc ma sát Ï†' (°)</span><output id="val-friction">30</output></label>
                        <input type="range" id="param-friction" min="10" max="45" value="30" step="1" class="dt-slider">
                    </div>
                    <div class="dt-param-group">
                        <label class="dt-param-label"><span>Trọng lượng riêng Î³ (kN/m³)</span><output id="val-unit-weight">18</output></label>
                        <input type="range" id="param-unit-weight" min="14" max="24" value="18" step="0.5" class="dt-slider">
                    </div>
                    <div class="dt-param-group">
                        <label class="dt-param-label"><span>Chiều sâu mặt trượt z (m)</span><output id="val-slip-depth">5</output></label>
                        <input type="range" id="param-slip-depth" min="1" max="20" value="5" step="0.5" class="dt-slider">
                    </div>
                    <div class="dt-param-group">
                        <label class="dt-param-label"><span>Góc dốc Î² (°)</span><output id="val-slope-angle">25</output></label>
                        <input type="range" id="param-slope-angle" min="10" max="60" value="25" step="1" class="dt-slider">
                    </div>
                </div>

                <div class="dt-panel-section">
                    <div class="dt-section-header"><i class="bi bi-cloud-rain-heavy"></i><span>Điều kiện Kích hoạt</span></div>
                    <div class="dt-param-group">
                        <label class="dt-param-label"><span>Cường độ mưa (mm/h)</span><output id="val-rainfall">0</output></label>
                        <input type="range" id="param-rainfall" min="0" max="200" value="0" step="5" class="dt-slider dt-slider-rain">
                    </div>
                    <div class="dt-param-group">
                        <label class="dt-param-label"><span>Áp lực nước r<sub>u</sub></span><output id="val-pore-pressure">0.00</output></label>
                        <input type="range" id="param-pore-pressure" min="0" max="0.6" value="0" step="0.01" class="dt-slider dt-slider-pore">
                    </div>
                    <div class="dt-param-group">
                        <label class="dt-param-label"><span>Gia tốc nền k<sub>h</sub></span><output id="val-seismic">0.00</output></label>
                        <input type="range" id="param-seismic" min="0" max="0.5" value="0" step="0.01" class="dt-slider dt-slider-seismic">
                    </div>
                </div>

                <div class="dt-panel-section">
                    <div class="dt-section-header"><i class="bi bi-tree"></i><span>Môi trường</span></div>
                    <div class="dt-param-group">
                        <label class="dt-param-label"><span>Số lượng nhà</span><output id="val-houses">40</output></label>
                        <input type="range" id="param-houses" min="0" max="100" value="40" step="5" class="dt-slider">
                    </div>
                    <div class="dt-param-group">
                        <label class="dt-param-label"><span>Số lượng cây</span><output id="val-trees">300</output></label>
                        <input type="range" id="param-trees" min="0" max="1000" value="300" step="50" class="dt-slider">
                    </div>
                </div>

                <div class="dt-panel-actions">
                    <button id="btn-run-simulation" class="dt-btn-primary"><i class="bi bi-play-fill"></i> Chạy Mô phỏng</button>
                    <button id="btn-reset-simulation" class="dt-btn-secondary"><i class="bi bi-arrow-counterclockwise"></i> Đặt lại</button>
                </div>
            </aside>

            <div id="dt-viewport">
                <canvas id="dt-canvas"></canvas>

                <div id="dt-fos-gauge" class="dt-hud-element">
                    <div class="dt-gauge-ring">
                        <svg viewBox="0 0 120 120">
                            <circle cx="60" cy="60" r="52" class="dt-gauge-bg"/>
                            <circle cx="60" cy="60" r="52" class="dt-gauge-fill" id="fos-gauge-arc"/>
                        </svg>
                        <div class="dt-gauge-center">
                            <div class="dt-gauge-value" id="fos-gauge-value">--</div>
                            <div class="dt-gauge-label">FoS</div>
                        </div>
                    </div>
                    <div class="dt-gauge-status" id="fos-gauge-status">ĐANG TẢI</div>
                </div>

                <div id="dt-damage-stats" class="dt-hud-element" style="display:none;">
                    <div class="dt-damage-title"><i class="bi bi-exclamation-triangle-fill"></i> Thống kê Thiệt hại</div>
                    <div class="dt-damage-grid">
                        <div class="dt-damage-item"><i class="bi bi-house-x-fill"></i><span class="dt-damage-val" id="dmg-houses">0</span><span class="dt-damage-lbl">Nhà sập</span></div>
                        <div class="dt-damage-item"><i class="bi bi-tree-fill"></i><span class="dt-damage-val" id="dmg-trees">0</span><span class="dt-damage-lbl">Cây đổ</span></div>
                        <div class="dt-damage-item"><i class="bi bi-speedometer2"></i><span class="dt-damage-val" id="dmg-velocity">0</span><span class="dt-damage-lbl">m/s</span></div>
                        <div class="dt-damage-item"><i class="bi bi-box-fill"></i><span class="dt-damage-val" id="dmg-volume">0</span><span class="dt-damage-lbl">m³</span></div>
                    </div>
                </div>

                <div id="dt-timeline" class="dt-hud-element">
                    <button class="dt-tl-btn" id="btn-tl-play" title="Play/Pause"><i class="bi bi-play-fill"></i></button>
                    <div class="dt-tl-bar"><div class="dt-tl-progress" id="tl-progress" style="width:0%"></div></div>
                    <div class="dt-tl-time" id="tl-time">00:00</div>
                    <select class="dt-tl-speed" id="tl-speed">
                        <option value="1">1x</option><option value="2">2x</option><option value="5" selected>5x</option><option value="10">10x</option>
                    </select>
                </div>

                <div id="dt-loading">
                    <div class="dt-loading-content">
                        <div class="dt-loading-spinner"></div>
                        <div class="dt-loading-text">Đang khởi tạo Digital Twin...</div>
                    </div>
                </div>

                <div id="dt-warning-overlay" style="display:none;">
                    <div class="dt-warning-text">⚠ CẢNH BÁO SẠT LỞ ⚠</div>
                    <div class="dt-warning-sub" id="dt-warning-fos">FoS = 0.95</div>
                </div>
            </div>
        </div>
    </div>

    <!-- Scripts -->
  `,

  "admin": String.raw`
<!-- SECURITY: Block page render until auth verified -->
    



    <!-- Sidebar -->
    <div class="admin-sidebar">
        <div class="sidebar-brand" style="cursor:pointer" onclick="window.location.href='/?view=map'"
            title="Về trang bản đồ">
            <h4><i class="bi bi-map me-2"></i>Map</h4>
            <small class="text-muted">Bản đồ</small>
        </div>

        <nav>
            <div class="nav-item">
                <a class="nav-link active" href="#" data-tab="tab-users"
                    onclick="window.adminManager?.switchTab('tab-users', this)">
                    <i class="bi bi-people"></i>
                    <span>Người dùng</span>
                </a>
            </div>
            <div class="nav-item">
                <a class="nav-link" href="#" data-tab="tab-projects"
                    onclick="window.adminManager?.switchTab('tab-projects', this)">
                    <i class="bi bi-folder"></i>
                    <span>Dự án</span>
                </a>
            </div>
            <div class="nav-item">
                <a class="nav-link" href="#" data-tab="tab-database"
                    onclick="window.adminManager?.switchTab('tab-database', this)">
                    <i class="bi bi-database"></i>
                    <span>Database</span>
                </a>
            </div>
            <div class="nav-item" id="system-tab" style="display:none;">
                <a class="nav-link" href="#" data-tab="tab-system"
                    onclick="window.adminManager?.switchTab('tab-system', this)">
                    <i class="bi bi-cpu"></i>
                    <span>Hệ thống</span>
                </a>
            </div>
            <div class="nav-item">
                <a class="nav-link" href="#" data-tab="tab-pi"
                    onclick="window.adminManager?.switchTab('tab-pi', this); window.adminManager?.loadPiDevices()">
                    <i class="bi bi-cpu-fill" style="color:#0ea5e9"></i>
                    <span>Pi Devices</span>
                </a>
            </div>
            <div class="nav-item">
                <a class="nav-link" href="#" data-tab="tab-rescue"
                    onclick="window.adminManager?.switchTab('tab-rescue', this); window.adminManager?.loadRescueRequests()">
                    <i class="bi bi-life-preserver" style="color:#ef4444"></i>
                    <span>Cứu hộ</span>
                </a>
            </div>
            <div class="nav-item mt-5">
                <a class="nav-link text-danger" href="#" id="logout-btn">
                    <i class="bi bi-box-arrow-left"></i>
                    <span>Đăng xuất</span>
                </a>
            </div>
        </nav>
    </div>

    <!-- Top Navbar -->
    <nav class="admin-navbar">
        <div class="d-flex justify-content-between align-items-center w-100">
            <div class="navbar-left">
                <h5 class="mb-0 fw-bold" style="color:var(--text-primary)">
                    <i class="bi bi-gear-wide-connected me-2" style="color:var(--accent-primary)"></i>
                    Quản lý Hệ thống
                </h5>
            </div>
            <div class="navbar-right d-flex align-items-center gap-3">
                <div class="theme-toggle-mini" id="theme-toggle" onclick="window.themeManager.toggle()">
                    <i class="bi bi-moon-stars-fill"></i>
                </div>
                <div class="user-profile d-flex align-items-center gap-2">
                    <div class="avatar-circle">A</div>
                    <span class="d-none d-sm-block">Administrator</span>
                </div>
            </div>
        </div>
    </nav>

    <!-- Main Content -->
    <div class="admin-main">

        <!-- Tab Content (no horizontal tabs â€” sidebar handles switching) -->
        <div class="tab-content" id="admin-tab-content">

            <!-- TAB 1: USERS -->
            <div class="tab-pane fade show active" id="tab-users">
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <h4>Danh sách Người dùng</h4>
                    <button class="btn btn-outline-primary" data-bs-toggle="modal" data-bs-target="#addUserModal">
                        <i class="bi bi-person-plus me-2"></i>Thêm user
                    </button>
                </div>

                <div class="custom-table">
                    <table class="table table-hover mb-0">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Tài khoản</th>
                                <th>Họ tên</th>
                                <th>Vai trò</th>
                                <th>Trạng thái</th>
                                <th>Thao tác</th>
                            </tr>
                        </thead>
                        <tbody id="user-table-body">
                            <tr>
                                <td colspan="6" class="text-center py-4">
                                    <div class="spinner-border text-primary"></div>
                                    <p class="mt-2 text-muted">Đang tải...</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- TAB 2: PROJECTS -->
            <div class="tab-pane fade" id="tab-projects">
                <nav aria-label="breadcrumb" class="mb-3">
                    <ol class="breadcrumb" id="project-breadcrumb">
                        <li class="breadcrumb-item active">Dự án</li>
                    </ol>
                </nav>

                <div class="d-flex justify-content-between align-items-center mb-4">
                    <div class="d-flex gap-2 align-items-center">
                        <button class="btn btn-outline-secondary" id="btn-back-nav" style="display: none;"
                            onclick="window.adminManager.navigateBack()">
                            <i class="bi bi-arrow-left me-1"></i> Quay lại
                        </button>
                        <h4 id="current-view-title" class="mb-0">Danh sách Dự án</h4>
                    </div>
                    <div id="action-buttons-container">
                        <button class="btn btn-gradient" onclick="window.adminManager.openCreateProjectModal()">
                            <i class="bi bi-plus-circle me-2"></i>Tạo Dự án
                        </button>
                    </div>
                </div>

                <div id="projects-content-area">
                    <div class="text-center py-5">
                        <div class="spinner-border text-primary"></div>
                        <p class="text-muted mt-2">Đang tải...</p>
                    </div>
                </div>
            </div>

            <!-- TAB 3: DATABASE -->
            <div class="tab-pane fade" id="tab-database">
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <h4><i class="bi bi-database me-2"></i>Quản lý Database</h4>

                    <!-- UPDATED BUTTONS -->
                    <div class="btn-group">
                        <button class="btn btn-outline-primary" onclick="window.dbManager.loadAllData()">
                            <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                        </button>

                        <!-- EXCEL EXPORT -->
                        <button class="btn btn-outline-success" onclick="window.dbManager.exportToExcel()">
                            <i class="bi bi-file-earmark-excel me-1"></i>Export Excel
                        </button>

                        <!-- CLEAR DATABASE -->
                        <button class="btn btn-outline-danger" onclick="window.dbManager.clearDatabase()">
                            <i class="bi bi-trash3 me-1"></i>Xóa DB
                        </button>
                    </div>
                </div>

                <!-- Filter & Search -->
                <div class="card mb-3">
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-3">
                                <select class="form-select" id="db-filter-table"
                                    onchange="window.dbManager.applyFilter()">
                                    <option value="all">Tất cả bảng</option>
                                    <option value="stations">Stations</option>
                                    <option value="devices">Devices</option>
                                    <option value="sensor_data">Sensor Data</option>
                                    <option value="alerts">Alerts</option>
                                </select>
                            </div>
                            <div class="col-md-6">
                                <input type="text" class="form-control" id="db-search" placeholder="Tìm kiếm..."
                                    oninput="window.dbManager.applyFilter()">
                            </div>
                            <div class="col-md-3">
                                <select class="form-select" id="db-limit" onchange="window.dbManager.applyFilter()">
                                    <option value="50">50 dòng</option>
                                    <option value="100" selected>100 dòng</option>
                                    <option value="500">500 dòng</option>
                                    <option value="1000">1000 dòng</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Database Viewer -->
                <div class="custom-table" style="max-height: 600px; overflow-y: auto;">
                    <table class="table table-hover table-sm mb-0">
                        <thead id="db-table-head" class="sticky-top">
                            <tr>
                                <th style="width: 80px;">ID</th>
                                <th style="width: 120px;">Table</th>
                                <th>Data Preview</th>
                                <th style="width: 150px;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="db-table-body">
                            <tr>
                                <td colspan="4" class="text-center py-4">
                                    <div class="spinner-border text-primary"></div>
                                    <p class="mt-2 text-muted">Đang tải...</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>

                <!-- Stats -->
                <div class="row g-3 mt-3">
                    <div class="col-md-3">
                        <div class="card bg-primary text-white">
                            <div class="card-body">
                                <h6 class="mb-1">Stations</h6>
                                <h3 id="stat-stations" class="mb-0">--</h3>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card bg-success text-white">
                            <div class="card-body">
                                <h6 class="mb-1">Devices</h6>
                                <h3 id="stat-devices" class="mb-0">--</h3>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card bg-info text-white">
                            <div class="card-body">
                                <h6 class="mb-1">Sensor Data</h6>
                                <h3 id="stat-data" class="mb-0">--</h3>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card bg-warning text-white">
                            <div class="card-body">
                                <h6 class="mb-1">Active Alerts</h6>
                                <h3 id="stat-alerts" class="mb-0">--</h3>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- ✅ THÊM TAB 4: HỆ THỐNG -->
            <div class="tab-pane fade" id="tab-system">

                <!-- ⚠ï¸ Warning Header -->
                <div class="alert alert-danger mb-4">
                    <div class="d-flex align-items-center gap-3">
                        <i class="bi bi-shield-exclamation fs-1"></i>
                        <div>
                            <h5 class="mb-1"><strong>CẢNH BÁO:</strong> Cài đặt toàn hệ thống</h5>
                            <p class="mb-0">Thay đổi ở đây sẽ ảnh hưởng tới <strong>TẤT CẢ</strong> trạm giám sát. Hãy
                                cẩn thận!</p>
                        </div>
                    </div>
                </div>

                <form id="systemConfigForm" autocomplete="off">

                    <!-- Dummy fields to absorb aggressive browser/password-manager autofill -->
                    <input type="text" name="fake-username" autocomplete="username"
                        style="position:absolute;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0;pointer-events:none;"
                        tabindex="-1" aria-hidden="true">
                    <input type="password" name="fake-password" autocomplete="current-password"
                        style="position:absolute;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0;pointer-events:none;"
                        tabindex="-1" aria-hidden="true">

                    <!-- 1. MQTT Configuration -->
                    <div class="config-section">
                        <div class="section-header">
                            <i class="bi bi-hdd-network-fill"></i>
                            <h5>MQTT Broker Configuration</h5>
                            <span id="sys-mqtt-status-badge" class="badge bg-secondary ms-auto">UNKNOWN</span>
                        </div>

                        <div class="row g-3">
                            <div class="col-md-6">
                                <label class="form-label">
                                    <i class="bi bi-server me-1"></i> Broker Address
                                </label>
                                <input type="text" class="form-control" id="sys-mqtt-broker" placeholder="aitogy.asia">
                                <small class="text-muted">Địa chỉ MQTT Broker (IP hoặc Domain)</small>
                            </div>

                            <div class="col-md-3">
                                <label class="form-label">
                                    <i class="bi bi-plug me-1"></i> Port
                                </label>
                                <input type="number" class="form-control" id="sys-mqtt-port" value="1883">
                                <small class="text-muted">Mặc định: 1883</small>
                            </div>

                            <div class="col-md-3">
                                <label class="form-label">
                                    <i class="bi bi-arrow-clockwise me-1"></i> Reload Interval
                                </label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="sys-reload-interval" value="60">
                                    <span class="input-group-text">giây</span>
                                </div>
                                <small class="text-muted">Tần suất reload topics</small>
                            </div>

                            <div class="col-md-6">
                                <label class="form-label">
                                    <i class="bi bi-person-badge me-1"></i> Username
                                </label>
                                <input type="text" class="form-control" id="sys-mqtt-user" placeholder="mqttUser"
                                    name="sys_mqtt_user_runtime" autocomplete="new-password" readonly
                                    onfocus="unlockProtectedInput(this)" spellcheck="false" autocapitalize="off"
                                    autocorrect="off" data-lpignore="true" onblur="lockProtectedInput(this)">
                                <small class="text-muted">Tài khoản MQTT</small>
                            </div>

                            <div class="col-md-6">
                                <label class="form-label">
                                    <i class="bi bi-key-fill me-1"></i> Password
                                </label>
                                <div class="input-group">
                                    <input type="password" class="form-control" id="sys-mqtt-password"
                                        name="sys_mqtt_password_runtime" autocomplete="new-password" readonly
                                        onfocus="unlockProtectedInput(this)" placeholder="â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢" data-lpignore="true"
                                        onblur="lockProtectedInput(this)">
                                    <button class="btn btn-outline-secondary" type="button"
                                        onclick="togglePasswordVisibility('sys-mqtt-password')">
                                        <i class="bi bi-eye"></i>
                                    </button>
                                </div>
                                <small class="text-muted">Mật khẩu MQTT</small>
                            </div>
                        </div>
                    </div>

                    <!-- 2. Alert Confirmation Settings -->
                    <div class="config-section">
                        <div class="section-header">
                            <i class="bi bi-exclamation-triangle-fill"></i>
                            <h5>Cơ chế Đếm Xác Nhận Cảnh Báo</h5>
                            <span class="badge bg-warning text-dark ms-auto">CRITICAL</span>
                        </div>

                        <div class="alert alert-info mb-3">
                            <i class="bi bi-info-circle-fill me-2"></i>
                            <strong>Cơ chế đếm xác nhận:</strong> Hệ thống sẽ chỉ gửi cảnh báo khi phát hiện vượt ngưỡng
                            <strong>liên tục N lần</strong> (tránh false alarm)
                        </div>

                        <div class="row g-3">
                            <div class="col-md-3">
                                <label class="form-label">
                                    <i class="bi bi-geo-alt-fill text-danger me-1"></i> GNSS
                                </label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="sys-confirm-gnss" value="3" min="1"
                                        max="10">
                                    <span class="input-group-text">lần</span>
                                </div>
                                <small class="text-muted">Số lần xác nhận GNSS</small>
                            </div>

                            <div class="col-md-3">
                                <label class="form-label">
                                    <i class="bi bi-cloud-rain-fill text-primary me-1"></i> Rain
                                </label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="sys-confirm-rain" value="2" min="1"
                                        max="10">
                                    <span class="input-group-text">lần</span>
                                </div>
                                <small class="text-muted">Số lần xác nhận Mưa</small>
                            </div>

                            <div class="col-md-3">
                                <label class="form-label">
                                    <i class="bi bi-water text-info me-1"></i> Water
                                </label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="sys-confirm-water" value="3" min="1"
                                        max="10">
                                    <span class="input-group-text">lần</span>
                                </div>
                                <small class="text-muted">Số lần xác nhận Nước</small>
                            </div>

                            <div class="col-md-3">
                                <label class="form-label">
                                    <i class="bi bi-activity text-warning me-1"></i> IMU
                                </label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="sys-confirm-imu" value="1" min="1"
                                        max="5">
                                    <span class="input-group-text">lần</span>
                                </div>
                                <small class="text-muted">Shock thường báo ngay</small>
                            </div>
                        </div>
                    </div>

                    <!-- 3. Data Save Intervals -->
                    <div class="config-section">
                        <div class="section-header">
                            <i class="bi bi-clock-history"></i>
                            <h5>Chu Kỳ Lưu Database</h5>
                            <span class="badge bg-info ms-auto">DATABASE</span>
                        </div>

                        <div class="alert alert-info mb-3">
                            <i class="bi bi-info-circle-fill me-2"></i>
                            <strong>Chu kỳ lưu DB:</strong> Để tránh quá tải, dữ liệu chỉ lưu vào DB theo chu kỳ. Khi có
                            cảnh báo, sẽ lưu ngay lập tức.
                        </div>

                        <div class="row g-3">
                            <div class="col-md-3">
                                <label class="form-label">
                                    <i class="bi bi-geo-alt-fill text-danger me-1"></i> GNSS
                                </label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="sys-save-gnss" value="86400">
                                    <span class="input-group-text">giây</span>
                                </div>
                                <small class="text-muted">Mặc định: 86400s (1 ngày)</small>
                            </div>

                            <div class="col-md-3">
                                <label class="form-label">
                                    <i class="bi bi-cloud-rain-fill text-primary me-1"></i> Rain
                                </label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="sys-save-rain" value="3600">
                                    <span class="input-group-text">giây</span>
                                </div>
                                <small class="text-muted">Mặc định: 3600s (1 giờ)</small>
                            </div>

                            <div class="col-md-3">
                                <label class="form-label">
                                    <i class="bi bi-water text-info me-1"></i> Water
                                </label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="sys-save-water" value="3600">
                                    <span class="input-group-text">giây</span>
                                </div>
                                <small class="text-muted">Mặc định: 3600s (1 giờ)</small>
                            </div>

                            <div class="col-md-3">
                                <label class="form-label">
                                    <i class="bi bi-activity text-warning me-1"></i> IMU
                                </label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="sys-save-imu" value="2592000">
                                    <span class="input-group-text">giây</span>
                                </div>
                                <small class="text-muted">Mặc định: 2592000s (30 ngày)</small>
                            </div>
                        </div>
                    </div>


                    <!-- Save Button -->
                    <div class="text-end">
                        <button type="button" class="btn btn-lg btn-danger"
                            onclick="window.systemManager.saveSystemConfig()">
                            <i class="bi bi-save me-2"></i> Lưu cấu hình toàn hệ thống
                        </button>
                    </div>

                </form>
            </div>

            <!-- TAB: RESCUE -->
            <div class="tab-pane fade" id="tab-rescue">
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h4 class="mb-1" style="font-weight:700;">
                            <i class="bi bi-life-preserver me-2" style="color:#ef4444"></i>QUẢN LÝ CỨU HỘ
                        </h4>
                        <small class="text-muted">Danh sách yêu cầu cứu hộ khẩn cấp.</small>
                    </div>
                    <button type="button" class="btn btn-sm btn-outline-primary"
                        onclick="window.adminManager?.loadRescueRequests()">
                        <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                    </button>
                </div>
                <div class="alert alert-info py-2 small mb-3">
                    Guest có thể gửi vị trí GPS + thông tin cứu hộ từ web map. Admin xử lý tại đây.
                </div>
                <div class="row g-2 mb-3">
                    <div class="col-6 col-md-3">
                        <div class="card border-0 shadow-sm" style="background: var(--bg-tertiary);">
                            <div class="card-body py-2 px-3">
                                <div class="small text-muted">Tổng trường hợp</div>
                                <div class="fw-bold fs-5" id="rescue-count-total">0</div>
                            </div>
                        </div>
                    </div>
                    <div class="col-6 col-md-3">
                        <div class="card border-0 shadow-sm" style="background: var(--bg-tertiary);">
                            <div class="card-body py-2 px-3">
                                <div class="small text-muted">Đang chờ</div>
                                <div class="fw-bold fs-5 text-danger" id="rescue-count-pending">0</div>
                            </div>
                        </div>
                    </div>
                    <div class="col-6 col-md-3">
                        <div class="card border-0 shadow-sm" style="background: var(--bg-tertiary);">
                            <div class="card-body py-2 px-3">
                                <div class="small text-muted">Đã xong</div>
                                <div class="fw-bold fs-5 text-success" id="rescue-count-resolved">0</div>
                            </div>
                        </div>
                    </div>
                    <div class="col-6 col-md-3">
                        <div class="card border-0 shadow-sm" style="background: var(--bg-tertiary);">
                            <div class="card-body py-2 px-3">
                                <div class="small text-muted">Từ chối</div>
                                <div class="fw-bold fs-5 text-secondary" id="rescue-count-rejected">0</div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="custom-table" style="max-height: 600px; overflow-y: auto;">
                    <table class="table table-hover table-sm align-middle mb-0" id="rescue-requests-table">
                        <thead class="sticky-top">
                            <tr>
                                <th>ID</th>
                                <th>Thời gian</th>
                                <th>Người gửi</th>
                                <th>Liên hệ</th>
                                <th>Vị trí</th>
                                <th>Nội dung</th>
                                <th>Trạng thái</th>
                                <th>Thao tác</th>
                            </tr>
                        </thead>
                        <tbody id="rescue-requests-body">
                            <tr>
                                <td colspan="8" class="text-muted text-center py-4">Chưa có dữ liệu</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- TAB 5: PI DEVICES -->
            <div class="tab-pane fade" id="tab-pi">

                <!-- Header -->
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h4 class="mb-1" style="font-weight:700;letter-spacing:.5px">
                            <i class="bi bi-broadcast me-2" style="color:#0ea5e9"></i>DEVICE MANAGEMENT
                        </h4>
                        <small class="text-muted">Monitor and configure connected Pi sensor nodes.</small>
                    </div>
                    <div class="d-flex gap-2 align-items-center">
                        <div class="input-group input-group-sm" style="width:200px">
                            <span class="input-group-text"
                                style="background:var(--bg-tertiary);border-color:var(--border-color)">
                                <i class="bi bi-search" style="color:var(--text-muted)"></i>
                            </span>
                            <input type="text" class="form-control form-control-sm" placeholder="Search ID..."
                                id="pi-search-input" oninput="window.adminManager._filterPiGrid(this.value)"
                                style="min-height:34px">
                        </div>
                        <button class="btn btn-sm btn-outline-primary" onclick="window.adminManager.loadPiDevices()">
                            <i class="bi bi-arrow-clockwise me-1"></i>Sync
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" id="pi-select-toggle"
                            onclick="window.adminManager.togglePiSelectMode()">
                            <i class="bi bi-check2-square me-1"></i>Chọn
                        </button>
                    </div>
                </div>

                <!-- Summary Cards -->
                <div class="row g-3 mb-4" id="pi-summary-cards" style="align-items:stretch">
                    <div class="col-md-4 d-flex">
                        <div class="card w-100" style="border-color:#f59e0b33">
                            <div class="card-body py-3 d-flex justify-content-between align-items-center">
                                <div>
                                    <div class="text-uppercase fw-bold small" style="color:#f59e0b;letter-spacing:1px">
                                        PENDING ACTIVATION</div>
                                    <div class="d-flex align-items-baseline gap-1">
                                        <span id="pi-pending-count"
                                            style="font-size:2rem;font-weight:800;line-height:1">0</span>
                                        <span class="text-muted small">nodes</span>
                                    </div>
                                    <small id="pi-pending-desc" class="text-muted">No devices awaiting handshake</small>
                                </div>
                                <i class="bi bi-hourglass-split" style="font-size:2rem;color:#f59e0b44"></i>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4 d-flex">
                        <div class="card w-100" style="border-color:#22c55e33">
                            <div class="card-body py-3 d-flex justify-content-between align-items-center">
                                <div>
                                    <div class="text-uppercase fw-bold small" style="color:#22c55e;letter-spacing:1px">
                                        ACTIVATED · UNASSIGNED</div>
                                    <div class="d-flex align-items-baseline gap-1">
                                        <span id="pi-activated-count"
                                            style="font-size:2rem;font-weight:800;line-height:1">0</span>
                                        <span class="text-muted small">nodes</span>
                                    </div>
                                    <small class="text-muted">System optimized. No idle units.</small>
                                </div>
                                <i class="bi bi-check-circle" style="font-size:2rem;color:#22c55e44"></i>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4 d-flex">
                        <div class="card w-100" style="border-color:#0ea5e933">
                            <div class="card-body py-3 d-flex justify-content-between align-items-center">
                                <div>
                                    <div class="text-uppercase fw-bold small" style="color:#0ea5e9;letter-spacing:1px">
                                        ASSIGNED TO STATION</div>
                                    <div class="d-flex align-items-baseline gap-1">
                                        <span id="pi-assigned-count"
                                            style="font-size:2rem;font-weight:800;line-height:1">0</span>
                                        <span class="text-muted small">nodes</span>
                                    </div>
                                </div>
                                <i class="bi bi-broadcast-pin" style="font-size:2rem;color:#0ea5e944"></i>
                            </div>
                            <div
                                style="height:3px;background:linear-gradient(90deg,#0ea5e9,#06b6d4);border-radius:0 0 12px 12px">
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Active Grid / Table -->
                <div class="card">
                    <div class="card-body p-0">
                        <div class="d-flex justify-content-between align-items-center px-3 py-2"
                            style="border-bottom:1px solid var(--border-color)">
                            <span class="fw-bold small text-uppercase" style="letter-spacing:1px">
                                <i class="bi bi-grid-3x3 me-1"></i>ACTIVE GRID
                            </span>
                            <div class="d-flex gap-3 small">
                                <span><i class="bi bi-circle-fill me-1"
                                        style="color:#22c55e;font-size:.5rem"></i>Online</span>
                                <span><i class="bi bi-circle-fill me-1"
                                        style="color:#ef4444;font-size:.5rem"></i>Offline</span>
                            </div>
                        </div>
                        <div class="table-responsive">
                            <table class="table mb-0">
                                <thead>
                                    <tr>
                                        <th style="width:40px"></th>
                                        <th>DEVICE ID / NAME</th>
                                        <th>SERIAL</th>
                                        <th>STATUS</th>
                                        <th>LAST PING</th>
                                    </tr>
                                </thead>
                                <tbody id="pi-grid-body">
                                    <tr>
                                        <td colspan="5" class="text-center text-muted py-4">Loading...</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                        <div class="d-flex justify-content-between align-items-center px-3 py-2"
                            style="border-top:1px solid var(--border-color)">
                            <small id="pi-grid-info" class="text-muted">Showing 0 entries</small>
                            <nav>
                                <ul class="pagination pagination-sm mb-0" id="pi-grid-pagination"></ul>
                            </nav>
                        </div>
                    </div>
                </div>

                <!-- Hidden legacy elements for badge compatibility -->
                <span id="pi-pending-badge" style="display:none">0</span>
                <span id="pi-activated-badge" style="display:none">0</span>
                <span id="pi-assigned-badge" style="display:none">0</span>
                <div id="pi-pending-list" style="display:none"></div>
                <div id="pi-activated-list" style="display:none"></div>
                <div id="pi-assigned-list" style="display:none"></div>

            </div>

        </div>
    </div>

    <!-- ============================================
         MODALS
    ============================================ -->

    <!-- 1. Add User Modal -->
    <div class="modal fade" id="addUserModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Thêm người dùng mới</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <form id="addUserForm">
                        <div class="mb-3">
                            <label class="form-label">Tài khoản</label>
                            <input type="text" class="form-control" id="new-username" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Mật khẩu</label>
                            <input type="password" class="form-control" id="new-password" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Họ tên</label>
                            <input type="text" class="form-control" id="new-fullname">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Vai trò</label>
                            <select class="form-select" id="new-role"
                                onchange="document.getElementById('project-assign-group').style.display = (this.value === 'operator' || this.value === 'viewer') ? 'block' : 'none'">
                                <option value="viewer">Viewer</option>
                                <option value="operator">Operator</option>
                                <option value="admin">Admin</option>
                            </select>
                        </div>
                        <div class="mb-3" id="project-assign-group" style="display:none">
                            <label class="form-label">Gán dự án <small class="text-muted">(Operator/Viewer, Viewer không chọn = tất cả)</small></label>
                            <div id="project-checkbox-list" class="project-checkbox-list"
                                style="max-height:200px;overflow-y:auto;border:1px solid var(--border-color);border-radius:8px;padding:10px">
                                <small class="text-muted">Đang tải danh sách dự án...</small>
                            </div>
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="button" class="btn btn-gradient" onclick="window.adminManager.createUser()">Tạo tài
                        khoản</button>
                </div>
            </div>
        </div>
    </div>

    <!-- 2. Create Project Modal -->
    <div class="modal fade" id="createProjectModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Tạo Dự án Mới</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <form id="createProjectForm">
                        <div class="mb-3">
                            <label class="form-label">Mã dự án <span class="text-danger">*</span></label>
                            <input type="text" class="form-control" id="project-code" required>
                            <small class="text-muted">VD: DA_QUANGNINH_2024</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Tên dự án <span class="text-danger">*</span></label>
                            <input type="text" class="form-control" id="project-name" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Mô tả</label>
                            <textarea class="form-control" id="project-desc" rows="3"></textarea>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Vị trí</label>
                            <input type="text" class="form-control" id="project-location" placeholder="VD: Quảng Ninh">
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="button" class="btn btn-gradient" onclick="window.adminManager.createProject()">
                        <i class="bi bi-save me-1"></i> Tạo Dự án
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- 3. Station Config Modal - 3 STEPS WIZARD -->
    <div class="modal fade" id="stationConfigModal" tabindex="-1">
        <div class="modal-dialog modal-lg modal-dialog-scrollable">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="modal-title">Cấu hình Trạm</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <!-- WIZARD STEPS OUTSIDE SCROLLING BODY -->
                <div class="wizard-steps-container">
                    <div class="wizard-steps" id="wizard-steps" style="margin-bottom: 24px;">
                        <div class="wizard-step active" data-step="1">
                            <div class="step-circle">1</div>
                            <div class="step-label">Thông tin cơ bản</div>
                        </div>
                        <div class="wizard-step" data-step="2">
                            <div class="step-circle">2</div>
                            <div class="step-label">MQTT & Tọa độ</div>
                        </div>
                        <div class="wizard-step" data-step="3">
                            <div class="step-circle">3</div>
                            <div class="step-label">Ngưỡng cảnh báo</div>
                        </div>
                    </div>
                </div>

                <div class="modal-body">

                    <form id="stationConfigForm">
                        <input type="hidden" id="edit-station-id">
                        <input type="hidden" id="edit-project-id">

                        <!-- STEP 1: MÃ TRẠM & TÊN -->
                        <div class="wizard-content active" data-step="1">
                            <div class="row g-3">
                                <div class="col-md-6">
                                    <label class="form-label">Mã trạm <span class="text-danger">*</span></label>
                                    <input type="text" class="form-control" id="edit-code" required>
                                    <small class="text-muted">VD: ST01, ST02...</small>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Tên trạm <span class="text-danger">*</span></label>
                                    <input type="text" class="form-control" id="edit-name" required>
                                    <div class="alert alert-warning mt-3 mb-0">
                                        <div class="form-check form-switch mb-2">
                                            <input class="form-check-input" type="checkbox" id="station-alerting-disabled">
                                            <label class="form-check-label fw-semibold" for="station-alerting-disabled">
                                                Không cảnh báo
                                            </label>
                                            <small class="d-block text-muted">
                                                Bật tùy chọn này thì trạm vẫn quan trắc và lưu dữ liệu, nhưng không phát cảnh báo tự động.
                                            </small>
                                        </div>
                                        <div class="form-check form-switch">
                                            <input class="form-check-input" type="checkbox" id="station-offline-display-enabled">
                                            <label class="form-check-label fw-semibold" for="station-offline-display-enabled">
                                                Hiển thị offline giám sát
                                            </label>
                                            <small class="d-block text-muted">
                                                Khi trạm mất kết nối, marker chuyển màu vàng và vẫn hiển thị dữ liệu cuối cùng thay vì trạng thái OFFLINE đỏ/xám.
                                            </small>
                                        </div>
                                    </div>
                                    <small class="text-muted">VD: Trạm Đà Nẵng</small>
                                </div>
                            </div>
                        </div>

                        <!-- STEP 2: MQTT & TỌA ĐỘ -->
                        <div class="wizard-content" data-step="2">
                            <div class="alert alert-info small mb-3">
                                <i class="bi bi-info-circle me-1"></i>
                                Chọn thiết bị â†’ Nhập MQTT Topic â†’ Cấu hình tọa độ (nếu cần)
                            </div>

                            <h6 class="mb-3">1. Chọn thiết bị cần kích hoạt:</h6>
                            <div class="d-flex flex-wrap gap-3 mb-4 p-3 border rounded">
                                <div class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="edit-gnss">
                                    <label class="form-check-label" for="edit-gnss"><i
                                            class="bi bi-geo-alt-fill text-danger me-1"></i>
                                        GNSS</label>
                                </div>
                                <div class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="edit-rain">
                                    <label class="form-check-label" for="edit-rain"><i
                                            class="bi bi-cloud-rain-fill me-1"
                                            style="color: var(--accent-primary);"></i> Rain</label>
                                </div>
                                <div class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="edit-water">
                                    <label class="form-check-label" for="edit-water"><i class="bi bi-water me-1"
                                            style="color: var(--accent-info);"></i> Water</label>
                                </div>
                                <div class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="edit-imu">
                                    <label class="form-check-label" for="edit-imu"><i class="bi bi-compass-fill me-1"
                                            style="color: var(--accent-warning);"></i> IMU</label>
                                </div>
                            </div>

                            <h6 class="mb-3">2. Cấu hình MQTT Topics:</h6>

                            <div id="mqtt-gnss-section" class="sensor-config-section" style="display: none;">
                                <div class="sensor-config-header">
                                    <i class="bi bi-geo-alt-fill text-danger"></i>
                                    <span>GNSS Configuration</span>
                                </div>
                                <div class="sensor-config-body">
                                    <label class="form-label">MQTT Topic</label>
                                    <input type="text" class="form-control mb-3" id="topic-gnss"
                                        placeholder="station/ST01/gnss">

                                    <div class="coordinate-lock-box">
                                        <h6 class="mb-2"><i class="bi bi-crosshair me-2"></i>Khóa Tọa độ Gốc (Origin)
                                        </h6>
                                        <div class="row g-2 mb-3">
                                            <div class="col-md-4"><label class="form-label small">Lat</label><input
                                                    type="number" step="0.00000001" class="form-control form-control-sm"
                                                    id="origin-lat" readonly></div>
                                            <div class="col-md-4"><label class="form-label small">Lon</label><input
                                                    type="number" step="0.00000001" class="form-control form-control-sm"
                                                    id="origin-lon" readonly></div>
                                            <div class="col-md-4"><label class="form-label small">Height</label><input
                                                    type="number" step="0.001" class="form-control form-control-sm"
                                                    id="origin-h" readonly></div>
                                        </div>
                                        <div class="d-flex justify-content-between align-items-center">
                                            <small id="origin-status" class="text-muted">Chưa có dữ liệu gốc</small>
                                            <div class="d-flex gap-2">
                                                <button type="button" class="btn btn-sm btn-outline-warning"
                                                    id="btn-reset-origin"
                                                    onclick="window.adminManager.resetGnssOrigin(window.adminManager.currentStationId)">
                                                    <i class="bi bi-arrow-counterclockwise me-1"></i> Đặt lại điểm gốc
                                                </button>
                                                <button type="button" class="btn btn-sm btn-warning"
                                                    id="btn-fetch-origin"
                                                    onclick="window.adminManager.fetchLatestOrigin()">
                                                    <i class="bi bi-arrow-repeat me-1"></i> Lấy tọa độ
                                                </button>
                                            </div>
                                        </div>
                                    </div>

                                    <!-- ✅ GNSS EXTERNAL FORWARDING CONFIG -->
                                    <div class="mt-3 p-3 rounded border"
                                        style="background: rgba(14,165,233,0.06); border-color: rgba(14,165,233,0.25) !important;">
                                        <div class="d-flex align-items-center gap-3 mb-1">
                                            <i class="bi bi-broadcast-pin" style="color:#0ea5e9;font-size:1.1rem"></i>
                                            <h6 class="mb-0 fw-bold" style="color:var(--text-primary)">Truyền dữ liệu
                                                RTK (1Hz)</h6>

                                            <div class="ms-auto">
                                                <div class="ios-switch">
                                                    <input type="checkbox" id="cfg-fwd-enabled"
                                                        onchange="window.adminManager.toggleRtkForwardingSlide()">
                                                    <span class="ios-switch-track"></span>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="text-muted small mb-3" style="font-size: 0.75rem;">
                                            Tự động đẩy 9 tham số GNSS nâng cao lên server qua MQTT theo tần suất 1Hz.
                                        </div>

                                        <div id="rtk-forwarding-content"
                                            style="display: none; overflow: hidden; transition: all 0.3s ease-out;">
                                            <!-- MQTT Broker config cho RTK Forward -->
                                            <div class="row g-2 mb-3">
                                                <div class="col-md-6">
                                                    <label class="form-label small fw-semibold">MQTT Host
                                                        (External)</label>
                                                    <input type="text" class="form-control form-control-sm"
                                                        id="gnss-rtk-host" placeholder="mqtt.example.com">
                                                </div>
                                                <div class="col-md-2">
                                                    <label class="form-label small fw-semibold">Port</label>
                                                    <input type="number" class="form-control form-control-sm"
                                                        id="gnss-rtk-port" placeholder="1883" value="1883">
                                                </div>
                                                <div class="col-md-2">
                                                    <label class="form-label small fw-semibold">User</label>
                                                    <input type="text" class="form-control form-control-sm"
                                                        id="gnss-rtk-user" placeholder="user">
                                                </div>
                                                <div class="col-md-2">
                                                    <label class="form-label small fw-semibold">Pass</label>
                                                    <input type="password" class="form-control form-control-sm"
                                                        id="gnss-rtk-pass" placeholder="pass">
                                                </div>
                                            </div>

                                            <!-- MQTT Topic cho RTK Forward -->
                                            <div class="row g-2 mb-3 border-top pt-2">
                                                <div class="col-md-8">
                                                    <label class="form-label small fw-semibold">
                                                        <i class="bi bi-reception-4 text-success me-1"></i>Topic đẩy dữ
                                                        liệu RTK (Publish)
                                                        <span class="text-muted fw-normal">(Độ chính xác cm)</span>
                                                    </label>
                                                    <input type="text" class="form-control form-control-sm"
                                                        id="gnss-rtk-topic" placeholder="GNSS/RTK/STATION_01">
                                                </div>
                                                <div class="col-md-4">
                                                    <label class="form-label small fw-semibold">
                                                        <i class="bi bi-tag text-info me-1"></i>Mã định danh GNSS (Code)
                                                    </label>
                                                    <input type="text" class="form-control form-control-sm"
                                                        id="gnss-rtk-code" placeholder="gnss_processed">
                                                </div>
                                            </div>

                                            <!-- 9 tham số đẩy lên server -->
                                            <div class="alert alert-info py-2 px-3 mb-3"
                                                style="border:none; border-left:4px solid #3498db; background:#e8f4fd">
                                                <div class="d-flex align-items-center">
                                                    <i class="fas fa-info-circle me-2 text-primary"></i>
                                                    <div class="small">
                                                        <strong>Giao thức đẩy dữ liệu:</strong> Dữ liệu được đóng gói
                                                        theo chuẩn <strong>GNSS JSON</strong> (lồng nhau). Tắt các nút
                                                        bên dưới sẽ xóa trường tương ứng khỏi JSON <code>data</code>.
                                                    </div>
                                                </div>
                                            </div>

                                            <label class="form-label small fw-semibold mb-2">Chọn tham số trong gói tin
                                                JSON:</label>

                                            <!-- Tọa độ hiện tại -->
                                            <div class="mb-2">
                                                <small class="text-muted text-uppercase d-block mb-1"
                                                    style="font-size:0.68rem;letter-spacing:1px">📍 Tọa độ hiện tại
                                                    (Tương đối)</small>
                                                <div class="row g-2">
                                                    <div class="col-md-4">
                                                        <label class="ios-toggle-wrap is-on" id="wrap-fwd-x"
                                                            onclick="window.adminManager.toggleForwardingWrap(event,this,'fwd-toggle-x')">
                                                            <div class="ios-toggle-info">
                                                                <div class="param-name">X <span
                                                                        style="font-weight:400;font-family:inherit;font-size:0.78rem;color:var(--text-muted)">(m)</span>
                                                                </div>
                                                                <div class="param-unit">JSON: <code>adv_x</code></div>
                                                            </div>
                                                            <div class="ios-switch">
                                                                <input type="checkbox" id="fwd-toggle-x" checked>
                                                                <span class="ios-switch-track"></span>
                                                            </div>
                                                        </label>
                                                    </div>
                                                    <div class="col-md-4">
                                                        <label class="ios-toggle-wrap is-on" id="wrap-fwd-y"
                                                            onclick="window.adminManager.toggleForwardingWrap(event,this,'fwd-toggle-y')">
                                                            <div class="ios-toggle-info">
                                                                <div class="param-name">Y <span
                                                                        style="font-weight:400;font-family:inherit;font-size:0.78rem;color:var(--text-muted)">(m)</span>
                                                                </div>
                                                                <div class="param-unit">JSON: <code>adv_y</code></div>
                                                            </div>
                                                            <div class="ios-switch">
                                                                <input type="checkbox" id="fwd-toggle-y" checked>
                                                                <span class="ios-switch-track"></span>
                                                            </div>
                                                        </label>
                                                    </div>
                                                    <div class="col-md-4">
                                                        <label class="ios-toggle-wrap is-on" id="wrap-fwd-h"
                                                            onclick="window.adminManager.toggleForwardingWrap(event,this,'fwd-toggle-h')">
                                                            <div class="ios-toggle-info">
                                                                <div class="param-name">H <span
                                                                        style="font-weight:400;font-family:inherit;font-size:0.78rem;color:var(--text-muted)">(m)</span>
                                                                </div>
                                                                <div class="param-unit">JSON: <code>adv_h</code></div>
                                                            </div>
                                                            <div class="ios-switch">
                                                                <input type="checkbox" id="fwd-toggle-h" checked>
                                                                <span class="ios-switch-track"></span>
                                                            </div>
                                                        </label>
                                                    </div>
                                                </div>
                                            </div>

                                            <!-- Chuyển vị -->
                                            <div class="mb-2">
                                                <small class="text-muted text-uppercase d-block mb-1"
                                                    style="font-size:0.68rem;letter-spacing:1px">📐 Chuyển vị
                                                    (mm)</small>
                                                <div class="row g-2">
                                                    <div class="col-md-4">
                                                        <label class="ios-toggle-wrap is-on" id="wrap-fwd-dx"
                                                            onclick="window.adminManager.toggleForwardingWrap(event,this,'fwd-toggle-dx')">
                                                            <div class="ios-toggle-info">
                                                                <div class="param-name">dX <span
                                                                        style="font-weight:400;font-family:inherit;font-size:0.78rem;color:var(--text-muted)">(mm)</span>
                                                                </div>
                                                                <div class="param-unit">JSON: <code>adv_dx</code></div>
                                                            </div>
                                                            <div class="ios-switch">
                                                                <input type="checkbox" id="fwd-toggle-dx" checked>
                                                                <span class="ios-switch-track"></span>
                                                            </div>
                                                        </label>
                                                    </div>
                                                    <div class="col-md-4">
                                                        <label class="ios-toggle-wrap is-on" id="wrap-fwd-dy"
                                                            onclick="window.adminManager.toggleForwardingWrap(event,this,'fwd-toggle-dy')">
                                                            <div class="ios-toggle-info">
                                                                <div class="param-name">dY <span
                                                                        style="font-weight:400;font-family:inherit;font-size:0.78rem;color:var(--text-muted)">(mm)</span>
                                                                </div>
                                                                <div class="param-unit">JSON: <code>adv_dy</code></div>
                                                            </div>
                                                            <div class="ios-switch">
                                                                <input type="checkbox" id="fwd-toggle-dy" checked>
                                                                <span class="ios-switch-track"></span>
                                                            </div>
                                                        </label>
                                                    </div>
                                                    <div class="col-md-4">
                                                        <label class="ios-toggle-wrap is-on" id="wrap-fwd-dh"
                                                            onclick="window.adminManager.toggleForwardingWrap(event,this,'fwd-toggle-dh')">
                                                            <div class="ios-toggle-info">
                                                                <div class="param-name">dH <span
                                                                        style="font-weight:400;font-family:inherit;font-size:0.78rem;color:var(--text-muted)">(mm)</span>
                                                                </div>
                                                                <div class="param-unit">JSON: <code>adv_dh</code></div>
                                                            </div>
                                                            <div class="ios-switch">
                                                                <input type="checkbox" id="fwd-toggle-dh" checked>
                                                                <span class="ios-switch-track"></span>
                                                            </div>
                                                        </label>
                                                    </div>
                                                </div>
                                            </div>

                                            <!-- Vận tốc -->
                                            <div class="mb-1">
                                                <small class="text-muted text-uppercase d-block mb-1"
                                                    style="font-size:0.68rem;letter-spacing:1px">⚡ Vận tốc chuyển vị
                                                    (mm/phút)</small>
                                                <div class="row g-2">
                                                    <div class="col-md-4">
                                                        <label class="ios-toggle-wrap is-on" id="wrap-fwd-vdx"
                                                            onclick="window.adminManager.toggleForwardingWrap(event,this,'fwd-toggle-vdx')">
                                                            <div class="ios-toggle-info">
                                                                <div class="param-name">VdX <span
                                                                        style="font-weight:400;font-family:inherit;font-size:0.78rem;color:var(--text-muted)">(mm/p)</span>
                                                                </div>
                                                                <div class="param-unit">JSON: <code>adv_vdx</code></div>
                                                            </div>
                                                            <div class="ios-switch">
                                                                <input type="checkbox" id="fwd-toggle-vdx" checked>
                                                                <span class="ios-switch-track"></span>
                                                            </div>
                                                        </label>
                                                    </div>
                                                    <div class="col-md-4">
                                                        <label class="ios-toggle-wrap is-on" id="wrap-fwd-vdy"
                                                            onclick="window.adminManager.toggleForwardingWrap(event,this,'fwd-toggle-vdy')">
                                                            <div class="ios-toggle-info">
                                                                <div class="param-name">VdY <span
                                                                        style="font-weight:400;font-family:inherit;font-size:0.78rem;color:var(--text-muted)">(mm/p)</span>
                                                                </div>
                                                                <div class="param-unit">JSON: <code>adv_vdy</code></div>
                                                            </div>
                                                            <div class="ios-switch">
                                                                <input type="checkbox" id="fwd-toggle-vdy" checked>
                                                                <span class="ios-switch-track"></span>
                                                            </div>
                                                        </label>
                                                    </div>
                                                    <div class="col-md-4">
                                                        <label class="ios-toggle-wrap is-on" id="wrap-fwd-vdh"
                                                            onclick="window.adminManager.toggleForwardingWrap(event,this,'fwd-toggle-vdh')">
                                                            <div class="ios-toggle-info">
                                                                <div class="param-name">VdH <span
                                                                        style="font-weight:400;font-family:inherit;font-size:0.78rem;color:var(--text-muted)">(mm/p)</span>
                                                                </div>
                                                                <div class="param-unit">JSON: <code>adv_vdh</code></div>
                                                            </div>
                                                            <div class="ios-switch">
                                                                <input type="checkbox" id="fwd-toggle-vdh" checked>
                                                                <span class="ios-switch-track"></span>
                                                            </div>
                                                        </label>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>

                                    <!-- ✅ VN2000 TRANSFORMATION PARAMETERS (Advanced) -->
                                    <div class="mt-3 p-3 rounded border"
                                        style="background: rgba(16, 185, 129, 0.06); border-color: rgba(16, 185, 129, 0.25) !important;">
                                        <div class="d-flex align-items-center gap-3 mb-1">
                                            <i class="bi bi-gear-wide-connected"
                                                style="color:#10b981;font-size:1.1rem"></i>
                                            <h6 class="mb-0 fw-bold" style="color:var(--text-primary)">Tham số VN2000
                                                (Tùy chỉnh)</h6>

                                            <div class="ms-auto">
                                                <div class="ios-switch">
                                                    <input type="checkbox" id="vn2000-enabled"
                                                        onchange="window.adminManager.toggleVn2000AdvancedSlide()">
                                                    <span class="ios-switch-track"></span>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="text-muted small mb-3" style="font-size: 0.75rem;">
                                            Sử dụng bộ tham số 7 tham số Helmert và các số hiệu chỉnh cục bộ (Dành cho
                                            chuyên gia).
                                        </div>

                                        <div id="vn2000-advanced-content"
                                            style="display: none; overflow: hidden; transition: all 0.3s ease-out;">
                                            <!-- Helmert 7-Params -->
                                            <h6 class="small fw-bold mb-2">1. Tham số dịch chuyển (Helmert 7-params)
                                            </h6>
                                            <div class="row g-2 mb-3">
                                                <div class="col-md-4"><label class="form-label small">dX
                                                        (m)</label><input type="number" step="0.00000001"
                                                        class="form-control form-control-sm" id="vn-dx"
                                                        value="191.90441429"></div>
                                                <div class="col-md-4"><label class="form-label small">dY
                                                        (m)</label><input type="number" step="0.00000001"
                                                        class="form-control form-control-sm" id="vn-dy"
                                                        value="39.30318279"></div>
                                                <div class="col-md-4"><label class="form-label small">dZ
                                                        (m)</label><input type="number" step="0.00000001"
                                                        class="form-control form-control-sm" id="vn-dz"
                                                        value="111.45032835"></div>
                                                <div class="col-md-4"><label class="form-label small">rX
                                                        (")</label><input type="number" step="0.00000001"
                                                        class="form-control form-control-sm" id="vn-rx"
                                                        value="-0.00928836"></div>
                                                <div class="col-md-4"><label class="form-label small">rY
                                                        (")</label><input type="number" step="0.00000001"
                                                        class="form-control form-control-sm" id="vn-ry"
                                                        value="0.01975479"></div>
                                                <div class="col-md-4"><label class="form-label small">rZ
                                                        (")</label><input type="number" step="0.00000001"
                                                        class="form-control form-control-sm" id="vn-rz"
                                                        value="-0.00427372"></div>
                                                <div class="col-md-12"><label class="form-label small">Scale
                                                        (k)</label><input type="number" step="1e-15"
                                                        class="form-control form-control-sm" id="vn-k"
                                                        value="1.000000252906278"></div>
                                            </div>

                                            <!-- Projection -->
                                            <h6 class="small fw-bold mb-2 border-top pt-2">2. Kinh tuyến trục & Tỷ lệ
                                                chiếu</h6>
                                            <div class="row g-2 mb-3">
                                                <div class="col-md-6"><label class="form-label small">L0
                                                        (deg/min)</label><input type="text" inputmode="decimal"
                                                        class="form-control form-control-sm" id="vn-l0" value="105.0">
                                                </div>
                                                <div class="col-md-6"><label class="form-label small">k0</label><input
                                                        type="number" step="0.0001" class="form-control form-control-sm"
                                                        id="vn-k0" value="0.9999"></div>
                                            </div>

                                            <!-- Residuals -->
                                            <h6 class="small fw-bold mb-2 border-top pt-2">3. Số hiệu chỉnh (Residuals)
                                            </h6>
                                            <div class="row g-2">
                                                <div class="col-md-4"><label class="form-label small">resB
                                                        (rad)</label><input type="number" step="1e-12"
                                                        class="form-control form-control-sm" id="vn-resb" value="0">
                                                </div>
                                                <div class="col-md-4"><label class="form-label small">resL
                                                        (rad)</label><input type="number" step="1e-12"
                                                        class="form-control form-control-sm" id="vn-resl" value="0">
                                                </div>
                                                <div class="col-md-4"><label class="form-label small">resH
                                                        (m)</label><input type="number" step="0.001"
                                                        class="form-control form-control-sm" id="vn-resh" value="0">
                                                </div>
                                                <div class="col-md-4"><label class="form-label small">resN
                                                        (m)</label><input type="number" step="0.001"
                                                        class="form-control form-control-sm" id="vn-resn" value="0">
                                                </div>
                                                <div class="col-md-4"><label class="form-label small">resE
                                                        (m)</label><input type="number" step="0.001"
                                                        class="form-control form-control-sm" id="vn-rese" value="0">
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>

                        <div id="mqtt-rain-section" class="sensor-config-section" style="display: none;">
                            <div class="sensor-config-header"><i
                                    class="bi bi-cloud-rain-fill text-primary"></i><span>Rain Configuration</span>
                            </div>
                            <div class="sensor-config-body">
                                <label class="form-label">MQTT Topic</label><input type="text" class="form-control mb-3"
                                    id="topic-rain">
                                <div class="coordinate-lock-box">
                                    <h6 class="mb-2"><i class="bi bi-geo-alt me-2"></i>Tọa độ Lắp đặt</h6>
                                    <div class="row g-2">
                                        <div class="col-md-4"><label class="form-label small">Lat</label><input
                                                type="number" step="0.00000001" class="form-control form-control-sm"
                                                id="origin-rain-lat"></div>
                                        <div class="col-md-4"><label class="form-label small">Lon</label><input
                                                type="number" step="0.00000001" class="form-control form-control-sm"
                                                id="origin-rain-lon"></div>
                                        <div class="col-md-4"><label class="form-label small">Height</label><input
                                                type="number" step="0.001" class="form-control form-control-sm"
                                                id="origin-rain-h"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div id="mqtt-water-section" class="sensor-config-section" style="display: none;">
                            <div class="sensor-config-header"><i class="bi bi-water text-info"></i><span>Water
                                    Configuration</span></div>
                            <div class="sensor-config-body">
                                <label class="form-label">MQTT Topic</label><input type="text" class="form-control mb-3"
                                    id="topic-water">
                                <div class="coordinate-lock-box">
                                    <h6 class="mb-2"><i class="bi bi-geo-alt me-2"></i>Tọa độ Lắp đặt</h6>
                                    <div class="row g-2">
                                        <div class="col-md-4"><label class="form-label small">Lat</label><input
                                                type="number" step="0.00000001" class="form-control form-control-sm"
                                                id="origin-water-lat"></div>
                                        <div class="col-md-4"><label class="form-label small">Lon</label><input
                                                type="number" step="0.00000001" class="form-control form-control-sm"
                                                id="origin-water-lon"></div>
                                        <div class="col-md-4"><label class="form-label small">Height</label><input
                                                type="number" step="0.001" class="form-control form-control-sm"
                                                id="origin-water-h"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div id="mqtt-imu-section" class="sensor-config-section" style="display: none;">
                            <div class="sensor-config-header"><i class="bi bi-compass-fill text-warning"></i><span>IMU
                                    Configuration</span></div>
                            <div class="sensor-config-body">
                                <label class="form-label">MQTT Topic</label><input type="text" class="form-control mb-3"
                                    id="topic-imu">
                                <div class="coordinate-lock-box">
                                    <h6 class="mb-2"><i class="bi bi-geo-alt me-2"></i>Tọa độ Lắp đặt</h6>
                                    <div class="row g-2">
                                        <div class="col-md-4"><label class="form-label small">Lat</label><input
                                                type="number" step="0.00000001" class="form-control form-control-sm"
                                                id="origin-imu-lat"></div>
                                        <div class="col-md-4"><label class="form-label small">Lon</label><input
                                                type="number" step="0.00000001" class="form-control form-control-sm"
                                                id="origin-imu-lon"></div>
                                        <div class="col-md-4"><label class="form-label small">Height</label><input
                                                type="number" step="0.001" class="form-control form-control-sm"
                                                id="origin-imu-h"></div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div id="mqtt-empty-state" class="text-center py-5 text-muted">
                            <i class="bi bi-inbox fs-1"></i>
                            <p class="mt-2">Chưa có thiết bị nào được chọn</p>
                        </div>
                </div>
                <!-- STEP 3: NGƯỠNG CẢNH BÁO -->
                <div class="wizard-content" data-step="3">

                    <!-- ✅ QUICK PRESETS CHO TRẠM -->
                    <div class="mb-4 p-3 border rounded" style="background: rgba(14, 165, 233, 0.05);">
                        <h6 class="mb-2">
                            <i class="bi bi-lightning-charge-fill text-primary me-2"></i>
                            Quick Presets (Áp dụng cho trạm này)
                        </h6>
                        <small class="text-muted d-block mb-3">
                            Chọn preset để tự động điền các tham số bên dưới phù hợp với mức độ nguy hiểm của
                            khu vực.
                        </small>

                        <div class="row g-2">
                            <div class="col-md-4">
                                <button type="button" id="btn-preset-conservative"
                                    class="btn btn-sm btn-outline-primary w-100 preset-btn"
                                    onclick="window.adminManager.applyStationPreset('conservative')">
                                    <i class="bi bi-shield-check me-1"></i>
                                    <strong>Conservative</strong>
                                    <small class="d-block text-muted">Ít báo sai</small>
                                </button>
                            </div>
                            <div class="col-md-4">
                                <button type="button" id="btn-preset-balanced"
                                    class="btn btn-sm btn-outline-warning w-100 preset-btn"
                                    onclick="window.adminManager.applyStationPreset('balanced')">
                                    <i class="bi bi-sliders me-1"></i>
                                    <strong>Balanced</strong>
                                    <small class="d-block text-muted">Cân bằng</small>
                                </button>
                            </div>
                            <div class="col-md-4">
                                <button type="button" id="btn-preset-sensitive"
                                    class="btn btn-sm btn-outline-danger w-100 preset-btn"
                                    onclick="window.adminManager.applyStationPreset('sensitive')">
                                    <i class="bi bi-exclamation-diamond me-1"></i>
                                    <strong>Sensitive</strong>
                                    <small class="d-block text-muted">Báo sớm</small>
                                </button>
                            </div>
                        </div>

                        <div class="mt-2">
                            <small class="text-muted">
                                <strong>Conservative:</strong> GNSS 5 lần, Rain 3, Water 5, IMU 2<br>
                                <strong>Balanced:</strong> GNSS 3 lần, Rain 2, Water 3, IMU 1 (Mặc định)<br>
                                <strong>Sensitive:</strong> Tất cả 1 lần (Cảnh báo nhanh)
                            </small>
                        </div>
                        <div class="alert alert-warning py-2 small mt-2 mb-0">
                            <i class="bi bi-diagram-3 me-1"></i>
                            <strong>Ưu tiên Confirm Steps:</strong> Giá trị nhập tại đây (trạm) &gt; Giá trị trong tab
                            Hệ thống (toàn cục).
                            Nếu trạm đã lưu riêng, thay đổi ở Hệ thống sẽ <strong>không</strong> ảnh hưởng trạm này.
                        </div>
                    </div>

                    <!--1. OFFLINE TIMEOUTS -->
                    <div class="config-section mb-4">
                        <div class="section-header">
                            <i class="bi bi-clock-history"></i>
                            <h5>Offline Timeout (giây)</h5>
                        </div>
                        <p class="text-muted small mb-3">
                            <i class="bi bi-info-circle me-1"></i>
                            Thời gian tối đa không nhận dữ liệu trước khi sensor được coi là offline
                        </p>

                        <div class="row g-3">
                            <!-- GNSS Timeout -->
                            <div class="col-md-6">
                                <label class="form-label">
                                    <i class="bi bi-geo-alt-fill text-danger me-2"></i>
                                    GNSS Timeout
                                </label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="offline-gnss" value="30" min="15"
                                        max="3600" step="15">
                                    <span class="input-group-text">giây</span>
                                    <button class="btn btn-outline-secondary" type="button"
                                        onclick="document.getElementById('offline-gnss').value = 30; document.getElementById('offline-gnss').dispatchEvent(new Event('input'));"
                                        title="Reset về 30 giây">
                                        <i class="bi bi-arrow-clockwise"></i>
                                    </button>
                                </div>
                                <small class="text-muted d-block mt-1">
                                    Hiện tại: <span id="offline-gnss-display" class="fw-bold">30 giây</span>
                                </small>
                            </div>

                            <!-- Rain Timeout -->
                            <div class="col-md-6">
                                <label class="form-label">
                                    <i class="bi bi-cloud-rain-fill text-primary me-2"></i>
                                    Rain Timeout
                                </label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="offline-rain" value="60" min="30"
                                        max="3600" step="30">
                                    <span class="input-group-text">giây</span>
                                    <button class="btn btn-outline-secondary" type="button"
                                        onclick="document.getElementById('offline-rain').value = 60; document.getElementById('offline-rain').dispatchEvent(new Event('input'));"
                                        title="Reset về 1 phút">
                                        <i class="bi bi-arrow-clockwise"></i>
                                    </button>
                                </div>
                                <small class="text-muted d-block mt-1">
                                    Hiện tại: <span id="offline-rain-display" class="fw-bold">1 phút</span>
                                </small>
                            </div>

                            <!-- Water Timeout -->
                            <div class="col-md-6">
                                <label class="form-label">
                                    <i class="bi bi-water text-info me-2"></i>
                                    Water Timeout
                                </label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="offline-water" value="60" min="30"
                                        max="3600" step="30">
                                    <span class="input-group-text">giây</span>
                                    <button class="btn btn-outline-secondary" type="button"
                                        onclick="document.getElementById('offline-water').value = 60; document.getElementById('offline-water').dispatchEvent(new Event('input'));"
                                        title="Reset về 1 phút">
                                        <i class="bi bi-arrow-clockwise"></i>
                                    </button>
                                </div>
                                <small class="text-muted d-block mt-1">
                                    Hiện tại: <span id="offline-water-display" class="fw-bold">1 phút</span>
                                </small>
                            </div>

                            <!-- IMU Timeout -->
                            <div class="col-md-6">
                                <label class="form-label">
                                    <i class="bi bi-compass-fill text-warning me-2"></i>
                                    IMU Timeout
                                </label>
                                <div class="input-group">
                                    <input type="number" class="form-control" id="offline-imu" value="2400" min="60"
                                        max="7200" step="60">
                                    <span class="input-group-text">giây</span>
                                    <button class="btn btn-outline-secondary" type="button"
                                        onclick="document.getElementById('offline-imu').value = 2400; document.getElementById('offline-imu').dispatchEvent(new Event('input'));"
                                        title="Reset về 40 phút">
                                        <i class="bi bi-arrow-clockwise"></i>
                                    </button>
                                </div>
                                <small class="text-muted d-block mt-1">
                                    Hiện tại: <span id="offline-imu-display" class="fw-bold">40 phút</span>
                                </small>
                            </div>
                        </div>
                    </div>

                    <!--2. WATER LEVEL THRESHOLDS -->
                    <div class="config-section mb-4">
                        <div class="section-header">
                            <i class="bi bi-water"></i>
                            <h5>Water Level Thresholds</h5>
                        </div>
                        <div class="row g-3">
                            <div class="col-md-4">
                                <label class="form-label">Warning (m)</label>
                                <input type="number" step="0.01" class="form-control" id="cfg-water-warning"
                                    value="0.15">
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Critical (m)</label>
                                <input type="number" step="0.01" class="form-control" id="cfg-water-critical"
                                    value="0.30">
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Warning Confirm Steps</label>
                                <input type="number" class="form-control" id="cfg-water-warning-confirm" value="3"
                                    min="1" max="10">
                                <small id="cfg-water-confirm-source" class="text-muted">Mặc định</small>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Critical Confirm Steps</label>
                                <input type="number" class="form-control" id="cfg-water-critical-confirm" value="2"
                                    min="1" max="10">
                            </div>
                        </div>
                        <div class="row g-3 mt-1">
                            <div class="col-md-4">
                                <label class="form-label">Safe Confirm Steps <small class="text-muted">(an
                                        toàn)</small></label>
                                <input type="number" class="form-control" id="cfg-water-safe-confirm" value="3" min="1"
                                    max="20">
                                <small id="cfg-water-safe-confirm-source" class="text-muted">Mặc định</small>
                            </div>
                        </div>
                    </div>

                    <!-- ✅ 3. RAIN THRESHOLDS -->
                    <div class="config-section mb-4">
                        <div class="section-header">
                            <i class="bi bi-cloud-rain-fill"></i>
                            <h5>Rain Intensity (mm/h)</h5>
                        </div>
                        <div class="row g-3">
                            <div class="col-md-3">
                                <label class="form-label">Watch</label>
                                <input type="number" class="form-control" id="cfg-rain-watch" value="10.0">
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Warning</label>
                                <input type="number" class="form-control" id="cfg-rain-warning" value="25.0">
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Critical</label>
                                <input type="number" class="form-control" id="cfg-rain-critical" value="50.0">
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Warning Confirm Steps</label>
                                <input type="number" class="form-control" id="cfg-rain-warning-confirm" value="2"
                                    min="1" max="10">
                                <small id="cfg-rain-confirm-source" class="text-muted">Mặc định</small>
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Critical Confirm Steps</label>
                                <input type="number" class="form-control" id="cfg-rain-critical-confirm" value="1"
                                    min="1" max="10">
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Safe Confirm Steps <small class="text-muted">(an
                                        toàn)</small></label>
                                <input type="number" class="form-control" id="cfg-rain-safe-confirm" value="3" min="1"
                                    max="20">
                                <small id="cfg-rain-safe-confirm-source" class="text-muted">Mặc định</small>
                            </div>
                        </div>
                    </div>

                    <!-- ✅ 4. GNSS QUALITY -->
                    <div class="config-section mb-4">
                        <div class="section-header">
                            <i class="bi bi-geo-alt-fill"></i>
                            <h5>GNSS Quality & Velocity</h5>
                            <button type="button" class="btn btn-sm btn-outline-danger ms-auto"
                                onclick="window.adminManager.openVelocityModal()">
                                <i class="bi bi-speedometer2 me-1"></i>Bảng vận tốc
                            </button>
                        </div>
                        <div class="row g-3">
                            <div class="col-md-6">
                                <label class="form-label">Max HDOP</label>
                                <input type="number" step="0.1" class="form-control" id="cfg-gnss-hdop" value="4.0">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Warning Confirm Steps</label>
                                <input type="number" class="form-control" id="cfg-gnss-warning-steps" value="3" min="1"
                                    max="10">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Critical Confirm Steps</label>
                                <input type="number" class="form-control" id="cfg-gnss-critical-steps" value="2" min="1"
                                    max="10">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Safe Confirm Steps <small class="text-muted">(an
                                        toàn)</small></label>
                                <input type="number" class="form-control" id="cfg-gnss-safe-steps" value="5" min="1"
                                    max="20">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Degraded Timeout (s)</label>
                                <input type="number" class="form-control" id="cfg-gnss-timeout" value="300">
                            </div>
                        </div>
                    </div>

                    <!-- ✅ 5. IMU CONFIGURATION -->
                    <div class="config-section mb-4">
                        <div class="section-header">
                            <i class="bi bi-activity"></i>
                            <h5>IMU Alert Thresholds</h5>
                        </div>
                        <div class="row g-3">
                            <div class="col-md-3">
                                <label class="form-label">Critical Tilt (°)</label>
                                <input type="number" step="0.1" class="form-control" id="cfg-imu-tilt-crit"
                                    value="15.0">
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Shock Limit (m/s²)</label>
                                <input type="number" step="0.1" class="form-control" id="cfg-imu-shock" value="5.0">
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Critical Confirm Steps</label>
                                <input type="number" class="form-control" id="cfg-imu-critical-confirm" value="1"
                                    min="1" max="10">
                            </div>
                            <div class="col-md-3">
                                <label class="form-label">Safe Confirm Steps <small class="text-muted">(an
                                        toàn)</small></label>
                                <input type="number" class="form-control" id="cfg-imu-safe-confirm" value="3" min="1"
                                    max="20">
                            </div>
                        </div>
                        <div class="alert alert-secondary py-2 mt-3 mb-0 small">
                            <strong>Backend formula (đơn vị độ):</strong>
                            <code>delta_tilt_deg = sqrt(roll^2 + pitch^2)</code>;
                            cảnh báo khi <code>delta_tilt_deg &gt;= tilt_critical_deg</code>.
                            Lưu ý: <code>roll/pitch</code> là delta so với baseline (không phải raw roll/pitch).
                        </div>
                    </div>

                    <!-- ✅ 6. IMU BASELINE CONFIGURATION -->
                    <div class="config-section mb-4">
                        <div class="section-header">
                            <i class="bi bi-compass"></i>
                            <h5>IMU Baseline (Origin Angles)</h5>
                        </div>
                        <div class="alert alert-info py-2 small mb-3">
                            <i class="bi bi-info-circle me-1"></i> Tự động khóa từ bản tin đầu tiên. Bạn cÅ©ng có
                            thể sửa tay.
                        </div>
                        <div class="row g-3">
                            <div class="col-md-4">
                                <label class="form-label">Baseline Roll (°)</label>
                                <input type="number" step="0.1" class="form-control" id="cfg-imu-base-roll" value="0.0">
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Baseline Pitch (°)</label>
                                <input type="number" step="0.1" class="form-control" id="cfg-imu-base-pitch"
                                    value="0.0">
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Baseline Yaw (°)</label>
                                <input type="number" step="0.1" class="form-control" id="cfg-imu-base-yaw" value="0.0">
                            </div>
                        </div>
                    </div>

                    <!-- PENDING DEVICES (Pi) - shown when editing existing station -->
                    <div id="pending-devices-section" class="config-section mb-4" style="display: none;">
                        <div class="section-header">
                            <i class="bi bi-cpu-fill" style="color:#0ea5e9"></i>
                            <h5>Gán thiết bị Pi vào trạm này</h5>
                            <span class="badge ms-auto" style="background:#0ea5e9">Pi Trung tâm</span>
                        </div>
                        <div class="sensor-config-body">
                            <p class="text-muted small mb-3">
                                <i class="bi bi-info-circle me-1"></i>
                                Chọn một Pi Trung tâm đã kích hoạt (chưa gán trạm) để gắn vào trạm này.
                                Pi Trung tâm sẽ nhận cảnh báo âm thanh khi trạm phát hiện nguy hiểm.
                            </p>

                            <!-- Currently assigned Pi (if any) -->
                            <div id="current-pi-info" class="alert alert-success py-2 mb-3" style="display:none">
                                <i class="bi bi-broadcast-pin me-2"></i>
                                Pi đang gán: <strong id="current-pi-name">--</strong>
                                <button type="button" class="btn btn-sm btn-outline-danger ms-3"
                                    onclick="window.adminManager.unassignPiFromStation()">
                                    <i class="bi bi-x-circle me-1"></i>Bỏ gán
                                </button>
                            </div>

                            <div id="pending-devices-list">
                                <div class="text-center py-3">
                                    <div class="spinner-border spinner-border-sm text-primary"></div>
                                    <small class="ms-2 text-muted">Đang tải danh sách Pi...</small>
                                </div>
                            </div>

                            <div id="pi-assign-btn-row" class="mt-3" style="display:none">
                                <button type="button" class="btn btn-gradient"
                                    onclick="window.adminManager.assignSelectedPiToStation()">
                                    <i class="bi bi-link-45deg me-2"></i>Gán Pi vào trạm này
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                </form>
            </div>
            <div class="modal-footer justify-content-end">
                <div class="d-flex gap-2">
                    <button type="button" class="btn btn-secondary" id="btn-wizard-back" style="display: none;"
                        onclick="if (window.adminManager) { window.adminManager.wizardPrev(); } return false;">
                        <i class="bi bi-arrow-left me-1"></i> Quay lại
                    </button>
                    <button type="button" class="btn btn-primary" id="btn-wizard-next"
                        onclick="if (window.adminManager) { window.adminManager.wizardNext(); } return false;">
                        Tiếp theo <i class="bi bi-arrow-right ms-1"></i>
                    </button>
                    <button type="button" class="btn btn-success" id="btn-wizard-save" style="display: none;"
                        onclick="if (window.adminManager) { window.adminManager.saveStation(); } return false;">
                        <i class="bi bi-save me-1"></i> Lưu cấu hình
                    </button>
                </div>
            </div>
        </div>
    </div>
    </div>

    <!-- 4. Modal Velocity Config -->
    <div class="modal fade" id="velocityConfigModal" tabindex="-1" data-bs-backdrop="static">
        <div class="modal-dialog modal-lg">
            <div class="modal-content">
                <div class="modal-header bg-danger text-white">
                    <h5 class="modal-title"><i class="bi bi-speedometer2 me-2"></i>Phân cấp Vận tốc (Cruden & Varnes)
                    </h5>
                    <button type="button" class="btn-close btn-close-white"
                        onclick="window.adminManager.closeVelocityModal()"></button>
                </div>
                <div class="modal-body p-0">
                    <div class="alert alert-light m-3 border">
                        <small class="text-muted"><i class="bi bi-info-circle-fill me-1"></i> Bảng phân cấp vận tốc
                            trượt. Bạn có thể sửa ngưỡng (threshold) và nhấn "Áp dụng".</small>
                    </div>
                    <div class="table-responsive">
                        <table class="table table-striped table-hover mb-0 align-middle">
                            <thead class="table-light">
                                <tr>
                                    <th style="width: 25%">Cấp độ (Name)</th>
                                    <th style="width: 25%">Ngưỡng</th>
                                    <th>Mô tả / Ghi chú</th>
                                </tr>
                            </thead>
                            <tbody id="velocity-table-body"></tbody>
                        </table>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary"
                        onclick="window.adminManager.closeVelocityModal()">Đóng</button>
                    <button type="button" class="btn btn-primary" onclick="window.adminManager.applyVelocityConfig()">
                        <i class="bi bi-check-lg me-1"></i> Áp dụng
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- 5. Edit Database Record Modal -->
    <div class="modal fade" id="editRecordModal" tabindex="-1">
        <div class="modal-dialog modal-lg">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Chỉnh sửa Record</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <div class="mb-3">
                        <label class="form-label">Table</label>
                        <input type="text" class="form-control" id="edit-table" readonly>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Record ID</label>
                        <input type="text" class="form-control" id="edit-id" readonly>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">JSON Data</label>
                        <textarea class="form-control" id="edit-json" rows="15"
                            style="font-family: 'Courier New', monospace; font-size: 0.9rem;"></textarea>
                        <small class="text-muted">Chỉnh sửa JSON, sau đó bấm Save</small>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="button" class="btn btn-primary" onclick="window.dbManager.saveRecord()">
                        <i class="bi bi-save me-1"></i>Lưu
                    </button>
                </div>
            </div>
        </div>
    </div>

    <div id="password-shield" class="password-shield" style="display: none;">
        <div class="password-dialog">
            <h4><i class="bi bi-shield-lock-fill me-2"></i>SYSTEM ACCESS</h4>
            <p class="subtitle">
                Nhập System Password để truy cập<br>
                cài đặt toàn hệ thống
            </p>

            <div class="mb-3">
                <input type="password" class="form-control" id="system-password-input" placeholder="â€¢â€¢â€¢â€¢" maxlength="20"
                    autofocus>
            </div>

            <!-- Hint box -->
            <div id="password-hint" class="password-hint" style="display: none;"></div>

            <div class="d-flex gap-2 mt-3">
                <button class="btn btn-secondary flex-1" onclick="window.systemManager.cancelPasswordCheck()">
                    <i class="bi bi-x-circle me-1"></i> Hủy
                </button>
                <button class="btn btn-danger flex-1" onclick="window.systemManager.verifyPassword()">
                    <i class="bi bi-shield-lock-fill me-1"></i> Xác nhận
                </button>
            </div>

            <!-- Error message -->
            <p class="text-center mt-3 mb-0 small" id="password-error"
                style="display: none; color: var(--accent-danger);">
                <i class="bi bi-exclamation-triangle-fill me-1"></i>
                <span id="error-message">Sai mật khẩu!</span>
            </p>
        </div>
    </div>

    <!-- Scripts -->
    
    
    
    
    
    
    

    

    

    <!-- MODAL CHỌN BẢNG EXPORT EXCEL -->
    <div class="modal fade" id="exportExcelModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content">
                <div class="modal-header bg-success text-white">
                    <h5 class="modal-title">
                        <i class="bi bi-file-earmark-excel me-2"></i>
                        Export Excel
                    </h5>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                </div>

                <div class="modal-body">
                    <p class="text-muted mb-3">
                        <i class="bi bi-info-circle me-1"></i>
                        Chọn bảng dữ liệu muốn export ra file Excel:
                    </p>

                    <!-- CHECKLIST CÁC BẢNG -->
                    <div class="export-options">

                        <!-- Projects -->
                        <div class="form-check export-item">
                            <input class="form-check-input" type="checkbox" id="export-projects" checked>
                            <label class="form-check-label" for="export-projects">
                                <i class="bi bi-folder-fill text-primary me-2"></i>
                                <strong>Projects</strong>
                                <small class="text-muted d-block ms-4">Danh sách dự án</small>
                            </label>
                        </div>

                        <!-- Stations -->
                        <div class="form-check export-item">
                            <input class="form-check-input" type="checkbox" id="export-stations" checked>
                            <label class="form-check-label" for="export-stations">
                                <i class="bi bi-broadcast-pin text-success me-2"></i>
                                <strong>Stations</strong>
                                <small class="text-muted d-block ms-4">Thông tin trạm giám sát</small>
                            </label>
                        </div>

                        <!-- Devices -->
                        <div class="form-check export-item">
                            <input class="form-check-input" type="checkbox" id="export-devices" checked>
                            <label class="form-check-label" for="export-devices">
                                <i class="bi bi-cpu text-info me-2"></i>
                                <strong>Devices</strong>
                                <small class="text-muted d-block ms-4">Thiết bị cảm biến (GNSS, Rain, Water,
                                    IMU)</small>
                            </label>
                        </div>

                        <!-- Sensor Data -->
                        <div class="form-check export-item">
                            <input class="form-check-input" type="checkbox" id="export-sensor-data" checked>
                            <label class="form-check-label" for="export-sensor-data">
                                <i class="bi bi-graph-up text-warning me-2"></i>
                                <strong>Sensor Data</strong>
                                <small class="text-muted d-block ms-4">Dữ liệu cảm biến (giới hạn 10,000 records gần
                                    nhất)</small>
                            </label>
                        </div>

                        <!-- Alerts -->
                        <div class="form-check export-item">
                            <input class="form-check-input" type="checkbox" id="export-alerts" checked>
                            <label class="form-check-label" for="export-alerts">
                                <i class="bi bi-exclamation-triangle text-danger me-2"></i>
                                <strong>Alerts</strong>
                                <small class="text-muted d-block ms-4">Cảnh báo hệ thống (giới hạn 5,000 records gần
                                    nhất)</small>
                            </label>
                        </div>

                    </div>

                    <!-- QUICK SELECT -->
                    <div class="mt-3 pt-3 border-top">
                        <small class="text-muted">Chọn nhanh:</small>
                        <div class="btn-group btn-group-sm mt-2 w-100">
                            <button class="btn btn-outline-primary" onclick="window.dbManager.selectAllExport()">
                                <i class="bi bi-check-all me-1"></i>Tất cả
                            </button>
                            <button class="btn btn-outline-secondary" onclick="window.dbManager.deselectAllExport()">
                                <i class="bi bi-x me-1"></i>Bỏ chọn
                            </button>
                            <button class="btn btn-outline-info" onclick="window.dbManager.selectOnlyData()">
                                <i class="bi bi-database me-1"></i>Chỉ dữ liệu
                            </button>
                        </div>
                    </div>

                    <!-- WARNING -->
                    <div class="alert alert-info mt-3 mb-0">
                        <small>
                            <i class="bi bi-lightning-charge me-1"></i>
                            <strong>Lưu ý:</strong> File Excel lớn có thể mất vài giây để tạo
                        </small>
                    </div>
                </div>

                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                        <i class="bi bi-x-circle me-1"></i> Hủy
                    </button>
                    <button type="button" class="btn btn-success" onclick="window.dbManager.confirmExportExcel()">
                        <i class="bi bi-download me-1"></i> Tải xuống Excel
                    </button>
                </div>
            </div>
        </div>
    </div>

    <style>
        /* Export Modal Styles */
        .export-options {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .export-item {
            padding: 12px;
            border: 2px solid var(--border-color);
            border-radius: 8px;
            transition: all 0.3s;
            cursor: pointer;
        }

        .export-item:hover {
            background: rgba(14, 165, 233, 0.05);
            border-color: var(--accent-primary);
        }

        .export-item .form-check-input:checked~.form-check-label {
            color: var(--accent-primary);
        }

        .export-item .form-check-input {
            width: 20px;
            height: 20px;
            margin-top: 2px;
            cursor: pointer;
        }

        .export-item .form-check-label {
            cursor: pointer;
            width: 100%;
            margin-left: 8px;
        }

        .export-item small {
            font-size: 0.8rem;
            line-height: 1.3;
        }

        #exportExcelModal .modal-header {
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
        }
    </style>


    <!-- ============================================
     MODAL XÓA DATABASE (BẢO MẬT CAO)
============================================ -->
    <div class="modal fade" id="clearDatabaseModal" tabindex="-1" data-bs-backdrop="static">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content border-danger">
                <!-- Header màu đỏ cảnh báo -->
                <div class="modal-header bg-danger text-white">
                    <h5 class="modal-title">
                        <i class="bi bi-exclamation-triangle-fill me-2"></i>VÙNG NGUY HIỂM
                    </h5>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                </div>

                <div class="modal-body">
                    <div class="alert alert-warning border-warning">
                        <i class="bi bi-radioactive me-2"></i>
                        <strong>Cảnh báo:</strong> Hành động này không thể hoàn tác!
                    </div>

                    <p class="mb-2">Để xác nhận, vui lòng nhập chính xác lệnh tương ứng:</p>

                    <div class="bg-light p-3 rounded border mb-3">
                        <div class="d-flex align-items-center mb-2">
                            <code class="fs-6 fw-bold text-dark me-2">XOA DATA</code>
                            <span class="text-muted small">â†’ Xóa dữ liệu cảm biến (Sensor Data & Alerts). Giữ lại cấu
                                hình Trạm/Thiết bị.</span>
                        </div>
                        <div class="d-flex align-items-center">
                            <code class="fs-6 fw-bold text-danger me-2">FACTORY RESET</code>
                            <span class="text-muted small">â†’ Xóa TRẮNG toàn bộ hệ thống (Project, Station, Device,
                                Data...). Về trạng thái mới cài.</span>
                        </div>
                    </div>

                    <div class="form-group">
                        <label class="form-label small text-muted">Nhập lệnh xác nhận:</label>
                        <input type="text" class="form-control form-control-lg border-danger text-danger fw-bold"
                            id="clear-db-confirm-input" placeholder="Ví dụ: XOA DATA" autocomplete="off"
                            style="letter-spacing: 1px;">
                    </div>

                    <!-- Thông báo lỗi khi nhập sai -->
                    <div id="clear-db-error" class="text-danger small fw-bold mt-2"
                        style="display: none; animation: fadeIn 0.3s;">
                        <i class="bi bi-x-circle-fill me-1"></i> <span id="clear-db-error-message">Sai cú pháp!</span>
                    </div>
                </div>

                <div class="modal-footer bg-light">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                        <i class="bi bi-x-lg me-1"></i> Hủy bỏ
                    </button>
                    <!-- Nút này gọi hàm confirmClearDatabase trong JS -->
                    <button type="button" class="btn btn-danger" onclick="window.dbManager.confirmClearDatabase()">
                        <i class="bi bi-trash3-fill me-1"></i> XÁC NHẬN XÓA
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- 5. Assign Pi Point Modal -->
    <div class="modal fade" id="assignPiPointModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header" style="border-bottom-color:var(--border-color)">
                    <h5 class="modal-title">
                        <i class="bi bi-link-45deg me-2" style="color:#10b981"></i>
                        <span>Gắn Pi Hiện Trường</span>
                    </h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <form id="assignPiPointForm">
                        <input type="hidden" id="assign-center-id">
                        <input type="hidden" id="point-device-select">
                        <div class="mb-3">
                            <label class="form-label fw-bold">Chọn Pi Hiện trường cần gắn <span
                                    class="text-danger">*</span></label>
                            <div id="point-device-options" class="device-pick-list">
                                <div class="text-muted small">-- Đang tải danh sách Pi hiện trường... --</div>
                            </div>
                            <small class="text-muted">Chỉ hiển thị các Pi Hiện trường đã được kích hoạt (Activated) và
                                chưa gán.</small>
                        </div>
                    </form>
                </div>
                <div class="modal-footer bg-light">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="button" class="btn btn-success" onclick="window.adminManager.confirmAssignPiPoint()">
                        <i class="bi bi-link me-1"></i> Gắn Thiết Bị
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- MOBILE BOTTOM NAVIGATION (Mobile only, <768px) -->
    <nav class="mobile-bottom-nav" id="mobile-bottom-nav">
        <div class="nav-item active" data-view="dashboard">
            <a href="#" class="nav-link">
                <i class="bi bi-speedometer2"></i>
                <span>Dashboard</span>
            </a>
        </div>
        <div class="nav-item" data-view="stations">
            <a href="#" class="nav-link">
                <i class="bi bi-hdd-network"></i>
                <span>Stations</span>
            </a>
        </div>
        <div class="nav-item" data-view="sensors">
            <a href="#" class="nav-link">
                <i class="bi bi-sliders"></i>
                <span>Sensors</span>
            </a>
        </div>
        <div class="nav-item" data-view="settings">
            <a href="#" class="nav-link">
                <i class="bi bi-gear"></i>
                <span>Settings</span>
            </a>
        </div>
        <div class="nav-item" data-view="account">
            <a href="#" class="nav-link">
                <i class="bi bi-person-circle"></i>
                <span>Account</span>
            </a>
        </div>
    </nav>
  `
};


