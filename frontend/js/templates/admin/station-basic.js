window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['station-basic'] = String.raw`                        <!-- STEP 1: MÃ TRẠM & TÊN -->
                        <div class="wizard-content active" data-step="1">
                            <div class="row g-3">
                                <div class="col-md-6">
                                    <label class="form-label">Mã trạm <span class="text-danger">*</span></label>
                                    <input type="text" class="form-control" id="edit-code" required>
                                    <small class="text-muted">VD: ST01, ST02...</small>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Tên trạm <span class="text-danger">*</span></label>
                                    <input type="text" class="form-control" id="edit-name" required>
                                    <div class="alert alert-warning mt-3 mb-0">
                                        <div class="form-check form-switch mb-2">
                                            <input class="form-check-input" type="checkbox" id="station-alerting-disabled">
                                            <label class="form-check-label fw-semibold" for="station-alerting-disabled">
                                                Không cảnh báo
                                            </label>
                                            <small class="d-block text-muted">
                                                Bật tùy chọn này thì trạm vẫn quan trắc và lưu dữ liệu, nhưng không phát cảnh báo tự động.
                                            </small>
                                        </div>
                                        <div class="form-check form-switch">
                                            <input class="form-check-input" type="checkbox" id="station-offline-display-enabled">
                                            <label class="form-check-label fw-semibold" for="station-offline-display-enabled">
                                                Hiển thị offline giám sát
                                            </label>
                                            <small class="d-block text-muted">
                                                Khi trạm mất kết nối, marker chuyển màu vàng và vẫn hiển thị dữ liệu cuối cùng thay vì trạng thái OFFLINE đỏ/xám.
                                            </small>
                                        </div>
                                    </div>
                                    <small class="text-muted">VD: Trạm Đà Nẵng</small>
                                </div>
                            </div>
                        </div>

`;
