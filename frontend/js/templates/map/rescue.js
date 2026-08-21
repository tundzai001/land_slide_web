window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['rescue'] = String.raw`    <!-- FLOATING RESCUE FAB -->
    <button id="btn-guest-rescue" class="rescue-fab" aria-label="Yêu cầu cứu hộ">
        <span class="rescue-fab-icon">
            <i class="bi bi-exclamation-triangle-fill"></i>
        </span>
        <span class="rescue-fab-label">Yêu cầu cứu hộ</span>
    </button>

    <div class="modal fade" id="guestRescueModal" tabindex="-1" aria-labelledby="guestRescueModalLabel"
        aria-hidden="true">
        <div class="modal-dialog modal-dialog-centered modal-dialog-scrollable rescue-request-dialog">
            <div class="modal-content glass-modal-content rescue-request-modal">
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
                    <span class="dt-logo-copy">
                        <small>LS-RAPID</small>
                        <strong class="dt-logo-text">Mô phỏng sạt lở 3D</strong>
                    </span>
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
                <button class="dt-btn-back" id="btn-dt-history" title="Lịch sử mô phỏng">
                    <i class="bi bi-clock-history"></i> Lịch sử
                </button>
                <button class="dt-btn-icon" id="btn-toggle-panel" title="Ẩn hoặc hiện bảng tham số" aria-label="Ẩn hoặc hiện bảng tham số">
                    <i class="bi bi-layout-sidebar"></i>
                </button>
                <button class="dt-btn-icon" id="btn-fullscreen-dt" title="Toàn màn hình" aria-label="Mở toàn màn hình">
                    <i class="bi bi-arrows-fullscreen"></i>
                </button>
                <button class="dt-btn-back" id="btn-close-dt">
                    <i class="bi bi-x-lg"></i> Đóng 3D
                </button>
            </div>
        </header>

        <div id="dt-main">
            <aside id="dt-panel" class="dt-panel-open">
                <div class="dt-mode-switch" role="group" aria-label="Nguồn thông số mô phỏng">
                    <button type="button" class="active" data-simulation-mode="manual"><i class="bi bi-sliders"></i><span>Nhập thông số</span></button>
                    <button type="button" data-simulation-mode="station_snapshot"><i class="bi bi-broadcast-pin"></i><span>Dữ liệu trạm</span></button>
                </div>
                <div id="dt-station-source" class="dt-source-card" hidden>
                    <div><span>TRẠM ĐANG CHỌN</span><strong id="dt-source-name">Chưa chọn trạm</strong><small id="dt-source-freshness">Chọn một trạm trên bản đồ trước khi chạy</small></div>
                    <button type="button" id="btn-dt-live-evaluate" class="dt-btn-secondary"><i class="bi bi-activity"></i> Kiểm tra live</button>
                    <div id="dt-live-result" role="status" aria-live="polite"></div>
                </div>
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
                    <div class="dt-section-header"><i class="bi bi-droplet-half"></i><span>Thủy lực &amp; ngưỡng</span></div>
                    <div class="dt-param-group">
                        <label class="dt-param-label"><span>Hệ số thấm K<sub>s</sub> (×10⁻⁵ m/s)</span><output id="val-ks">1.5</output></label>
                        <input type="range" id="param-ks" min="0.1" max="100" value="1.5" step="0.1" class="dt-slider">
                    </div>
                    <div class="dt-param-group">
                        <label class="dt-param-label"><span>Độ rỗng</span><output id="val-porosity">0.25</output></label>
                        <input type="range" id="param-porosity" min="0.05" max="0.7" value="0.25" step="0.01" class="dt-slider">
                    </div>
                    <div class="dt-threshold-grid">
                        <label><span>FoS cảnh báo</span><input type="number" id="param-fos-warning" min="1" max="3" step="0.1" value="1.5"><output id="val-fos-warning">1.5</output></label>
                        <label><span>FoS nguy hiểm</span><input type="number" id="param-fos-critical" min="0.1" max="1.5" step="0.1" value="1.0"><output id="val-fos-critical">1.0</output></label>
                    </div>
                    <label class="dt-select-field" for="param-sim-duration"><span>Thời lượng kịch bản</span><select id="param-sim-duration"><option value="3600">1 giờ</option><option value="21600">6 giờ</option><option value="43200">12 giờ</option><option value="86400" selected>24 giờ</option><option value="259200">72 giờ</option><option value="604800">168 giờ</option></select><output id="val-sim-duration">24h</output></label>
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

                <div class="dt-run-card" id="dt-run-card" data-state="ready">
                    <div class="dt-run-context">
                        <span class="dt-run-eyebrow">Kịch bản đang dùng</span>
                        <strong id="dt-station-context">Kịch bản độc lập</strong>
                        <small id="dt-station-context-detail">Chưa gắn dữ liệu từ trạm quan trắc</small>
                    </div>
                    <div class="dt-run-status-line" role="status" aria-live="polite">
                        <i class="bi bi-check-circle-fill"></i>
                        <span id="dt-run-status-text">Sẵn sàng chạy mô phỏng</span>
                    </div>
                    <div class="dt-panel-actions">
                        <button id="btn-run-simulation" class="dt-btn-primary"><i class="bi bi-play-fill"></i> Chạy mô phỏng</button>
                        <button id="btn-reset-simulation" class="dt-btn-secondary"><i class="bi bi-arrow-counterclockwise"></i> Đặt lại tham số</button>
                    </div>
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
                    <div class="dt-warning-text"><i class="bi bi-exclamation-triangle-fill" aria-hidden="true"></i> CẢNH BÁO SẠT LỞ</div>
                    <div class="dt-warning-sub" id="dt-warning-fos">FoS = 0.95</div>
                </div>
            </div>

            <aside id="dt-results" class="dt-results" aria-hidden="true" aria-label="Kết quả mô phỏng">
                <header><div><span class="dt-result-eyebrow">KẾT QUẢ PHÂN TÍCH</span><h3 id="dt-result-title">Kết quả mô phỏng</h3></div><button type="button" id="btn-close-dt-results" class="dt-btn-icon" aria-label="Đóng kết quả"><i class="bi bi-x-lg"></i></button></header>
                <div id="dt-results-content" class="dt-results-content"></div>
            </aside>
        </div>
    </div>

    <!-- Scripts -->
`;
