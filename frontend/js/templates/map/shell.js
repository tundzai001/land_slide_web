window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['shell'] = String.raw`
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
            <h6><i class="bi bi-gear-wide-connected me-2"></i>Advanced GNSS & Network Adjustment</h6>
            <button class="sidepanel-close" id="gnss-sidepanel-close"><i class="bi bi-x-lg"></i></button>
        </div>
        <div class="sidepanel-body">
            <div class="adv-column-left">
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

                <!-- Nhóm 2: Biến dạng lũy kế -->
                <div class="adv-section">
                    <div class="adv-section-title">Biến dạng lũy kế (cm)</div>
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

                <!-- Nhóm 3: Vận tốc THÔ (Raw - trước lọc) -->
                <div class="adv-section">
                    <div class="adv-section-title text-secondary"><i class="bi bi-speedometer me-1"></i>Vận tốc thô (Raw)</div>
                    <div class="row g-2">
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">East</span>
                                <div class="adv-value-row"><span class="adv-value text-secondary" id="adv-val-raw-ve">--</span></div>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">North</span>
                                <div class="adv-value-row"><span class="adv-value text-secondary" id="adv-val-raw-vn">--</span></div>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">Up</span>
                                <div class="adv-value-row"><span class="adv-value text-secondary" id="adv-val-raw-vu">--</span></div>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">Speed 2D</span>
                                <div class="adv-value-row"><span class="adv-value text-secondary fw-bold" id="adv-val-raw-2d">--</span></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Nhóm 4: Vận tốc SAU LỌC (Theil-Sen) -->
                <div class="adv-section">
                    <div class="adv-section-title text-info"><i class="bi bi-funnel-fill me-1"></i>Vận tốc sau lọc (Theil-Sen)</div>
                    <div class="row g-2">
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">East</span>
                                <div class="adv-value-row"><span class="adv-value text-info" id="adv-val-filt-ve">--</span></div>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">North</span>
                                <div class="adv-value-row"><span class="adv-value text-info" id="adv-val-filt-vn">--</span></div>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">Up</span>
                                <div class="adv-value-row"><span class="adv-value text-info" id="adv-val-filt-vu">--</span></div>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">Speed 2D</span>
                                <div class="adv-value-row"><span class="adv-value text-info fw-bold" id="adv-val-filt-2d">--</span></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Nhóm 5: Vận tốc biến dạng VN2000 -->
                <div class="adv-section">
                    <div class="adv-section-title">Vận tốc biến dạng (VN2000)</div>
                    <div class="row g-2">
                        <div class="col-4">
                            <div class="adv-item">
                                <span class="adv-label">&Delta;X (E)</span>
                                <div class="adv-value-row"><span class="adv-value" id="adv-val-vdx">--</span></div>
                            </div>
                        </div>
                        <div class="col-4">
                            <div class="adv-item">
                                <span class="adv-label">&Delta;Y (N)</span>
                                <div class="adv-value-row"><span class="adv-value" id="adv-val-vdy">--</span></div>
                            </div>
                        </div>
                        <div class="col-4">
                            <div class="adv-item">
                                <span class="adv-label">&Delta;H (U)</span>
                                <div class="adv-value-row"><span class="adv-value" id="adv-val-vdh">--</span></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Nhóm 6: Dịch chuyển (Displacement) -->
                <div class="adv-section">
                    <div class="adv-section-title text-teal-400"><i class="bi bi-arrows-move me-1"></i>Dịch chuyển (Displacement)</div>
                    <div class="adv-item">
                        <span class="adv-label">Tổng dịch chuyển</span>
                        <div class="adv-value-row"><span class="adv-value text-warning fw-bold" id="adv-val-disp-total">--</span><span class="adv-unit">mm</span></div>
                    </div>
                    <div class="adv-item">
                        <span class="adv-label">Dịch chuyển đỉnh (Peak)</span>
                        <div class="adv-value-row"><span class="adv-value" id="adv-val-disp-peak">--</span><span class="adv-unit">mm</span></div>
                    </div>
                    <div class="row g-2 mt-1">
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">Noise Floor</span>
                                <div class="adv-value-row"><span class="adv-value text-muted" id="adv-val-disp-noise">--</span><span class="adv-unit">mm</span></div>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">Uncertainty</span>
                                <div class="adv-value-row"><span class="adv-value text-muted" id="adv-val-disp-uncert">--</span><span class="adv-unit">mm</span></div>
                            </div>
                        </div>
                    </div>
                    <div class="adv-item mt-1">
                        <span class="adv-label">Cửa sổ / Thời lượng</span>
                        <div class="adv-value-row"><span class="adv-value" id="adv-val-disp-window">--</span><span class="adv-unit"> mẫu</span> · <span class="adv-value" id="adv-val-disp-dur">--</span><span class="adv-unit">s</span></div>
                    </div>
                </div>

                <!-- Nhóm 9: Timestamps -->
                <div class="adv-section">
                    <div class="adv-section-title"><i class="bi bi-clock-history me-1"></i>Dấu thời gian (Timestamps)</div>
                    <div class="adv-item">
                        <span class="adv-label">GGA UTC</span>
                        <div class="adv-value-row"><span class="adv-value font-monospace" id="adv-val-ts-gga">--</span></div>
                    </div>
                    <div class="adv-item">
                        <span class="adv-label">Nhận GNSS (Server)</span>
                        <div class="adv-value-row"><span class="adv-value font-monospace" id="adv-val-ts-recv">--</span></div>
                    </div>
                    <div class="adv-item">
                        <span class="adv-label">Lọc Theil-Sen xong</span>
                        <div class="adv-value-row"><span class="adv-value font-monospace" id="adv-val-ts-calc">--</span></div>
                    </div>
                </div>


                <!-- Nhóm 7: Đánh giá chuyên sâu (Theil-Sen Quality) -->
                <div class="adv-section mt-3">
                    <div class="adv-section-title text-warning"><i class="bi bi-graph-up-arrow me-2"></i>Chất lượng Theil-Sen</div>
                    <div class="adv-item">
                        <span class="adv-label">Thuật toán:</span>
                        <div class="adv-value-row"><span class="adv-value" style="font-size: 0.75rem;" id="adv-val-method">Theil-Sen</span></div>
                    </div>
                    <div class="adv-item">
                        <span class="adv-label">Cửa sổ phân tích:</span>
                        <div class="adv-value-row">
                            <span class="adv-value" style="font-size: 0.75rem;"><span id="adv-val-samples">--</span> mẫu (<span id="adv-val-duration">--</span>s)</span>
                        </div>
                    </div>
                    <div class="adv-item mt-2">
                        <span class="adv-label">Sai số dư RMS:</span>
                        <div class="adv-value-row">
                            <span class="adv-value text-info" id="adv-val-rms">--</span><span class="adv-unit">mm</span>
                        </div>
                    </div>
                    <div class="adv-item">
                        <span class="adv-label">Sai số dư MAD:</span>
                        <div class="adv-value-row">
                            <span class="adv-value text-info" id="adv-val-mad">--</span><span class="adv-unit">mm</span>
                        </div>
                    </div>
                    <div class="adv-item">
                        <span class="adv-label">Uncertainty:</span>
                        <div class="adv-value-row">
                            <span class="adv-value text-danger fw-bold" id="adv-val-uncert">&plusmn; --</span><span class="adv-unit">mm/s</span>
                        </div>
                    </div>
                    <div class="adv-item">
                        <span class="adv-label">CI 95%:</span>
                        <div class="adv-value-row">
                            <span class="adv-value text-danger" id="adv-val-ci95">&plusmn; --</span><span class="adv-unit">mm/s</span>
                        </div>
                    </div>
                </div>

                <!-- Nhóm 8: Chất lượng tín hiệu GNSS -->
                <div class="adv-section">
                    <div class="adv-section-title"><i class="bi bi-broadcast me-1"></i>Tín hiệu GNSS</div>
                    <div class="adv-item">
                        <span class="adv-label">Số vệ tinh (Sats)</span>
                        <div class="adv-value-row"><span class="adv-value" id="adv-val-sats">--</span></div>
                    </div>
                    <div class="adv-item">
                        <span class="adv-label">HDOP</span>
                        <div class="adv-value-row"><span class="adv-value" id="adv-val-hdop">--</span></div>
                    </div>
                </div>

                <div class="mt-2 small text-muted text-center italic" style="font-size: 0.65rem;">
                    * Hệ tọa độ VN2000. Giá trị hiển thị nguyên bản từ backend, không lọc/ép UI.
                </div>

            </div>
        </div>
    </div>

`;
