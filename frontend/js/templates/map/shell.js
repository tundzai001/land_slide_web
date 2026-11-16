window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['shell'] = `
<!-- TOP NAVBAR -->
    <nav class="top-navbar">
        <div class="d-flex align-items-center gap-3">
            <!-- Hamburger Menu -->
            <button type="button" class="navbar-hamburger" id="navbar-hamburger-btn" title="Danh sách trạm"
                aria-label="Mở danh sách trạm" aria-controls="station-list-sidebar" aria-expanded="false">
                <i class="bi bi-list"></i>
            </button>

            <a href="#" class="brand-text" data-map-home>
                <span class="app-brand-plate"><img src="/assets/aitogy.png?v=__BUILD_VERSION__" width="759" height="329" alt="Aitogy"></span>
                <span class="app-brand-product"><strong>Monitoring</strong><small>Quan trắc</small></span>
            </a>

            <span class="map-workspace-label">Bản đồ quan trắc</span>

            <button type="button" id="btn-digital-twin" class="btn btn-sm map-simulation-nav"
                aria-label="Mở mô phỏng sạt lở 3D" style="display:none">
                <i class="bi bi-boxes me-1"></i> Mô phỏng 3D
            </button>

            <a href="/management" id="admin-nav-btn" class="btn btn-sm btn-outline-primary"
                style="display: none;">
                <i class="bi bi-gear me-1"></i> Quản trị
            </a>
        </div>

        <div class="d-flex align-items-center gap-3">
            <!-- Compact Layer Toggle Switch -->
            <label class="layer-toggle-switch" aria-label="Chế độ hiển thị bản đồ">
                <input type="checkbox" id="layer-mode-toggle" class="layer-mode-input">
                <span class="layer-mode-option station-mode" id="icon-layer-station"><i class="bi bi-broadcast-pin"></i><span>Trạm</span></span>
                <span class="layer-mode-option rescue-mode" id="icon-layer-rescue"><i class="bi bi-life-preserver"></i><span>Cứu hộ</span></span>
            </label>

            <div class="map-layer-control basemap-control">
                <button type="button" id="basemap-toggle" class="map-icon-button" aria-label="Đổi nền bản đồ" aria-expanded="false" aria-controls="basemap-popover" title="Đổi nền bản đồ"><i class="bi bi-map"></i><span>Nền</span></button>
                <fieldset id="basemap-popover" class="map-layer-popover" hidden><legend>Nền bản đồ</legend>
                    <label><input type="radio" name="basemap" value="roadmap"><span><i class="bi bi-signpost-split"></i> Đường phố</span></label>
                    <label><input type="radio" name="basemap" value="satellite"><span><i class="bi bi-globe"></i> Vệ tinh</span></label>
                    <label><input type="radio" name="basemap" value="hybrid" checked><span><i class="bi bi-geo-alt"></i> Vệ tinh có nhãn</span></label>
                    <label><input type="radio" name="basemap" value="terrain"><span><i class="bi bi-map"></i> Địa hình</span></label>
                    <p id="basemap-status" role="status" aria-live="polite">Vệ tinh có nhãn</p>
                </fieldset>
            </div>

            <div class="map-layer-control">
                <button type="button" id="layer-popover-toggle" class="map-icon-button" aria-label="Chọn lớp bản đồ" aria-expanded="false" aria-controls="layer-popover"><i class="bi bi-layers"></i></button>
                <fieldset id="layer-popover" class="map-layer-popover" hidden><legend>Lớp hiển thị</legend>
                    <label><input type="checkbox" id="layer-station" checked><span><i class="bi bi-broadcast-pin"></i> Trạm quan trắc</span></label>
                    <label><input type="checkbox" id="layer-cors" checked><span><i class="bi bi-crosshair"></i> Trạm CORS base</span></label>
                    <label><input type="checkbox" id="layer-rescue" checked><span><i class="bi bi-life-preserver"></i> Yêu cầu cứu hộ</span></label>
                    <label><input type="checkbox" id="layer-heatmap"><span><i class="bi bi-fire"></i> Mật độ cảnh báo</span></label>
                </fieldset>
            </div>

            <button type="button" id="theme-toggle-btn" class="map-icon-button" aria-label="Chuyển giao diện tối" aria-pressed="false">
                <svg class="theme-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20.2 15.6A8.6 8.6 0 0 1 8.4 3.8 8.6 8.6 0 1 0 20.2 15.6Z"/></svg><svg class="theme-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.6"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
            </button>

            <!-- Auth Button -->
            <button id="auth-btn" class="btn btn-primary btn-sm">
                <i class="bi bi-person-circle me-1"></i> Tài khoản
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
                <h4 class="alert-title" id="alert-title">CẢNH BÁO NGHIÊM TRỌNG</h4>
                <div class="alert-info-line">
                    <span class="alert-station" id="alert-station">Trạm: Đang xác định…</span>
                    <span class="alert-message" id="alert-message">Chưa có mô tả cảnh báo.</span>
                </div>
            </div>
            <div class="alert-actions">
                <button class="btn-alert-follow" id="btn-alert-follow">
                    <i class="bi bi-geo-alt-fill me-1"></i> Theo dõi
                </button>
                <button class="btn-alert-dismiss" id="btn-alert-dismiss" aria-label="Ẩn cảnh báo">
                    <i class="bi bi-x-lg"></i>
                </button>
            </div>
        </div>
    </div>

    <!-- LEFT SIDEBAR (Station List) -->
    <div class="station-list-sidebar" id="station-list-sidebar" role="complementary"
        aria-label="Danh sách trạm" aria-hidden="true">
        <div class="sidebar-header station-list-header">
            <div>
                <span class="map-panel-eyebrow">MẠNG QUAN TRẮC</span>
                <h6><i class="bi bi-hdd-network me-2"></i>Danh sách trạm</h6>
            </div>
        </div>

        <button class="sidebar-close-tab" id="sidebar-close-tab" type="button"
            aria-label="Thu gọn danh sách trạm" title="Thu gọn danh sách trạm">
            <i class="bi bi-chevron-left"></i>
        </button>

        <div class="sidebar-search station-search-field">
            <i class="bi bi-search" aria-hidden="true"></i>
            <input type="search" class="form-control form-control-sm" placeholder="Tìm tên hoặc mã trạm…" id="search-station" aria-label="Tìm trạm">
        </div>

        <div class="station-filter-bar">
            <label for="station-status-filter"><i class="bi bi-funnel" aria-hidden="true"></i><span class="visually-hidden">Lọc trạng thái trạm</span>
                <select id="station-status-filter" aria-label="Lọc trạng thái trạm">
                    <option value="all">Tất cả trạng thái</option>
                    <option value="online">Trực tuyến</option>
                    <option value="alert">Đang cảnh báo</option>
                    <option value="offline">Mất kết nối</option>
                </select>
            </label>
            <span id="station-filter-result" role="status">0 trạm</span>
        </div>

        <div class="station-list-content" id="station-list-container">
            <!-- Station list here -->
            <div class="station-filter-empty" id="station-filter-empty" hidden><i class="bi bi-search"></i><span>Không có trạm phù hợp</span></div>
        </div>
    </div>

    <!-- MAP -->
    <div id="map">
    </div>

    <aside class="map-status-legend" aria-label="Chú giải trạng thái trạm">
        <span><i class="status-dot is-safe"></i>An toàn</span>
        <span><i class="status-dot is-warning"></i>Cảnh báo</span>
        <span><i class="status-dot is-critical"></i>Nguy cấp</span>
        <span><i class="status-dot is-stale"></i>Dữ liệu cũ</span>
        <span><i class="status-dot is-offline"></i>Ngoại tuyến</span>
    </aside>

    <aside class="map-heatmap-legend" id="heatmap-legend" aria-label="Chú giải mật độ cảnh báo" hidden>
        <strong>Mật độ cảnh báo</strong>
        <span id="heatmap-count" role="status" aria-live="polite"></span>
        <span class="heatmap-gradient" aria-hidden="true"></span>
        <span class="heatmap-scale"><span>Ít / cảnh báo</span><span>Nhiều / nguy cấp</span></span>
    </aside>

    <nav class="map-bottom-nav" id="map-bottom-nav" aria-label="Điều hướng bản đồ">
        <button type="button" data-map-action="stations"><i class="bi bi-hdd-network"></i><span>Trạm</span></button>
        <button type="button" data-map-action="layers"><i class="bi bi-layers"></i><span>Lớp bản đồ</span></button>
        <button type="button" data-map-action="rescue" hidden><i class="bi bi-life-preserver"></i><span>Cứu hộ</span></button>
        <button type="button" data-map-action="account"><i class="bi bi-person-circle"></i><span>Tài khoản</span></button>
    </nav>

    <!-- CUSTOM GLASS ZOOM CONTROLS (Bottom-Right) -->
    <div class="custom-map-controls">
        <div class="heatmap-toggle-wrap">
            <button class="heatmap-toggle-btn" id="heatmap-toggle" title="Bật/Tắt mật độ cảnh báo"
                aria-label="Bật hoặc tắt mật độ cảnh báo" aria-pressed="false" aria-controls="heatmap-legend">
                <i class="bi bi-fire"></i>
            </button>
        </div>
        <span class="map-control-divider" aria-hidden="true"></span>
        <button class="map-ctrl-btn" id="map-zoom-in" title="Phóng to" aria-label="Phóng to bản đồ">
            <i class="bi bi-plus-lg"></i>
        </button>
        <button class="map-ctrl-btn" id="map-zoom-out" title="Thu nhỏ" aria-label="Thu nhỏ bản đồ">
            <i class="bi bi-dash-lg"></i>
        </button>
    </div>

    <!-- TIMELINE SLIDER -->
    <div class="timeline-slider-container" id="timeline-slider-wrap" style="display: none;">
        <span class="timeline-label" id="timeline-label">Ngày 30</span>
        <input type="range" min="1" max="30" value="30" id="timeline-slider">
        <span class="timeline-label opacity-50" style="font-size:0.65rem;">30 Ngày</span>
    </div>

    <div class="gnss-advanced-sidepanel" id="gnss-advanced-sidepanel" role="dialog"
        aria-label="Thông tin GNSS nâng cao" aria-hidden="true">
        <div class="sidepanel-header">
            <h6><i class="bi bi-gear-wide-connected me-2"></i>GNSS nâng cao &amp; bình sai mạng</h6>
            <button type="button" class="sidepanel-close" id="gnss-sidepanel-close"
                aria-label="Đóng thông tin GNSS nâng cao"><i class="bi bi-x-lg"></i></button>
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
                        <div class="adv-value-row"><span class="adv-value" id="adv-val-dx">--</span><span
                                class="adv-unit">cm</span></div>
                    </div>
                    <div class="adv-item">
                        <span class="adv-label">Biến dạng &Delta;Y (North)</span>
                        <div class="adv-value-row"><span class="adv-value" id="adv-val-dy">--</span><span
                                class="adv-unit">cm</span></div>
                    </div>
                    <div class="adv-item">
                        <span class="adv-label">Biến dạng &Delta;H (Up)</span>
                        <div class="adv-value-row"><span class="adv-value" id="adv-val-dh">--</span><span
                                class="adv-unit">cm</span></div>
                    </div>
                </div>

                <div class="adv-section gnss-integrity-section" id="gnss-integrity-section" data-state="unknown">
                    <div class="adv-section-title d-flex justify-content-between align-items-center gap-2">
                        <span><i class="bi bi-shield-check me-1"></i>Toàn vẹn GNSS & mốc tham chiếu</span>
                        <span class="gnss-integrity-badge" id="gnss-integrity-badge" role="status">NO DATA</span>
                    </div>
                    <p class="gnss-integrity-message" id="gnss-integrity-message">Chưa có đánh giá toàn vẹn GNSS.</p>
                    <div class="row g-2 small" id="gnss-integrity-shift-grid">
                        <div class="col-4"><span class="adv-label">Dịch Đông</span><div id="gnss-shift-e">--</div></div>
                        <div class="col-4"><span class="adv-label">Dịch Bắc</span><div id="gnss-shift-n">--</div></div>
                        <div class="col-4"><span class="adv-label">Dịch cao</span><div id="gnss-shift-u">--</div></div>
                        <div class="col-6"><span class="adv-label">Độ lớn 2D / 3D</span><div id="gnss-shift-mag">--</div></div>
                        <div class="col-6"><span class="adv-label">Độ phân tán XY / U</span><div id="gnss-shift-spread">--</div></div>
                        <div class="col-6"><span class="adv-label">Thời lượng</span><div id="gnss-shift-duration">--</div></div>
                        <div class="col-6"><span class="adv-label">Sự kiện mốc</span><div id="gnss-reference-event">--</div></div>
                    </div>
                </div>

                <!-- Nhóm 3: Vận tốc THÔ (Raw - trước lọc) -->
                <div class="adv-section">
                    <div class="adv-section-title text-secondary"><i class="bi bi-speedometer me-1"></i>Vận tốc thô</div>
                    <div class="row g-2">
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">East</span>
                                <div class="adv-value-row"><span class="adv-value text-secondary" id="adv-val-raw-ve">--</span><span class="adv-unit">mm/s</span></div>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">North</span>
                                <div class="adv-value-row"><span class="adv-value text-secondary" id="adv-val-raw-vn">--</span><span class="adv-unit">mm/s</span></div>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">Up</span>
                                <div class="adv-value-row"><span class="adv-value text-secondary" id="adv-val-raw-vu">--</span><span class="adv-unit">mm/s</span></div>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">Tốc độ 2D</span>
                                <div class="adv-value-row"><span class="adv-value text-secondary fw-bold" id="adv-val-raw-2d">--</span><span class="adv-unit">mm/s</span></div>
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
                                <div class="adv-value-row"><span class="adv-value text-info" id="adv-val-filt-ve">--</span><span class="adv-unit">mm/s</span></div>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">North</span>
                                <div class="adv-value-row"><span class="adv-value text-info" id="adv-val-filt-vn">--</span><span class="adv-unit">mm/s</span></div>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">Up</span>
                                <div class="adv-value-row"><span class="adv-value text-info" id="adv-val-filt-vu">--</span><span class="adv-unit">mm/s</span></div>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="adv-item">
                                <span class="adv-label">Tốc độ 2D</span>
                                <div class="adv-value-row"><span class="adv-value text-info fw-bold" id="adv-val-filt-2d">--</span><span class="adv-unit">mm/s</span></div>
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
                                <div class="adv-value-row"><span class="adv-value" id="adv-val-vdx">--</span><span class="adv-unit">mm/min</span></div>
                            </div>
                        </div>
                        <div class="col-4">
                            <div class="adv-item">
                                <span class="adv-label">&Delta;Y (N)</span>
                                <div class="adv-value-row"><span class="adv-value" id="adv-val-vdy">--</span><span class="adv-unit">mm/min</span></div>
                            </div>
                        </div>
                        <div class="col-4">
                            <div class="adv-item">
                                <span class="adv-label">&Delta;H (U)</span>
                                <div class="adv-value-row"><span class="adv-value" id="adv-val-vdh">--</span><span class="adv-unit">mm/min</span></div>
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
                        <span class="adv-label">Cửa sổ chuyển vị (độc lập với cửa sổ vận tốc)</span>
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
                        <span class="adv-label">Cửa sổ vận tốc (để tính Theil-Sen):</span>
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
                        <span class="adv-label">Độ bất định:</span>
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

            </div>
        </div>
    </div>

`;
