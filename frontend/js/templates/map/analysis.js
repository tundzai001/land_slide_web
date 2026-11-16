window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['analysis'] = `            <!-- Empty State -->
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

                </div>

                <!-- ============================================ -->
                <!-- CROSS-SENSOR CONSENSUS SECTION -->
                <!-- ============================================ -->
                <div id="cross-consensus-section" class="mt-4" style="display: none;">
                    <h5 class="mb-3 border-bottom pb-2" style="color: var(--text-primary); font-size: 0.9rem;">
                        <i class="bi bi-intersect me-2"></i>Đồng thuận đa cảm biến
                    </h5>
                    <div id="consensus-banner" class="consensus-banner mb-3" style="padding: 10px; border-radius: 8px;">
                        <div class="d-flex align-items-center gap-2 flex-wrap mb-2">
                            <span id="consensus-badge" class="consensus-badge" style="font-size: 0.7rem;">--</span>
                            <span id="consensus-summary" class="fw-semibold" style="font-size: 0.8rem;"></span>
                        </div>
                        <div id="consensus-sensors-with-data" class="d-flex flex-wrap gap-1 mt-1"></div>
                    </div>
                    <div class="row g-2 mb-2">
                        <div class="col-6">
                            <div class="p-2 border border-secondary rounded" style="background: rgba(255,255,255,0.02);">
                                <div class="text-muted" style="font-size: 0.65rem;">Mưa (7 ngày)</div>
                                <div id="consensus-rain" class="fw-bold" style="font-size: 0.8rem;">--</div>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="p-2 border border-secondary rounded" style="background: rgba(255,255,255,0.02);">
                                <div class="text-muted" style="font-size: 0.65rem;">Gia tốc GNSS</div>
                                <div id="consensus-accel" class="fw-bold" style="font-size: 0.8rem;">--</div>
                            </div>
                        </div>
                    </div>
                    <div id="consensus-trend-agreement" class="fw-bold mt-1 mb-2 text-muted" style="font-size: 0.8rem;"></div>
                    <div id="consensus-notes" class="small text-muted" style="font-size: 0.72rem;"></div>
                    <div class="small text-muted fst-italic mt-1" id="consensus-desc" style="font-size: 0.7rem;"></div>
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

`;
