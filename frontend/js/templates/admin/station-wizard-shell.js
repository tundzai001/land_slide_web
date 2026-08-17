window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['station-wizard-shell'] = String.raw`    <!-- 3. Station Config Modal - 3 STEPS WIZARD -->
    <div class="modal fade" id="stationConfigModal" tabindex="-1" aria-labelledby="modal-title" aria-hidden="true">
        <div class="modal-dialog modal-xl modal-dialog-centered modal-dialog-scrollable">
            <div class="modal-content">
                <div class="modal-header">
                    <div class="station-modal-heading">
                        <span class="station-modal-icon" aria-hidden="true"><i class="bi bi-broadcast-pin"></i></span>
                        <div>
                            <div class="station-modal-eyebrow">Thiết lập trạm quan trắc</div>
                            <h5 class="modal-title" id="modal-title">Cấu hình Trạm</h5>
                        </div>
                    </div>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Đóng cửa sổ"></button>
                </div>
                <!-- WIZARD STEPS OUTSIDE SCROLLING BODY -->
                <div class="wizard-steps-container">
                    <div class="wizard-steps" id="wizard-steps" role="list" aria-label="Tiến trình cấu hình trạm">
                        <div class="wizard-step active" data-step="1" role="listitem" aria-current="step">
                            <div class="step-circle">1</div>
                            <div class="step-label">Thông tin cơ bản</div>
                        </div>
                        <div class="wizard-step" data-step="2" role="listitem">
                            <div class="step-circle">2</div>
                            <div class="step-label">MQTT & Tọa độ</div>
                        </div>
                        <div class="wizard-step" data-step="3" role="listitem">
                            <div class="step-circle">3</div>
                            <div class="step-label">Ngưỡng cảnh báo</div>
                        </div>
                        <div class="wizard-step" data-step="4" role="listitem">
                            <div class="step-circle">4</div>
                            <div class="step-label">Lưu dữ liệu</div>
                        </div>
                    </div>
                </div>

                <div class="modal-body">

                    <form id="stationConfigForm">
                        <input type="hidden" id="edit-station-id">
                        <input type="hidden" id="edit-project-id">

`;
