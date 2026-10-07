window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['station-connectivity'] = String.raw`                        <!-- STEP 2: MQTT & TỌA ĐỘ -->
                        <div class="wizard-content" data-step="2" aria-labelledby="station-connectivity-heading">
                            <div class="station-step-intro">
                                <div>
                                    <span class="station-step-kicker">Bước 2 / 4</span>
                                    <h6 id="station-connectivity-heading">Kết nối &amp; định vị</h6>
                                    <p>Chọn cảm biến đang sử dụng, cấu hình MQTT và kiểm tra tọa độ lắp đặt.</p>
                                </div>
                                <span class="station-step-status"><i class="bi bi-shield-check" aria-hidden="true"></i> Kiểm tra tại chỗ</span>
                            </div>
                            <div class="alert alert-info small mb-3 station-flow-hint">
                                <i class="bi bi-info-circle me-1"></i>
                                Chọn cảm biến <i class="bi bi-chevron-right mx-1" aria-hidden="true"></i>
                                Nhập MQTT Topic <i class="bi bi-chevron-right mx-1" aria-hidden="true"></i>
                                Kiểm tra tọa độ
                            </div>

                            <fieldset class="monitoring-picker">
                                <legend>Chọn cảm biến quan trắc</legend>
                                <p>Chọn nhiều loại cho cùng một trạm. Mỗi loại có kết nối riêng.</p>
                                <label for="sensor-catalog-search">Tìm cảm biến</label>
                                <input id="sensor-catalog-search" type="search" class="form-control" placeholder="Tên cảm biến hoặc nhóm quan trắc" oninput="window.filterSensorCatalog(this.value)">
                                <div class="monitoring-picker-actions">
                                    <button type="button" class="btn btn-outline-primary" onclick="window.selectSensorGroup('Thân đập')">Chọn nhóm thân đập</button>
                                    <button type="button" class="btn btn-outline-primary" onclick="window.selectSensorGroup('Thấm & nền đập')">Chọn nhóm thấm</button>
                                </div>
                                <div class="monitoring-picker-grid">
                                ${(window.SensorCatalog || [{key:'gnss',label:'GNSS'}, {key:'rain',label:'Lượng mưa'}, {key:'water',label:'Mực nước'}, {key:'imu',label:'IMU'}]).map(sensor => `
                                    <label class="monitoring-choice" data-sensor-choice>
                                        <input type="checkbox" id="edit-${sensor.key}">
                                        <span><strong>${sensor.label}</strong><small>${sensor.group || ''}</small></span>
                                    </label>`).join('')}
                                </div>
                            </fieldset>

                            <h6 class="mb-3">2. Cấu hình MQTT & Tọa độ theo cảm biến:</h6>

                            ${(window.SensorCatalog || []).filter(sensor => !sensor.legacy).map(sensor => `
                            <section id="mqtt-${sensor.key}-section" class="sensor-config-section" style="display:none">
                                <div class="sensor-config-header">${sensor.label} · ${sensor.unit}</div>
                                <div class="sensor-config-body">
                                    <label class="form-label" for="topic-${sensor.key}">MQTT Topic</label>
                                    <input class="form-control" id="topic-${sensor.key}" placeholder="station/ST01/${sensor.key}">
                                    <div class="row g-2 mt-2">
                                        <div class="col-md-8"><label for="cfg-${sensor.key}-mqtt-host">MQTT Broker</label><input class="form-control" id="cfg-${sensor.key}-mqtt-host" placeholder="Dùng broker mặc định"></div>
                                        <div class="col-md-4"><label for="cfg-${sensor.key}-mqtt-port">Port</label><input type="number" min="1" max="65535" class="form-control" id="cfg-${sensor.key}-mqtt-port" placeholder="1883"></div>
                                        <div class="col-md-6"><label for="cfg-${sensor.key}-mqtt-user">Tài khoản</label><input class="form-control" id="cfg-${sensor.key}-mqtt-user" autocomplete="off"></div>
                                        <div class="col-md-6"><label for="cfg-${sensor.key}-mqtt-pass">Mật khẩu</label><input type="password" class="form-control" id="cfg-${sensor.key}-mqtt-pass" autocomplete="new-password"></div>
                                    </div>
                                    <label class="monitoring-choice"><input type="checkbox" id="cfg-${sensor.key}-mqtt-tls"> Mã hóa TLS</label>
                                    <div class="row g-2 mt-2">
                                        ${[['lat','Vĩ độ',-90,90],['lon','Kinh độ',-180,180],['h','Cao độ (m)',-1000,10000]].map(([axis,label,min,max]) => `<div class="col-md-4"><label for="origin-${sensor.key}-${axis}">${label}</label><input class="form-control" type="number" step="any" min="${min}" max="${max}" id="origin-${sensor.key}-${axis}"></div>`).join('')}
                                    </div>
                                </div>
                            </section>`).join('')}

                            <div id="mqtt-gnss-section" class="sensor-config-section" style="display: none;">
                                <div class="sensor-config-header">
                                    <i class="bi bi-geo-alt-fill text-danger"></i>
                                    <span>GNSS Configuration</span>
                                </div>
                                <div class="sensor-config-body">

                                    <div class="row g-2 mb-2">
                                        <div class="col-md-5">
                                            <label class="form-label small fw-semibold">MQTT Host / Broker</label>
                                            <input type="text" class="form-control form-control-sm" id="cfg-gnss-mqtt-host" placeholder="Để trống để dùng mặc định">
                                        </div>
                                        <div class="col-md-2">
                                            <label class="form-label small fw-semibold">Port</label>
                                            <input type="number" class="form-control form-control-sm" id="cfg-gnss-mqtt-port" placeholder="1883">
                                        </div>
                                        <div class="col-md-5">
                                            <label class="form-label small fw-semibold d-block">&nbsp;</label>
                                            <label class="ios-toggle-wrap is-off" id="wrap-gnss-mqtt-tls" onclick="window.adminManager.toggleForwardingWrap(event,this,'cfg-gnss-mqtt-tls')">
                                                <div class="ios-toggle-info">
                                                    <div class="param-name">Bật TLS (SSL)</div>
                                                    <div class="param-unit text-muted" style="font-size: 0.7rem;">Mã hoá kết nối</div>
                                                </div>
                                                <div class="ios-switch">
                                                    <input type="checkbox" id="cfg-gnss-mqtt-tls">
                                                    <span class="ios-switch-track"></span>
                                                </div>
                                            </label>
                                        </div>
                                    </div>
                                    <div class="row g-2 mb-3 border-bottom pb-3">
                                        <div class="col-md-6">
                                            <label class="form-label small fw-semibold">Username</label>
                                            <input type="text" class="form-control form-control-sm" id="cfg-gnss-mqtt-user" placeholder="Tài khoản">
                                        </div>
                                        <div class="col-md-6">
                                            <label class="form-label small fw-semibold">Password</label>
                                            <input type="password" class="form-control form-control-sm" id="cfg-gnss-mqtt-pass" placeholder="Mật khẩu">
                                        </div>
                                    </div>

                                    <div class="p-3 mb-3 rounded border"
                                        style="background:rgba(6,182,212,.06);border-color:rgba(6,182,212,.28)!important">
                                        <div class="d-flex align-items-center justify-content-between gap-2 mb-2">
                                            <label class="form-label small fw-semibold mb-0" for="cfg-gnss-aicaster-user">
                                                <i class="bi bi-broadcast-pin text-info me-1"></i>User AICaster của rover
                                            </label>
                                            <button type="button" class="btn btn-sm btn-outline-info"
                                                id="btn-refresh-aicaster-users"
                                                onclick="window.adminManager.loadAICasterUsers()">
                                                <i class="bi bi-arrow-clockwise me-1"></i>Làm mới
                                            </button>
                                        </div>
                                        <select class="form-select form-select-sm" id="cfg-gnss-aicaster-user">
                                            <option value="">-- Chọn user AICaster của rover --</option>
                                        </select>
                                        <small class="d-block text-muted mt-2" id="aicaster-user-status">
                                            Danh sách lấy trực tiếp bằng GET /usertable; mật khẩu không được đưa ra trình duyệt.
                                        </small>
                                    </div>

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
                                            <div class="d-flex flex-wrap justify-content-end gap-2">
                                                <button type="button" class="btn btn-sm btn-outline-warning"
                                                    id="btn-reset-origin"
                                                    onclick="window.adminManager.resetGnssOrigin(window.adminManager.currentStationId)">
                                                    <i class="bi bi-crosshair me-1"></i> Hiệu chuẩn offset
                                                </button>
                                                <button type="button" class="btn btn-sm btn-outline-danger"
                                                    id="btn-relock-origin"
                                                    onclick="window.adminManager.relockGnssOrigin(window.adminManager.currentStationId)">
                                                    <i class="bi bi-lock-fill me-1" aria-hidden="true"></i> Khóa lại tọa độ gốc
                                                </button>
                                                <button type="button" class="btn btn-sm btn-warning"
                                                    id="btn-fetch-origin"
                                                    onclick="window.adminManager.fetchLatestOrigin()">
                                                    <i class="bi bi-arrow-repeat me-1"></i> Lấy tọa độ
                                                </button>
                                            </div>
                                        </div>
                                        <div id="gnss-origin-relock-progress" class="mt-3 p-3 border rounded-3 bg-body-tertiary" hidden aria-live="polite">
                                            <div class="d-flex justify-content-between align-items-center gap-2 mb-2">
                                                <strong id="gnss-origin-relock-label" class="small">Đang thu mẫu RTK FIXED</strong>
                                                <span id="gnss-origin-relock-counts" class="small text-muted">0/61 mẫu · 0/60 giây</span>
                                            </div>
                                            <div class="progress" role="progressbar" aria-label="Tiến trình khóa lại tọa độ gốc" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" style="height: 10px;">
                                                <div id="gnss-origin-relock-bar" class="progress-bar progress-bar-striped progress-bar-animated bg-info" style="width: 0%;"></div>
                                            </div>
                                            <div class="d-flex justify-content-between flex-wrap gap-1 mt-2">
                                                <small id="gnss-origin-relock-detail" class="text-muted">Giữ RTK FIXED ổn định trong lúc thu mẫu.</small>
                                                <small id="gnss-origin-relock-remaining" class="text-muted">Đang kết nối thiết bị…</small>
                                            </div>
                                        </div>
                                        <div id="gnss-offset-result" class="gnss-offset-result" hidden aria-live="polite">
                                            <div class="gnss-offset-result-heading">
                                                <span><i class="bi bi-activity me-1" aria-hidden="true"></i>Tracking offset đang áp dụng</span>
                                                <small id="gnss-offset-state">Đang đọc…</small>
                                            </div>
                                            <div class="gnss-offset-grid">
                                                <div><span>Offset E</span><strong id="gnss-offset-e">—</strong><small>mm</small></div>
                                                <div><span>Offset N</span><strong id="gnss-offset-n">—</strong><small>mm</small></div>
                                                <div><span>Offset U</span><strong id="gnss-offset-u">—</strong><small>mm</small></div>
                                                <div><span>Tổng 2D</span><strong id="gnss-offset-2d">—</strong><small>mm</small></div>
                                            </div>
                                            <div class="gnss-offset-meta"><span id="gnss-offset-samples">Dữ liệu runtime/DB</span><span id="gnss-offset-duration">—</span><span>Origin không đổi</span></div>
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
                                            <div class="mb-3">
                                                <label class="form-label" for="gnss-forwarding-approval">Số văn bản / nội dung chấp thuận của Chủ đầu tư</label>
                                                <input class="form-control" id="gnss-forwarding-approval" maxlength="500" placeholder="Ví dụ: Văn bản 123/CĐT ngày 06/10/2026">
                                                <small class="text-muted">Mặc định khóa chuyển tiếp. Admin ghi nhận văn bản chấp thuận để mở khóa.</small>
                                            </div>
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

                                <div class="row g-2 mb-2">
                                    <div class="col-md-5">
                                        <label class="form-label small fw-semibold">MQTT Host / Broker</label>
                                        <input type="text" class="form-control form-control-sm" id="cfg-rain-mqtt-host" placeholder="Để trống để dùng mặc định">
                                    </div>
                                    <div class="col-md-2">
                                        <label class="form-label small fw-semibold">Port</label>
                                        <input type="number" class="form-control form-control-sm" id="cfg-rain-mqtt-port" placeholder="1883">
                                    </div>
                                    <div class="col-md-5">
                                            <label class="form-label small fw-semibold d-block">&nbsp;</label>
                                        <label class="ios-toggle-wrap is-off" id="wrap-rain-mqtt-tls" onclick="window.adminManager.toggleForwardingWrap(event,this,'cfg-rain-mqtt-tls')">
                                            <div class="ios-toggle-info">
                                                <div class="param-name">Bật TLS (SSL)</div>
                                                <div class="param-unit text-muted" style="font-size: 0.7rem;">Mã hoá kết nối</div>
                                            </div>
                                            <div class="ios-switch">
                                                <input type="checkbox" id="cfg-rain-mqtt-tls">
                                                <span class="ios-switch-track"></span>
                                            </div>
                                        </label>
                                    </div>
                                </div>
                                <div class="row g-2 mb-3 border-bottom pb-3">
                                    <div class="col-md-6">
                                        <label class="form-label small fw-semibold">Username</label>
                                        <input type="text" class="form-control form-control-sm" id="cfg-rain-mqtt-user" placeholder="Tài khoản">
                                    </div>
                                    <div class="col-md-6">
                                        <label class="form-label small fw-semibold">Password</label>
                                        <input type="password" class="form-control form-control-sm" id="cfg-rain-mqtt-pass" placeholder="Mật khẩu">
                                    </div>
                                </div>
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

                                <div class="row g-2 mb-2">
                                    <div class="col-md-5">
                                        <label class="form-label small fw-semibold">MQTT Host / Broker</label>
                                        <input type="text" class="form-control form-control-sm" id="cfg-water-mqtt-host" placeholder="Để trống để dùng mặc định">
                                    </div>
                                    <div class="col-md-2">
                                        <label class="form-label small fw-semibold">Port</label>
                                        <input type="number" class="form-control form-control-sm" id="cfg-water-mqtt-port" placeholder="1883">
                                    </div>
                                    <div class="col-md-5">
                                            <label class="form-label small fw-semibold d-block">&nbsp;</label>
                                        <label class="ios-toggle-wrap is-off" id="wrap-water-mqtt-tls" onclick="window.adminManager.toggleForwardingWrap(event,this,'cfg-water-mqtt-tls')">
                                            <div class="ios-toggle-info">
                                                <div class="param-name">Bật TLS (SSL)</div>
                                                <div class="param-unit text-muted" style="font-size: 0.7rem;">Mã hoá kết nối</div>
                                            </div>
                                            <div class="ios-switch">
                                                <input type="checkbox" id="cfg-water-mqtt-tls">
                                                <span class="ios-switch-track"></span>
                                            </div>
                                        </label>
                                    </div>
                                </div>
                                <div class="row g-2 mb-3 border-bottom pb-3">
                                    <div class="col-md-6">
                                        <label class="form-label small fw-semibold">Username</label>
                                        <input type="text" class="form-control form-control-sm" id="cfg-water-mqtt-user" placeholder="Tài khoản">
                                    </div>
                                    <div class="col-md-6">
                                        <label class="form-label small fw-semibold">Password</label>
                                        <input type="password" class="form-control form-control-sm" id="cfg-water-mqtt-pass" placeholder="Mật khẩu">
                                    </div>
                                </div>
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

                                <div class="row g-2 mb-2">
                                    <div class="col-md-5">
                                        <label class="form-label small fw-semibold">MQTT Host / Broker</label>
                                        <input type="text" class="form-control form-control-sm" id="cfg-imu-mqtt-host" placeholder="Để trống để dùng mặc định">
                                    </div>
                                    <div class="col-md-2">
                                        <label class="form-label small fw-semibold">Port</label>
                                        <input type="number" class="form-control form-control-sm" id="cfg-imu-mqtt-port" placeholder="1883">
                                    </div>
                                    <div class="col-md-5">
                                            <label class="form-label small fw-semibold d-block">&nbsp;</label>
                                        <label class="ios-toggle-wrap is-off" id="wrap-imu-mqtt-tls" onclick="window.adminManager.toggleForwardingWrap(event,this,'cfg-imu-mqtt-tls')">
                                            <div class="ios-toggle-info">
                                                <div class="param-name">Bật TLS (SSL)</div>
                                                <div class="param-unit text-muted" style="font-size: 0.7rem;">Mã hoá kết nối</div>
                                            </div>
                                            <div class="ios-switch">
                                                <input type="checkbox" id="cfg-imu-mqtt-tls">
                                                <span class="ios-switch-track"></span>
                                            </div>
                                        </label>
                                    </div>
                                </div>
                                <div class="row g-2 mb-3 border-bottom pb-3">
                                    <div class="col-md-6">
                                        <label class="form-label small fw-semibold">Username</label>
                                        <input type="text" class="form-control form-control-sm" id="cfg-imu-mqtt-user" placeholder="Tài khoản">
                                    </div>
                                    <div class="col-md-6">
                                        <label class="form-label small fw-semibold">Password</label>
                                        <input type="password" class="form-control form-control-sm" id="cfg-imu-mqtt-pass" placeholder="Mật khẩu">
                                    </div>
                                </div>
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
`;
