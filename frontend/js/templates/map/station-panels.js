window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['station-panels'] = String.raw`    <!-- RIGHT DETAIL SIDEBAR -->
    <div class="detail-sidebar" id="detail-sidebar" aria-hidden="true">
        <div class="sidebar-header detail-sidebar-header">
            <div class="d-flex align-items-center justify-content-between">
                <div class="detail-station-identity d-flex align-items-baseline gap-2">
                    <h5 id="st-name" class="mb-0" style="font-size: 1.1rem;">Station Name</h5>
                    <small class="text-muted" id="st-code">CODE</small>
                </div>
                <div class="detail-header-actions d-flex gap-1">
                    <button class="btn btn-sm btn-outline-secondary btn-qr-share" title="Chia sẻ QR"
                        onclick="if(currentStationData) window.showStationQR(currentStationData.location?.lat, currentStationData.location?.lon, currentStationData.name)">
                        <i class="bi bi-qr-code"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-secondary btn-export-pdf" title="Xuất PDF"
                        onclick="window.exportStationPDF()">
                        <i class="bi bi-file-earmark-pdf"></i>
                    </button>
                    <button type="button" class="sidebar-close-btn" id="close-btn" aria-label="Đóng thông tin trạm">
                        <i class="bi bi-x-lg"></i>
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
                <div id="monitoring-sensor-values" class="monitoring-values"></div>
                <!-- COMPACT SENSOR DATA -->
                <div class="sensor-compact">
                    <!-- GNSS -->
                    <button type="button" class="sensor-item sensor-clickable" id="sensor-card-gnss"
                        title="Xem chi tiết GNSS" aria-label="Mở thông tin GNSS nâng cao"
                        aria-controls="gnss-advanced-sidepanel" aria-expanded="false">
                        <div class="sensor-label d-flex justify-content-between align-items-center">
                            <span title="Vận tốc 3D Theil-Sen trong cửa sổ thời gian, không phải vận tốc tức thời"><i class="bi bi-geo-alt-fill me-1"></i>Vận tốc GNSS (3D) <i
                                    class="bi bi-info-circle ms-1 small opacity-50"></i></span>
                            <span id="gnss-fix-badge" class="gnss-fix-badge GNSS_UNKNOWN">NO DATA</span>
                            <span id="gnss-offline-badge" class="sensor-offline-badge"
                                style="display:none;">OFFLINE</span>
                        </div>
                        <div class="sensor-value-large" id="val-gnss-vel">--<span class="sensor-unit">mm/s</span></div>
                        <div id="gnss-eval-summary" class="mt-1" style="display: none; font-size: 0.7rem; font-weight: 500;">
                            <!-- Đánh giá Theil-Sen Summary -->
                        </div>
                    </button>

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
                    <div class="sensor-item sensor-full-width sensor-imu-instrument" id="sensor-card-imu">
                        <div class="sensor-label d-flex justify-content-between align-items-center">
                            <span><i class="bi bi-compass-fill me-1"></i>IMU (ROLL/PITCH/YAW)</span>
                            <span id="imu-offline-badge" class="imu-offline-badge" style="display:none;">OFFLINE</span>
                        </div>
                        <div class="imu-axes" aria-label="Roll, pitch and yaw">
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
                        <div class="mt-2 pt-1 border-top imu-baseline-section">
                            <div class="imu-delta-header">Chuyển vị từ Baseline</div>
                            <div class="imu-delta-grid">
                                <div class="imu-delta-item">
                                    <span class="imu-delta-axis">Roll (X)</span>
                                    <span class="imu-delta-hint">← Trái / Phải →</span>
                                    <span class="imu-delta-num" id="val-imu-delta-roll">-- mm</span>
                                </div>
                                <div class="imu-delta-item">
                                    <span class="imu-delta-axis">Pitch (Y)</span>
                                    <span class="imu-delta-hint">↓ Trước / Sau ↑</span>
                                    <span class="imu-delta-num" id="val-imu-delta-pitch">-- mm</span>
                                </div>
                                <div class="imu-delta-item">
                                    <span class="imu-delta-axis">Yaw (Z)</span>
                                    <span class="imu-delta-hint">↺ Trái / Phải ↻</span>
                                    <span class="imu-delta-num" id="val-imu-delta-yaw">-- mm</span>
                                </div>
                            </div>
                        </div>

                        <!-- Thêm khoảng cách dịch nghiêng -->
                        <div class="mt-1 pt-1 border-top imu-drift-summary" style="opacity: 0.8;">
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
                    <button class="btn-action" id="btn-show-charts" aria-controls="charts-panel" aria-expanded="false">
                        <i class="bi bi-graph-up me-2"></i>View Chart
                    </button>
                    <button class="btn-action w-100 secondary d-none" id="btn-long-term">
                        <i class="bi bi-calendar-range me-2"></i>Analysis
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
    <div class="charts-panel" id="charts-panel" role="dialog" aria-label="Biểu đồ trạm" aria-hidden="true">
        <div class="charts-panel-header">
            <div class="charts-heading">
                <div class="charts-heading-title">
                    <i class="bi bi-activity" aria-hidden="true"></i>
                    <h5>Biểu đồ quan trắc</h5>
                    <span class="charts-period">24 giờ</span>
                </div>
                <p id="charts-station-context">Dữ liệu cảm biến của trạm đang chọn</p>
            </div>
            <button type="button" class="btn btn-sm" id="close-charts-btn" aria-label="Đóng biểu đồ">
                <i class="bi bi-x-lg"></i>
            </button>
        </div>

        <div class="charts-panel-content">
            <div class="charts-toolbar" aria-label="Khoảng thời gian biểu đồ">
                <div class="chart-range-selector" id="chart-range-selector" role="group" aria-label="Chọn khoảng thời gian">
                    <button type="button" class="chart-range-btn active" data-chart-hours="24" aria-pressed="true">24 giờ</button>
                    <button type="button" class="chart-range-btn" data-chart-hours="168" aria-pressed="false">7 ngày</button>
                    <button type="button" class="chart-range-btn" data-chart-hours="720" aria-pressed="false">30 ngày</button>
                    <button type="button" class="chart-range-btn" data-chart-hours="8760" aria-pressed="false">1 năm</button>
                </div>
                <span class="charts-point-meta" id="charts-point-meta">Mặc định 24 giờ</span>
            </div>

            ${(window.SensorCatalog || []).filter(sensor => !sensor.legacy && sensor.key !== 'extensometer').map(sensor => sensor.fields.map(field => `
                <div class="chart-box" id="chart-box-${sensor.key}-${field}">
                    <div class="chart-title">${sensor.metrics?.find(metric => metric.field === field)?.label || sensor.label} (${sensor.unit})</div>
                    <div class="chart-canvas-wrap"><canvas id="chart-${sensor.key}-${field}"></canvas></div>
                </div>`).join('')).join('')}
            <div id="extensometer-charts"></div>
            <div id="accelerometer-waveform-charts"></div>
            <!-- GNSS Chart -->
            <div class="chart-box" id="chart-box-gnss">
                <div class="chart-title"><i class="bi bi-speedometer2"></i><span>Vận tốc GNSS</span></div>
                <div class="chart-stat-grid">
                    <div class="flex-fill">
                        <div class="small text-muted" style="font-size: 0.7rem;">Hiện tại</div>
                        <div class="fw-bold text-primary" id="stat-chart-gnss-latest">--</div>
                    </div>
                    <div class="flex-fill border-start">
                        <div class="small text-muted" style="font-size: 0.7rem;">Max</div>
                        <div class="fw-bold text-danger" id="stat-chart-gnss-max">--</div>
                    </div>
                    <div class="flex-fill border-start">
                        <div class="small text-muted" style="font-size: 0.7rem;">Min</div>
                        <div class="fw-bold text-success" id="stat-chart-gnss-min">--</div>
                    </div>
                    <div class="flex-fill border-start">
                        <div class="small text-muted" style="font-size: 0.7rem;">Trung bình</div>
                        <div class="fw-bold text-info" id="stat-chart-gnss-avg">--</div>
                    </div>
                </div>
                <div class="chart-canvas-wrap">
                    <canvas id="chart-gnss"></canvas>
                </div>
            </div>

            <!-- Rain Chart -->
            <div class="chart-box" id="chart-box-rain">
                <div class="chart-title"><i class="bi bi-cloud-rain"></i><span>Cường độ mưa</span></div>
                <div class="chart-canvas-wrap">
                    <canvas id="chart-rain"></canvas>
                </div>
            </div>

            <!-- Water Chart -->
            <div class="chart-box" id="chart-box-water">
                <div class="chart-title"><i class="bi bi-water"></i><span>Mực nước</span></div>
                <div class="chart-stat-grid">
                    <div class="flex-fill">
                        <div class="small text-muted" style="font-size: 0.7rem;">Hiện tại</div>
                        <div class="fw-bold text-primary" id="stat-chart-water-latest">--</div>
                    </div>
                    <div class="flex-fill border-start">
                        <div class="small text-muted" style="font-size: 0.7rem;">Max</div>
                        <div class="fw-bold text-danger" id="stat-chart-water-max">--</div>
                    </div>
                    <div class="flex-fill border-start">
                        <div class="small text-muted" style="font-size: 0.7rem;">Min</div>
                        <div class="fw-bold text-success" id="stat-chart-water-min">--</div>
                    </div>
                    <div class="flex-fill border-start">
                        <div class="small text-muted" style="font-size: 0.7rem;">Trung bình</div>
                        <div class="fw-bold text-info" id="stat-chart-water-avg">--</div>
                    </div>
                </div>
                <div class="chart-canvas-wrap">
                    <canvas id="chart-water"></canvas>
                </div>
            </div>

            <!-- IMU Chart (3-axis) -->
            <div class="chart-box" id="chart-box-imu">
                <div class="chart-title d-flex justify-content-between align-items-center">
                    <span><i class="bi bi-compass"></i> Góc nghiêng IMU</span>
                    <button class="btn btn-sm btn-outline-primary" id="btn-toggle-imu-3d"
                        aria-label="Chuyển chế độ biểu đồ IMU 2D hoặc 3D">
                        <i class="bi bi-box me-1"></i>3D
                    </button>
                </div>
                <div id="chart-imu-wrapper" class="chart-canvas-wrap">
                    <canvas id="chart-imu"></canvas>
                </div>
                <div id="realtime-imu-3d-wrapper" class="chart-canvas-wrap chart-3d-wrap">
                    <div id="realtime-imu-3d-scene"></div>
                </div>
            </div>

`;
