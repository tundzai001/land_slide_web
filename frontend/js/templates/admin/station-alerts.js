window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['station-alerts'] = String.raw`                <!-- STEP 3: NGƯỠNG CẢNH BÁO -->
                <div class="wizard-content" data-step="3" aria-labelledby="station-alerts-heading">
                    <div class="station-step-intro">
                        <div>
                            <span class="station-step-kicker">Bước 3 / 4</span>
                            <h6 id="station-alerts-heading">Ngưỡng &amp; xác nhận cảnh báo</h6>
                            <p>Chọn cấu hình khởi điểm, sau đó tinh chỉnh từng ngưỡng theo điều kiện thực địa.</p>
                        </div>
                        <span class="station-step-status"><i class="bi bi-bell" aria-hidden="true"></i> Theo từng trạm</span>
                    </div>

                    <!-- ✅ QUICK PRESETS CHO TRẠM -->
                    <div class="station-preset-panel mb-4">
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

`;
