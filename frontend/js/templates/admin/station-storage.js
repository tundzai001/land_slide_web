window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['station-storage'] = String.raw`                <!-- STEP 4: LƯU DỮ LIỆU -->
                <div class="wizard-content" data-step="4">
                    <div class="config-section mb-4">
                        <div class="section-header">
                            <i class="bi bi-database-fill-gear" style="color:#10b981"></i>
                            <h5>Chu kỳ lưu dữ liệu vào Database</h5>
                            <span class="badge ms-auto" style="background:#10b981">Per-Station</span>
                        </div>
                        <div class="sensor-config-body">
                            <p class="text-muted small mb-3">
                                <i class="bi bi-info-circle me-1"></i>
                                Thiết lập chu kỳ ghi dữ liệu cho từng loại sensor của trạm này.
                                Nếu để trống, sẽ sử dụng giá trị mặc định từ cấu hình Hệ thống.
                            </p>
                            <div class="row g-3">
                                <div class="col-md-6">
                                    <label class="form-label"><i class="bi bi-broadcast text-success me-1"></i> GNSS (giây)</label>
                                    <input type="number" class="form-control" id="cfg-station-save-gnss" placeholder="Mặc định hệ thống" min="10">
                                    <small class="text-muted">VD: 86400 = 1 ngày, 3600 = 1 giờ</small>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label"><i class="bi bi-cloud-rain text-info me-1"></i> Mưa (giây)</label>
                                    <input type="number" class="form-control" id="cfg-station-save-rain" placeholder="Mặc định hệ thống" min="10">
                                    <small class="text-muted">VD: 3600 = 1 giờ</small>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label"><i class="bi bi-water text-primary me-1"></i> Nước (giây)</label>
                                    <input type="number" class="form-control" id="cfg-station-save-water" placeholder="Mặc định hệ thống" min="10">
                                    <small class="text-muted">VD: 3600 = 1 giờ</small>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label"><i class="bi bi-arrow-repeat text-warning me-1"></i> IMU (giây)</label>
                                    <input type="number" class="form-control" id="cfg-station-save-imu" placeholder="Mặc định hệ thống" min="10">
                                    <small class="text-muted">VD: 2592000 = 30 ngày</small>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- TỔNG KẾT CẤU HÌNH TRƯỚC KHI LƯU -->
                    <div class="config-section mb-4">
                        <div class="section-header">
                            <i class="bi bi-check2-all" style="color:#0ea5e9"></i>
                            <h5>Xác nhận cấu hình</h5>
                        </div>
                        <div class="sensor-config-body">
                            <div id="station-config-summary" class="text-muted small">
                                <p><i class="bi bi-info-circle me-1"></i> Nhấn <strong>"Lưu cấu hình"</strong> để hoàn tất thiết lập trạm.</p>
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

`;
