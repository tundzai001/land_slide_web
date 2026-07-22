window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['data-modals-nav'] = String.raw`    <!-- 4. Modal Velocity Config -->
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
    
    
    
    
    
    
    

    

    

    <!-- MODAL TẢI DỮ LIỆU NÂNG CAO -->
    <div class="modal fade" id="exportExcelModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered modal-xl export-dialog">
            <div class="modal-content export-shell">
                <div class="modal-header export-header text-white">
                    <div>
                        <div class="export-eyebrow">DATABASE ARCHIVE</div>
                        <h5 class="modal-title mb-1"><i class="bi bi-box-arrow-down me-2"></i>Xuất dữ liệu hệ thống</h5>
                        <div class="export-header-copy">Chọn phạm vi, dataset và theo dõi tác vụ chạy nền.</div>
                    </div>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" title="Thu nhỏ; tác vụ export vẫn tiếp tục"></button>
                </div>

                <div class="modal-body export-body">
                    <div class="row g-3">
                        <!-- Cột Trái: Chọn Dự án & Trạm -->
                        <div class="col-lg-5">
                            <section class="export-panel h-100">
                            <h6 class="export-section-title"><span>01</span> Phạm vi dữ liệu</h6>
                            <div class="mb-3">
                                <label class="form-label small text-muted">Dự Án</label>
                                <select class="form-select" id="export-project-select" onchange="window.dbManager.onExportProjectChange()">
                                    <option value="all">-- Tất cả Dự án --</option>
                                </select>
                            </div>
                            <div class="mb-3">
                                <label class="form-label small text-muted">Trạm Quan Trắc</label>
                                <select class="form-select" id="export-station-select">
                                    <option value="all">-- Tất cả Trạm --</option>
                                </select>
                            </div>
                            
                            <h6 class="export-section-title mt-4"><span>02</span> Khoảng thời gian</h6>
                            <div class="row g-2">
                                <div class="col-6">
                                    <label class="form-label small text-muted">Từ Ngày</label>
                                    <input type="date" class="form-control" id="export-start-date">
                                </div>
                                <div class="col-6">
                                    <label class="form-label small text-muted">Đến Ngày</label>
                                    <input type="date" class="form-control" id="export-end-date">
                                </div>
                            </div>
                            <div id="export-scope-summary" class="export-scope-note mt-3">Toàn bộ thời gian trong phạm vi đã chọn.</div>
                            </section>
                        </div>

                        <!-- Cột Phải: Chọn Loại Dữ Liệu -->
                        <div class="col-lg-7">
                            <section class="export-panel h-100">
                            <h6 class="export-section-title"><span>03</span> Dataset cần đóng gói</h6>
                            
                            <div class="export-options">
                                <div class="export-item p-2 mb-2 border rounded d-flex align-items-center position-relative" style="cursor: pointer;">
                                    <input class="form-check-input m-0 me-2" type="checkbox" id="export-projects" value="projects" style="width: 16px; height: 16px; min-width: 16px; flex-shrink: 0; position: relative; z-index: 2; float: none;">
                                    <label class="form-check-label stretched-link mb-0" for="export-projects" style="z-index: 1;">
                                        <strong>Dự án và trạm</strong><small>Cấu hình, tọa độ và trạng thái</small>
                                    </label>
                                </div>
                                
                                <div class="export-item p-2 mb-2 border rounded d-flex align-items-center position-relative" style="cursor: pointer;">
                                    <input class="form-check-input m-0 me-2" type="checkbox" id="export-devices" value="devices" style="width: 16px; height: 16px; min-width: 16px; flex-shrink: 0; position: relative; z-index: 2; float: none;">
                                    <label class="form-check-label stretched-link mb-0" for="export-devices" style="z-index: 1;">
                                        <strong>Thiết bị</strong><small>Pi, sensor, topic và loại thiết bị</small>
                                    </label>
                                </div>

                                <div class="export-item p-2 mb-2 border rounded border-primary bg-light d-flex align-items-center position-relative" style="cursor: pointer;">
                                    <input class="form-check-input m-0 me-2" type="checkbox" id="export-sensor-data" value="sensor_data" checked onchange="document.getElementById('export-sensor-types').style.display = this.checked ? 'grid' : 'none'" style="width: 16px; height: 16px; min-width: 16px; flex-shrink: 0; position: relative; z-index: 2; float: none;">
                                    <label class="form-check-label stretched-link mb-0" for="export-sensor-data" style="z-index: 1;">
                                        <strong>Lịch sử cảm biến</strong><small>GNSS, IMU, mưa và mực nước</small>
                                    </label>
                                </div>

                                <div class="export-item export-item-accent p-2 mb-2 border rounded d-flex align-items-center position-relative" style="cursor: pointer;">
                                    <input class="form-check-input m-0 me-2" type="checkbox" id="export-gnss-adjustments" value="gnss_adjustments" checked>
                                    <label class="form-check-label stretched-link mb-0" for="export-gnss-adjustments">
                                        <strong>Kết quả bình sai GNSS</strong><small>Theo dự án, cụm, trạm; kèm JSON và báo cáo XLSX</small>
                                    </label>
                                </div>
                                
                                <!-- Chi tiết Cảm biến -->
                                <div id="export-sensor-types" class="ps-4 mb-3">
                                    <div class="d-flex align-items-center mb-2">
                                        <input class="form-check-input m-0 me-2" type="checkbox" id="sensor-gnss" value="gnss" checked style="width: 16px; height: 16px; min-width: 16px; flex-shrink: 0; float: none; cursor: pointer;">
                                        <label class="form-check-label small mb-0" for="sensor-gnss" style="cursor: pointer;">GNSS (Chuyển vị)</label>
                                    </div>
                                    <div class="d-flex align-items-center mb-2">
                                        <input class="form-check-input m-0 me-2" type="checkbox" id="sensor-imu" value="imu" checked style="width: 16px; height: 16px; min-width: 16px; flex-shrink: 0; float: none; cursor: pointer;">
                                        <label class="form-check-label small mb-0" for="sensor-imu" style="cursor: pointer;">IMU (Độ nghiêng)</label>
                                    </div>
                                    <div class="d-flex align-items-center mb-2">
                                        <input class="form-check-input m-0 me-2" type="checkbox" id="sensor-rain" value="rain" checked style="width: 16px; height: 16px; min-width: 16px; flex-shrink: 0; float: none; cursor: pointer;">
                                        <label class="form-check-label small mb-0" for="sensor-rain" style="cursor: pointer;">Lượng mưa</label>
                                    </div>
                                    <div class="d-flex align-items-center mb-2">
                                        <input class="form-check-input m-0 me-2" type="checkbox" id="sensor-water" value="water" checked style="width: 16px; height: 16px; min-width: 16px; flex-shrink: 0; float: none; cursor: pointer;">
                                        <label class="form-check-label small mb-0" for="sensor-water" style="cursor: pointer;">Mực nước</label>
                                    </div>
                                </div>

                                <div class="export-item p-2 mb-2 border rounded d-flex align-items-center position-relative" style="cursor: pointer;">
                                    <input class="form-check-input m-0 me-2" type="checkbox" id="export-alerts" value="alerts" style="width: 16px; height: 16px; min-width: 16px; flex-shrink: 0; position: relative; z-index: 2; float: none;">
                                    <label class="form-check-label stretched-link mb-0" for="export-alerts" style="z-index: 1;">
                                        <strong>Lịch sử cảnh báo</strong><small>Cấp độ, nội dung và trạng thái xử lý</small>
                                    </label>
                                </div>
                            </div>
                            </section>
                        </div>
                    </div>
                    
                    <!-- Vùng hiển thị Tiến trình (ẩn mặc định) -->
                    <div id="export-progress-container" class="export-progress-card mt-3" style="display: none;">
                        <div class="d-flex justify-content-between align-items-start gap-3 mb-2">
                            <div><div class="export-eyebrow text-success">BACKGROUND TASK</div><h6 class="mb-0" id="export-status-text">Đang chuẩn bị dữ liệu...</h6></div>
                            <div id="export-progress-percent" class="export-percent">0%</div>
                        </div>
                        <div class="progress export-progress-track">
                            <div id="export-progress-bar" class="progress-bar progress-bar-striped progress-bar-animated" role="progressbar" style="width: 0%;"></div>
                        </div>
                        <small class="text-muted mt-2 d-block" id="export-progress-detail">Khởi tạo tác vụ chạy nền...</small>
                    </div>

                </div>

                <div class="modal-footer export-footer">
                    <button type="button" class="btn btn-outline-secondary" id="btn-export-cancel" data-bs-dismiss="modal">
                        <i class="bi bi-dash-circle me-1"></i> Thu nhỏ
                    </button>
                    <button type="button" class="btn btn-success" id="btn-export-start" onclick="window.dbManager.confirmExportExcel()">
                        <i class="bi bi-play-fill me-1"></i> Bắt đầu export
                    </button>
                </div>
            </div>
        </div>
    </div>
    
    <style>
        #exportExcelModal { --export-ink:#17332c; --export-green:#0d8f68; --export-line:#d9e5df; }
        #exportExcelModal .export-dialog { max-width: 980px; }
        #exportExcelModal .export-shell { border:0; border-radius:18px; overflow:hidden; box-shadow:0 26px 80px rgba(17,47,38,.28); }
        #exportExcelModal .export-header { padding:18px 22px; border:0; background:linear-gradient(120deg,#0b3b32 0%,#0d6b53 58%,#12906c 100%); }
        #exportExcelModal .export-header-copy { color:rgba(232,255,247,.72); font-size:.78rem; }
        #exportExcelModal .export-eyebrow { font:700 .62rem/1.2 monospace; letter-spacing:.16em; opacity:.76; }
        #exportExcelModal .export-body { padding:18px; background:linear-gradient(145deg,#f4f8f6,#edf4f0); }
        #exportExcelModal .export-panel { padding:16px; border:1px solid var(--export-line); border-radius:14px; background:rgba(255,255,255,.9); }
        #exportExcelModal .export-section-title { display:flex; align-items:center; gap:8px; margin-bottom:12px; color:var(--export-ink); font-size:.82rem; font-weight:750; text-transform:uppercase; letter-spacing:.04em; }
        #exportExcelModal .export-section-title span { display:grid; place-items:center; width:24px; height:24px; border-radius:7px; color:#fff; background:var(--export-green); font:700 .66rem monospace; }
        #exportExcelModal .form-label { margin-bottom:5px; font-size:.72rem; font-weight:700; color:#557168!important; text-transform:uppercase; letter-spacing:.04em; }
        #exportExcelModal .form-select, #exportExcelModal .form-control { min-height:38px; border-color:#ceddd6; border-radius:9px; font-size:.82rem; }
        #exportExcelModal .export-item { min-height:48px; border-color:#dce8e2!important; background:#fff; transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease; }
        #exportExcelModal .export-item:hover { transform:translateY(-1px); border-color:#41a786!important; box-shadow:0 7px 18px rgba(17,95,71,.08); }
        #exportExcelModal .export-item-accent { background:linear-gradient(100deg,#edfdf6,#f8fffc); border-color:#8fd6bc!important; }
        #exportExcelModal .export-item label { display:flex; flex-direction:column; line-height:1.15; color:#203b33; }
        #exportExcelModal .export-item label strong { font-size:.8rem; }
        #exportExcelModal .export-item label small { margin-top:4px; color:#789087; font-size:.68rem; }
        #exportExcelModal #export-sensor-types { display:grid; grid-template-columns:1fr 1fr; gap:3px 12px; padding:8px 10px!important; margin:0 0 8px 26px!important; border-left:2px solid #b6ddce; background:#f8fbf9; border-radius:0 8px 8px 0; }
        #exportExcelModal #export-sensor-types>div { margin:0!important; }
        #exportExcelModal .export-scope-note { padding:9px 11px; border-radius:9px; background:#edf5f1; color:#597269; font-size:.72rem; }
        #exportExcelModal .export-progress-card { padding:14px 16px; border:1px solid #b9ddcf; border-radius:13px; background:#fff; box-shadow:0 8px 22px rgba(18,99,73,.08); }
        #exportExcelModal .export-percent { color:var(--export-green); font:800 1.25rem monospace; }
        #exportExcelModal .export-progress-track { height:9px; border-radius:999px; background:#dfeae5; }
        #exportExcelModal .export-progress-track .progress-bar { border-radius:999px; background:linear-gradient(90deg,#0d8f68,#42c99b); }
        #exportExcelModal .export-footer { padding:12px 18px; border-color:#dce7e1; background:#f8fbf9; }
        @media (max-width:767px) { #exportExcelModal .export-body{padding:12px} #exportExcelModal #export-sensor-types{grid-template-columns:1fr} }
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
`;
