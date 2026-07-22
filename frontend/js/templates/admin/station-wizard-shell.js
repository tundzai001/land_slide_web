window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['station-wizard-shell'] = String.raw`    <!-- 3. Station Config Modal - 3 STEPS WIZARD -->
    <div class="modal fade" id="stationConfigModal" tabindex="-1">
        <div class="modal-dialog modal-lg modal-dialog-scrollable">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="modal-title">Cấu hình Trạm</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <!-- WIZARD STEPS OUTSIDE SCROLLING BODY -->
                <div class="wizard-steps-container">
                    <div class="wizard-steps" id="wizard-steps" style="margin-bottom: 24px;">
                        <div class="wizard-step active" data-step="1">
                            <div class="step-circle">1</div>
                            <div class="step-label">Thông tin cơ bản</div>
                        </div>
                        <div class="wizard-step" data-step="2">
                            <div class="step-circle">2</div>
                            <div class="step-label">MQTT & Tọa độ</div>
                        </div>
                        <div class="wizard-step" data-step="3">
                            <div class="step-circle">3</div>
                            <div class="step-label">Ngưỡng cảnh báo</div>
                        </div>
                        <div class="wizard-step" data-step="4">
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
