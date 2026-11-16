window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['station-storage'] = `                <!-- STEP 4: LƯU DỮ LIỆU -->
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
                            <div class="station-options mb-3" role="group" aria-labelledby="station-processing-options-heading">
                                <div class="station-options-heading">
                                    <h6 id="station-processing-options-heading">Lưu log xử lý</h6>
                                    <p>Cấu hình riêng cho trạm này; không ảnh hưởng đến xử lý realtime.</p>
                                </div>
                                <label class="station-option-card" for="cfg-station-processing-storage-enabled">
                                    <span class="station-option-icon station-option-icon-info" aria-hidden="true"><i class="bi bi-cpu"></i></span>
                                    <span class="station-option-copy">
                                        <strong>Lưu trạng thái xử lý GNSS</strong>
                                        <small>Lưu các bản ghi <code>gnss_anomaly</code> và <code>gnss_audit</code>. Tắt để giảm phình cơ sở dữ liệu; trạm vẫn xử lý, cảnh báo và cập nhật realtime.</small>
                                    </span>
                                    <span class="station-switch">
                                        <input type="checkbox" id="cfg-station-processing-storage-enabled" role="switch" checked>
                                        <span class="station-switch-track" aria-hidden="true"></span>
                                    </span>
                                </label>
                            </div>
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
                                    <span class="station-storage-card-title"><i class="bi bi-water text-primary" aria-hidden="true"></i> Mực nước ngầm / Áp lực nước lỗ rỗng</span>
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

                    <section class="config-section mb-4" aria-labelledby="station-simulation-profile-title">
                        <div class="section-header"><span class="station-section-icon"><i class="bi bi-boxes" aria-hidden="true"></i></span><div><h5 id="station-simulation-profile-title">Hồ sơ mô phỏng sườn dốc</h5><p>Thông số địa chất dùng khi chạy mô phỏng từ dữ liệu trạm</p></div><span class="station-section-badge">Engineering</span></div>
                        <div class="sensor-config-body">
                            <div class="station-inline-note"><i class="bi bi-info-circle"></i><span>Đây là hồ sơ giả định của trạm. Cảm biến chỉ cập nhật mưa, mực nước và gia tốc; không tự suy đoán địa chất.</span></div>
                            <div class="station-storage-grid simulation-profile-grid">
                                <label class="station-storage-card"><span class="station-storage-card-title">Lực dính c′</span><span class="input-group"><input type="number" class="form-control" id="sim-profile-cohesion" value="15" min="0" max="200" step="0.1"><span class="input-group-text">kPa</span></span></label>
                                <label class="station-storage-card"><span class="station-storage-card-title">Góc ma sát φ′</span><span class="input-group"><input type="number" class="form-control" id="sim-profile-friction" value="30" min="1" max="60" step="0.1"><span class="input-group-text">°</span></span></label>
                                <label class="station-storage-card"><span class="station-storage-card-title">Trọng lượng riêng γ</span><span class="input-group"><input type="number" class="form-control" id="sim-profile-unit-weight" value="18" min="5" max="30" step="0.1"><span class="input-group-text">kN/m³</span></span></label>
                                <label class="station-storage-card"><span class="station-storage-card-title">Chiều sâu mặt trượt</span><span class="input-group"><input type="number" class="form-control" id="sim-profile-slip-depth" value="5" min="0.5" max="50" step="0.1"><span class="input-group-text">m</span></span></label>
                                <label class="station-storage-card"><span class="station-storage-card-title">Góc dốc</span><span class="input-group"><input type="number" class="form-control" id="sim-profile-slope" value="25" min="1" max="70" step="0.1"><span class="input-group-text">°</span></span></label>
                                <label class="station-storage-card"><span class="station-storage-card-title">Hệ số thấm Kₛ</span><span class="input-group"><input type="number" class="form-control" id="sim-profile-ks" value="0.000015" min="0.000000001" max="0.01" step="0.000001"><span class="input-group-text">m/s</span></span></label>
                                <label class="station-storage-card"><span class="station-storage-card-title">Độ rỗng</span><input type="number" class="form-control" id="sim-profile-porosity" value="0.25" min="0.05" max="0.7" step="0.01"></label>
                                <label class="station-storage-card"><span class="station-storage-card-title">ru nền</span><input type="number" class="form-control" id="sim-profile-base-ru" value="0" min="0" max="0.6" step="0.01"></label>
                                <label class="station-storage-card"><span class="station-storage-card-title">Mực nước khô</span><span class="input-group"><input type="number" class="form-control" id="sim-profile-water-dry" value="0" step="0.01"><span class="input-group-text">m</span></span></label>
                                <label class="station-storage-card"><span class="station-storage-card-title">Mực nước bão hòa</span><span class="input-group"><input type="number" class="form-control" id="sim-profile-water-saturated" value="1" step="0.01"><span class="input-group-text">m</span></span></label>
                                <label class="station-storage-card"><span class="station-storage-card-title">Nhà trong mô hình</span><input type="number" class="form-control" id="sim-profile-houses" value="40" min="0" max="2000"></label>
                                <label class="station-storage-card"><span class="station-storage-card-title">Cây trong mô hình</span><input type="number" class="form-control" id="sim-profile-trees" value="300" min="0" max="10000"></label>
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
                    <span>Khóa lại gốc lưu sau khi thu mẫu; cấu hình khác lưu ở bước 4</span>
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
