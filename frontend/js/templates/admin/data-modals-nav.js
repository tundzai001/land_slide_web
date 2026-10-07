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

    <!-- MODAL TẢI DỮ LIỆU NÂNG CAO -->
    <div class="modal fade" id="exportExcelModal" tabindex="-1" aria-labelledby="exportExcelModalLabel">
        <div class="modal-dialog modal-dialog-centered modal-xl export-dialog">
            <div class="modal-content export-shell">
                <div class="modal-header export-header text-white">
                    <div class="export-title-wrap">
                        <div class="export-header-icon" aria-hidden="true"><i class="bi bi-box-arrow-down"></i></div>
                        <div>
                            <div class="export-eyebrow">DATA EXPORT CENTER</div>
                            <h5 class="modal-title mb-1" id="exportExcelModalLabel">Xuất dữ liệu</h5>
                            <div class="export-header-copy">Chọn phạm vi và dataset. Tác vụ tiếp tục chạy nền khi bạn thu nhỏ cửa sổ.</div>
                        </div>
                    </div>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Thu nhỏ cửa sổ export" title="Thu nhỏ; tác vụ export vẫn tiếp tục"></button>
                </div>

                <div class="modal-body export-body">
                    <div class="export-layout">
                        <section class="export-panel export-scope-panel">
                            <div class="export-field">
                                <label class="form-label" for="export-format">Định dạng trong gói ZIP</label>
                                <select class="form-select" id="export-format"><option value="csv">CSV (.csv)</option><option value="both">CSV + Excel (.xlsx)</option></select>
                            </div>
                            <div class="export-section-title"><span class="export-step">01</span><span class="export-section-copy"><strong>Phạm vi dữ liệu</strong><small>Khoanh vùng dữ liệu cần đóng gói</small></span></div>
                            <div class="export-field">
                                <label class="form-label" for="export-project-select">Dự án</label>
                                <select class="form-select" id="export-project-select" onchange="window.dbManager.onExportProjectChange()">
                                    <option value="all">-- Tất cả Dự án --</option>
                                </select>
                            </div>
                            <div class="export-field">
                                <label class="form-label" for="export-station-select">Trạm quan trắc</label>
                                <select class="form-select" id="export-station-select">
                                    <option value="all">-- Tất cả Trạm --</option>
                                </select>
                            </div>
                            <div class="export-field">
                                <label class="form-label" for="export-cluster-select">Cụm bình sai GNSS</label>
                                <select class="form-select" id="export-cluster-select" disabled>
                                    <option value="all">-- Chọn dự án để lọc cụm --</option>
                                </select>
                            </div>
                            <div class="export-section-title export-section-title-spaced"><span class="export-step">02</span><span class="export-section-copy"><strong>Khoảng thời gian</strong><small>Để trống nếu muốn lấy toàn bộ lịch sử</small></span></div>
                            <div class="export-date-grid">
                                <div class="export-field">
                                    <label class="form-label" for="export-start-date">Từ ngày</label>
                                    <input type="date" class="form-control" id="export-start-date">
                                </div>
                                <div class="export-field">
                                    <label class="form-label" for="export-end-date">Đến ngày</label>
                                    <input type="date" class="form-control" id="export-end-date">
                                </div>
                            </div>
                            <div id="export-scope-summary" class="export-scope-note">Toàn bộ thời gian trong phạm vi đã chọn.</div>
                        </section>

                        <section class="export-panel export-dataset-panel">
                            <div class="export-section-title"><span class="export-step">03</span><span class="export-section-copy"><strong>Dataset cần đóng gói</strong><small>Chọn một hoặc nhiều nhóm dữ liệu</small></span></div>
                            <div class="export-options">
                                <label class="export-dataset" for="export-projects"><input type="checkbox" id="export-projects" value="projects"><span class="export-dataset-icon"><i class="bi bi-diagram-3"></i></span><span class="export-dataset-copy"><strong>Dự án và trạm</strong><small>Cấu hình, tọa độ và trạng thái</small></span><span class="export-check" aria-hidden="true"><i class="bi bi-check2"></i></span></label>
                                <label class="export-dataset" for="export-devices"><input type="checkbox" id="export-devices" value="devices"><span class="export-dataset-icon"><i class="bi bi-cpu"></i></span><span class="export-dataset-copy"><strong>Thiết bị</strong><small>Pi, sensor, topic và loại thiết bị</small></span><span class="export-check" aria-hidden="true"><i class="bi bi-check2"></i></span></label>
                                <div class="export-dataset export-dataset-with-children">
                                    <label class="export-dataset-main" for="export-sensor-data"><input type="checkbox" id="export-sensor-data" value="sensor_data" checked onchange="document.getElementById('export-sensor-types').style.display = this.checked ? 'grid' : 'none'"><span class="export-dataset-icon"><i class="bi bi-activity"></i></span><span class="export-dataset-copy"><strong>Lịch sử cảm biến</strong><small>Dữ liệu các loại cảm biến quan trắc</small></span><span class="export-check" aria-hidden="true"><i class="bi bi-check2"></i></span></label>
                                    <label class="export-dataset-main" for="export-simulations"><input type="checkbox" id="export-simulations" value="simulations"><span class="export-dataset-icon"><i class="bi bi-boxes"></i></span><span class="export-dataset-copy"><strong>Kết quả mô phỏng</strong><small>PDF, XLSX và JSON theo dự án/trạm</small></span><span class="export-check" aria-hidden="true"><i class="bi bi-check2"></i></span></label>
                                    <div id="export-sensor-types" class="export-sensor-types">
                                        ${(window.SensorCatalog || []).filter(sensor => !sensor.legacy).map(sensor => `<label for="sensor-${sensor.key}"><input type="checkbox" id="sensor-${sensor.key}" value="${sensor.key}" checked><span class="export-sensor-check" aria-hidden="true"><i class="bi bi-check2"></i></span><span class="export-sensor-copy"><strong>${sensor.label}</strong><small>${sensor.group}</small></span></label>`).join('')}
                                        <label for="sensor-gnss"><input type="checkbox" id="sensor-gnss" value="gnss" checked><span class="export-sensor-check" aria-hidden="true"><i class="bi bi-check2"></i></span><span class="export-sensor-copy"><strong>GNSS</strong><small>Chuyển vị</small></span></label>
                                        <label for="sensor-imu"><input type="checkbox" id="sensor-imu" value="imu" checked><span class="export-sensor-check" aria-hidden="true"><i class="bi bi-check2"></i></span><span class="export-sensor-copy"><strong>IMU</strong><small>Độ nghiêng</small></span></label>
                                        <label for="sensor-rain"><input type="checkbox" id="sensor-rain" value="rain" checked><span class="export-sensor-check" aria-hidden="true"><i class="bi bi-check2"></i></span><span class="export-sensor-copy"><strong>Mưa</strong><small>Lượng mưa</small></span></label>
                                        <label for="sensor-water"><input type="checkbox" id="sensor-water" value="water" checked><span class="export-sensor-check" aria-hidden="true"><i class="bi bi-check2"></i></span><span class="export-sensor-copy"><strong>Mực nước</strong><small>Mực nước</small></span></label>
                                    </div>
                                </div>
                                <label class="export-dataset export-dataset-featured" for="export-gnss-adjustments"><input type="checkbox" id="export-gnss-adjustments" value="gnss_adjustments" checked><span class="export-dataset-icon"><i class="bi bi-crosshair2"></i></span><span class="export-dataset-copy"><strong>Kết quả bình sai GNSS</strong><small>Theo dự án, cụm, trạm; kèm JSON và báo cáo XLSX</small></span><span class="export-check" aria-hidden="true"><i class="bi bi-check2"></i></span></label>
                                <label class="export-dataset" for="export-alerts"><input type="checkbox" id="export-alerts" value="alerts"><span class="export-dataset-icon"><i class="bi bi-bell"></i></span><span class="export-dataset-copy"><strong>Lịch sử cảnh báo</strong><small>Cấp độ, nội dung và trạng thái xử lý</small></span><span class="export-check" aria-hidden="true"><i class="bi bi-check2"></i></span></label>
                            </div>
                        </section>
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
        #exportExcelModal { --export-ink:#102a24; --export-muted:#637a72; --export-green:#087f5b; --export-line:#dce8e3; --export-canvas:#f4f8f6; }
        #exportExcelModal .export-dialog { max-width:1120px; }
        #exportExcelModal .export-shell { overflow:hidden; border:1px solid #d5e3dd; border-radius:22px; background:#fff; box-shadow:0 28px 90px rgba(15,45,35,.24); }
        #exportExcelModal .export-header { align-items:flex-start; gap:18px; padding:22px 26px; border:0; background:linear-gradient(125deg,#0b332b 0%,#0b6b52 68%,#11946e 100%); }
        #exportExcelModal .export-title-wrap { display:flex; align-items:center; gap:14px; min-width:0; }
        #exportExcelModal .export-header-icon { display:grid; place-items:center; width:44px; height:44px; flex:0 0 44px; border:1px solid rgba(255,255,255,.22); border-radius:13px; color:#d5fff1; background:rgba(255,255,255,.12); font-size:1.2rem; }
        #exportExcelModal .export-header-copy { max-width:650px; color:rgba(232,255,247,.78); font-size:.84rem; line-height:1.45; }
        #exportExcelModal .export-eyebrow { margin-bottom:4px; color:#b8f5dc; font:700 .66rem/1.2 ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.14em; }
        #exportExcelModal .export-body { max-height:min(72vh,760px); overflow-y:auto; padding:20px; background:linear-gradient(145deg,#f7faf8 0%,var(--export-canvas) 100%); }
        #exportExcelModal .export-layout { display:grid; grid-template-columns:minmax(300px,.82fr) minmax(420px,1.18fr); gap:16px; align-items:stretch; }
        #exportExcelModal .export-panel { min-width:0; padding:20px; border:1px solid var(--export-line); border-radius:16px; background:rgba(255,255,255,.94); box-shadow:0 8px 24px rgba(17,61,45,.05); }
        #exportExcelModal .export-section-title { display:flex; align-items:center; gap:10px; margin:0 0 18px; color:var(--export-ink); }
        #exportExcelModal .export-section-title-spaced { margin-top:28px; }
        #exportExcelModal .export-step { display:grid; place-items:center; width:27px; height:27px; flex:0 0 27px; border-radius:8px; color:#fff; background:var(--export-green); font:700 .68rem ui-monospace,SFMono-Regular,Menlo,monospace; }
        #exportExcelModal .export-section-copy { display:flex; flex-direction:column; gap:2px; }
        #exportExcelModal .export-section-copy strong { font-size:.91rem; font-weight:800; letter-spacing:.01em; }
        #exportExcelModal .export-section-copy small { color:var(--export-muted); font-size:.74rem; font-weight:500; line-height:1.35; }
        #exportExcelModal .export-field { margin-bottom:14px; }
        #exportExcelModal .form-label { display:block; margin:0 0 7px; color:#526b62!important; font-size:.72rem; font-weight:800; letter-spacing:.06em; text-transform:uppercase; }
        #exportExcelModal .form-select, #exportExcelModal .form-control { min-height:44px; border:1px solid #cdded6; border-radius:11px; color:var(--export-ink); background:#fff; font-size:.88rem; }
        #exportExcelModal .form-select:focus, #exportExcelModal .form-control:focus { border-color:#3ca47f; box-shadow:0 0 0 3px rgba(8,127,91,.13); }
        #exportExcelModal .export-date-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
        #exportExcelModal .export-scope-note { margin-top:22px; padding:12px 13px; border:1px solid #d7e9e0; border-radius:11px; color:#527067; background:#f2f9f5; font-size:.78rem; line-height:1.45; }
        #exportExcelModal .export-options { display:grid; gap:10px; }
        #exportExcelModal .export-dataset { position:relative; display:grid; grid-template-columns:40px minmax(0,1fr) 24px; align-items:center; gap:12px; min-height:72px; padding:12px 14px; border:1px solid #d9e6e0; border-radius:13px; color:var(--export-ink); background:#fff; cursor:pointer; transition:border-color .18s ease,background-color .18s ease,box-shadow .18s ease; }
        #exportExcelModal .export-dataset:hover { border-color:#56ad8c; box-shadow:0 7px 18px rgba(17,95,71,.08); }
        #exportExcelModal .export-dataset:focus-within { outline:3px solid rgba(8,127,91,.16); outline-offset:2px; }
        #exportExcelModal .export-dataset > input, #exportExcelModal .export-dataset-main > input, #exportExcelModal .export-sensor-types input { position:absolute!important; width:1px!important; height:1px!important; min-width:1px!important; min-height:1px!important; margin:0!important; padding:0!important; overflow:hidden; opacity:0; clip-path:inset(50%); pointer-events:none; }
        #exportExcelModal .export-dataset-icon { display:grid; place-items:center; width:40px; height:40px; border-radius:11px; color:#246c58; background:#edf7f3; font-size:1.05rem; transition:color .18s ease,background-color .18s ease; }
        #exportExcelModal .export-dataset-copy { display:flex; min-width:0; flex-direction:column; gap:4px; line-height:1.2; }
        #exportExcelModal .export-dataset-copy strong { font-size:.91rem; font-weight:800; }
        #exportExcelModal .export-dataset-copy small { overflow:hidden; color:var(--export-muted); font-size:.77rem; line-height:1.4; text-overflow:ellipsis; }
        #exportExcelModal .export-check { box-sizing:border-box; display:grid; place-items:center; width:22px; height:22px; border:1px solid #cbdcd4; border-radius:7px; color:transparent; background:#fff; font-size:.9rem; transition:all .18s ease; }
        #exportExcelModal .export-dataset:has(> input:checked), #exportExcelModal .export-dataset-main:has(> input:checked) { border-color:#52ad89; background:#f7fcf9; box-shadow:inset 3px 0 0 var(--export-green),0 0 0 2px rgba(8,127,91,.05); }
        #exportExcelModal .export-dataset:has(> input:checked) > .export-check, #exportExcelModal .export-dataset-main:has(> input:checked) > .export-check { border-color:var(--export-green); color:#fff; background:var(--export-green); }
        #exportExcelModal .export-dataset:has(> input:checked) > .export-dataset-icon, #exportExcelModal .export-dataset-main:has(> input:checked) > .export-dataset-icon { color:#067653; background:#dcf5e9; }
        #exportExcelModal .export-dataset-featured { border-left:3px solid #75bca1; }
        #exportExcelModal .export-dataset-with-children { display:block; padding:0; overflow:hidden; }
        #exportExcelModal .export-dataset-main { position:relative; display:grid; grid-template-columns:40px minmax(0,1fr) 24px; align-items:center; gap:12px; min-height:72px; padding:12px 14px; cursor:pointer; }
        #exportExcelModal .export-sensor-types { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:0 14px 14px 54px; padding:12px; border:1px solid #dceae4; border-radius:11px; background:#f8fbfa; }
        #exportExcelModal .export-sensor-types label { position:relative; display:grid; grid-template-columns:22px minmax(0,1fr); gap:9px; align-items:center; min-height:48px; padding:7px 9px; border:1px solid #e0ebe6; border-radius:9px; color:#284c40; background:#fff; cursor:pointer; transition:border-color .18s ease,background-color .18s ease; }
        #exportExcelModal .export-sensor-types label:hover { border-color:#91cbb4; }
        #exportExcelModal .export-sensor-types label:has(input:focus-visible) { outline:3px solid rgba(8,127,91,.16); outline-offset:1px; }
        #exportExcelModal .export-sensor-check { box-sizing:border-box; display:grid; place-items:center; width:21px; height:21px; border:1px solid #bfd2c9; border-radius:6px; color:transparent; background:#fff; font-size:.82rem; transition:all .18s ease; }
        #exportExcelModal .export-sensor-copy { display:flex; min-width:0; flex-direction:column; gap:2px; line-height:1.2; }
        #exportExcelModal .export-sensor-copy strong { font-size:.78rem; font-weight:800; }
        #exportExcelModal .export-sensor-copy small { color:#71877f; font-size:.69rem; }
        #exportExcelModal .export-sensor-types label:has(input:checked) { border-color:#a7d8c4; background:#f4fbf7; }
        #exportExcelModal .export-sensor-types label:has(input:checked) .export-sensor-check { border-color:var(--export-green); color:#fff; background:var(--export-green); }
        #exportExcelModal .export-progress-card { margin-top:16px; padding:15px 17px; border:1px solid #b9ddcf; border-radius:14px; background:#fff; box-shadow:0 8px 22px rgba(18,99,73,.08); }
        #exportExcelModal .export-percent { color:var(--export-green); font:800 1.2rem ui-monospace,SFMono-Regular,Menlo,monospace; }
        #exportExcelModal .export-progress-track { height:9px; border-radius:999px; background:#dfeae5; }
        #exportExcelModal .export-progress-track .progress-bar { border-radius:999px; background:linear-gradient(90deg,#087f5b,#43c99a); }
        #exportExcelModal .export-footer { position:sticky; bottom:0; justify-content:flex-end; gap:10px; padding:14px 20px; border-top:1px solid #dce7e1; background:rgba(250,253,251,.96); backdrop-filter:blur(10px); }
        #exportExcelModal #btn-export-start { min-height:42px; padding-inline:18px; border:0; border-radius:10px; background:#087f5b; box-shadow:0 7px 16px rgba(8,127,91,.18); font-weight:750; }
        #exportExcelModal #btn-export-start:hover { background:#056b4c; box-shadow:0 9px 20px rgba(8,127,91,.24); }
        #exportExcelModal #btn-export-cancel { min-height:42px; border-radius:10px; }
        @media (max-width:900px) { #exportExcelModal .export-layout { grid-template-columns:1fr; } }
        @media (max-width:575px) { #exportExcelModal .export-header { padding:18px; } #exportExcelModal .export-body { padding:12px; } #exportExcelModal .export-panel { padding:15px; } #exportExcelModal .export-date-grid, #exportExcelModal .export-sensor-types { grid-template-columns:1fr; } #exportExcelModal .export-sensor-types { margin-left:13px; } #exportExcelModal .export-footer { padding:12px; } #exportExcelModal #btn-export-cancel, #exportExcelModal #btn-export-start { flex:1; } }
        @media (prefers-reduced-motion: reduce) { #exportExcelModal .export-dataset, #exportExcelModal #btn-export-start { transition:none; } }
    </style>
    
    <!-- ============================================
     MODAL XÓA DATABASE (BẢO MẬT CAO)
============================================ -->
    <div class="modal fade" id="clearDatabaseModal" tabindex="-1" data-bs-backdrop="static" data-bs-keyboard="false">
        <div class="modal-dialog modal-dialog-centered clear-db-dialog">
            <div class="modal-content clear-db-shell">
                <div class="modal-header clear-db-header">
                    <div class="clear-db-title-wrap">
                        <span class="clear-db-icon"><i class="bi bi-exclamation-triangle" aria-hidden="true"></i></span>
                        <div>
                            <div class="clear-db-eyebrow">THAO TÁC KHÔNG THỂ HOÀN TÁC</div>
                            <h5 class="modal-title">Xóa dữ liệu hệ thống</h5>
                        </div>
                    </div>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Đóng"></button>
                </div>

                <div class="modal-body clear-db-body">
                    <p class="clear-db-intro">Chọn mức xóa bằng cách nhập chính xác một trong hai lệnh dưới đây.</p>
                    <div class="clear-db-options">
                        <article class="clear-db-option is-data-only">
                            <div class="clear-db-option-top">
                                <code>XOA DATA</code>
                                <span class="clear-db-severity">Giữ cấu hình</span>
                            </div>
                            <p>Xóa lịch sử cảm biến và cảnh báo. Dự án, trạm và thiết bị vẫn được giữ nguyên.</p>
                        </article>
                        <article class="clear-db-option is-factory-reset">
                            <div class="clear-db-option-top">
                                <code>FACTORY RESET</code>
                                <span class="clear-db-severity">Xóa toàn bộ</span>
                            </div>
                            <p>Xóa dự án, trạm, thiết bị và toàn bộ dữ liệu để đưa hệ thống về trạng thái mới cài đặt.</p>
                        </article>
                    </div>

                    <div class="clear-db-confirm-field">
                        <label class="form-label" for="clear-db-confirm-input">Nhập lệnh xác nhận</label>
                        <input type="text" class="form-control"
                            id="clear-db-confirm-input" placeholder="XOA DATA hoặc FACTORY RESET" autocomplete="off"
                            spellcheck="false" aria-describedby="clear-db-helper clear-db-error">
                        <div id="clear-db-helper" class="form-text">Chữ hoa và khoảng trắng phải chính xác.</div>
                    </div>

                    <div id="clear-db-error" class="clear-db-error" role="alert" style="display:none;">
                        <i class="bi bi-x-circle" aria-hidden="true"></i>
                        <span id="clear-db-error-message">Lệnh xác nhận không hợp lệ.</span>
                    </div>
                </div>

                <div class="modal-footer clear-db-footer">
                    <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Hủy bỏ</button>
                    <button type="button" class="btn btn-danger" id="clear-db-submit" onclick="window.dbManager.confirmClearDatabase()" disabled>
                        <i class="bi bi-trash3 me-1" aria-hidden="true"></i> Xác nhận xóa
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
