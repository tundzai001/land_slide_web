window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['station-storage'] = String.raw`                <!-- STEP 4: LƯU DỮ LIỆU -->
                <div class="wizard-content" data-step="4" aria-labelledby="station-storage-heading">
                    <div class="station-step-intro">
                        <div>
                            <span class="station-step-kicker">Bước 4 / 4</span>
                            <h6 id="station-storage-heading">Lưu dữ liệu &amp; xác nhận</h6>
                            <p>Chọn chu kỳ ghi phù hợp rồi rà soát cấu hình trước khi hoàn tất.</p>
                        </div>
                        <span class="station-step-status station-step-status-success"><i class="bi bi-check2-circle" aria-hidden="true"></i> Sẵn sàng lưu</span>
                    </div>

                    <section class="config-section station-storage-panel mb-4" aria-labelledby="station-storage-cycle-title">
                        <div class="section-header">
                            <span class="station-section-icon station-section-icon-success"><i class="bi bi-database-check" aria-hidden="true"></i></span>
                            <div>
                                <h5 id="station-storage-cycle-title">Chu kỳ lưu vào cơ sở dữ liệu</h5>
                                <p>Thiết lập riêng cho từng cảm biến của trạm</p>
                            </div>
                            <span class="station-section-badge">Theo trạm</span>
                        </div>
                        <div class="sensor-config-body">
                            <div class="station-inline-note">
                                <i class="bi bi-info-circle" aria-hidden="true"></i>
                                <span>Để trống để dùng chu kỳ mặc định của hệ thống. Giá trị tối thiểu là 10 giây.</span>
                            </div>
                            <div class="station-storage-grid">
                                <label class="station-storage-card" for="cfg-station-save-gnss">
                                    <span class="station-storage-card-title"><i class="bi bi-broadcast text-success" aria-hidden="true"></i> GNSS</span>
                                    <span class="input-group">
                                        <input type="number" class="form-control" id="cfg-station-save-gnss" placeholder="Mặc định hệ thống" min="10" inputmode="numeric">
                                        <span class="input-group-text">giây</span>
                                    </span>
                                    <small>Ví dụ: 86.400 giây = 1 ngày</small>
                                </label>
                                <label class="station-storage-card" for="cfg-station-save-rain">
                                    <span class="station-storage-card-title"><i class="bi bi-cloud-rain text-info" aria-hidden="true"></i> Cảm biến mưa</span>
                                    <span class="input-group">
                                        <input type="number" class="form-control" id="cfg-station-save-rain" placeholder="Mặc định hệ thống" min="10" inputmode="numeric">
                                        <span class="input-group-text">giây</span>
                                    </span>
                                    <small>Ví dụ: 3.600 giây = 1 giờ</small>
                                </label>
                                <label class="station-storage-card" for="cfg-station-save-water">
                                    <span class="station-storage-card-title"><i class="bi bi-water text-primary" aria-hidden="true"></i> Mực nước</span>
                                    <span class="input-group">
                                        <input type="number" class="form-control" id="cfg-station-save-water" placeholder="Mặc định hệ thống" min="10" inputmode="numeric">
                                        <span class="input-group-text">giây</span>
                                    </span>
                                    <small>Ví dụ: 3.600 giây = 1 giờ</small>
                                </label>
                                <label class="station-storage-card" for="cfg-station-save-imu">
                                    <span class="station-storage-card-title"><i class="bi bi-arrow-repeat text-warning" aria-hidden="true"></i> IMU</span>
                                    <span class="input-group">
                                        <input type="number" class="form-control" id="cfg-station-save-imu" placeholder="Mặc định hệ thống" min="10" inputmode="numeric">
                                        <span class="input-group-text">giây</span>
                                    </span>
                                    <small>Ví dụ: 2.592.000 giây = 30 ngày</small>
                                </label>
                            </div>
                        </div>
                    </section>

                    <section class="config-section station-review-panel mb-4" aria-labelledby="station-review-title">
                        <div class="section-header">
                            <span class="station-section-icon"><i class="bi bi-clipboard2-check" aria-hidden="true"></i></span>
                            <div>
                                <h5 id="station-review-title">Rà soát cấu hình</h5>
                                <p>Thông tin cuối cùng trước khi áp dụng cho trạm</p>
                            </div>
                        </div>
                        <div class="sensor-config-body">
                            <div id="station-config-summary" class="station-config-summary" aria-live="polite">
                                <p><i class="bi bi-info-circle" aria-hidden="true"></i> Nhấn <strong>“Lưu cấu hình”</strong> để hoàn tất thiết lập trạm.</p>
                            </div>
                        </div>
                    </section>
                </div>

                </form>
            </div>
            <div class="modal-footer station-wizard-footer">
                <div class="station-footer-meta" aria-live="polite">
                    <i class="bi bi-shield-check" aria-hidden="true"></i>
                    <span>Dữ liệu chỉ được lưu khi hoàn tất bước 4</span>
                </div>
                <div class="d-flex gap-2 station-footer-actions">
                    <button type="button" class="btn btn-secondary" id="btn-wizard-back" style="display: none;"
                        onclick="if (window.adminManager) { window.adminManager.wizardPrev(); } return false;">
                        <i class="bi bi-arrow-left" aria-hidden="true"></i> Quay lại
                    </button>
                    <button type="button" class="btn btn-primary" id="btn-wizard-next"
                        onclick="if (window.adminManager) { window.adminManager.wizardNext(); } return false;">
                        Tiếp theo <i class="bi bi-arrow-right" aria-hidden="true"></i>
                    </button>
                    <button type="button" class="btn btn-success" id="btn-wizard-save" style="display: none;"
                        onclick="if (window.adminManager) { window.adminManager.saveStation(); } return false;">
                        <i class="bi bi-check2-circle" aria-hidden="true"></i> Lưu cấu hình
                    </button>
                </div>
            </div>
        </div>
    </div>
    </div>

`;
