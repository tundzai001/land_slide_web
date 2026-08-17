window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['station-basic'] = String.raw`                        <!-- STEP 1: MÃ TRẠM & TÊN -->
                        <div class="wizard-content active" data-step="1" aria-labelledby="station-basic-heading">
                            <div class="station-step-intro">
                                <div>
                                    <span class="station-step-kicker">Bước 1 / 4</span>
                                    <h6 id="station-basic-heading">Thông tin nhận diện</h6>
                                    <p>Đặt mã duy nhất và tên dễ nhận biết cho trạm quan trắc.</p>
                                </div>
                                <span class="station-required-note"><span aria-hidden="true">*</span> Bắt buộc</span>
                            </div>

                            <div class="row g-4 station-basic-fields">
                                <div class="col-md-6">
                                    <label class="form-label" for="edit-code">Mã trạm <span class="text-danger" aria-hidden="true">*</span></label>
                                    <input type="text" class="form-control" id="edit-code" required autocomplete="off" aria-describedby="edit-code-help" placeholder="Ví dụ: DAP4_2">
                                    <small class="form-text" id="edit-code-help">Mã viết liền, dùng để nhận diện trạm trong hệ thống.</small>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label" for="edit-name">Tên trạm <span class="text-danger" aria-hidden="true">*</span></label>
                                    <input type="text" class="form-control" id="edit-name" required autocomplete="off" aria-describedby="edit-name-help" placeholder="Ví dụ: Đập 4 số 2">
                                    <small class="form-text" id="edit-name-help">Tên hiển thị trên bản đồ, danh sách trạm và báo cáo.</small>
                                </div>
                            </div>

                            <div class="station-options" role="group" aria-labelledby="station-options-heading">
                                <div class="station-options-heading">
                                    <h6 id="station-options-heading">Chế độ vận hành</h6>
                                    <p>Có thể thay đổi lại bất cứ lúc nào.</p>
                                </div>
                                <div class="station-option-grid">
                                    <label class="station-option-card" for="station-alerting-disabled">
                                        <span class="station-option-icon station-option-icon-warning" aria-hidden="true"><i class="bi bi-bell-slash"></i></span>
                                        <span class="station-option-copy">
                                            <strong>Tạm dừng cảnh báo</strong>
                                            <small>Trạm vẫn quan trắc và lưu dữ liệu nhưng không phát cảnh báo tự động.</small>
                                        </span>
                                        <span class="station-switch">
                                            <input type="checkbox" id="station-alerting-disabled" role="switch">
                                            <span class="station-switch-track" aria-hidden="true"></span>
                                        </span>
                                    </label>
                                    <label class="station-option-card" for="station-offline-display-enabled">
                                        <span class="station-option-icon station-option-icon-info" aria-hidden="true"><i class="bi bi-eye"></i></span>
                                        <span class="station-option-copy">
                                            <strong>Giữ hiển thị khi offline</strong>
                                            <small>Marker chuyển màu vàng và tiếp tục hiển thị dữ liệu cuối cùng khi mất kết nối.</small>
                                        </span>
                                        <span class="station-switch">
                                            <input type="checkbox" id="station-offline-display-enabled" role="switch">
                                            <span class="station-switch-track" aria-hidden="true"></span>
                                        </span>
                                    </label>
                                </div>
                            </div>
                        </div>

`;
