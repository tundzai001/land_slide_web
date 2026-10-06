window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts.operations = String.raw`
<div class="tab-pane fade" id="tab-operations">
  <header class="ops-page-header"><div><span class="ops-eyebrow">SYSTEM OPERATIONS</span><h4>Vận hành hệ thống</h4><p>Sao lưu, nhật ký và cấu hình tích hợp tại một nơi.</p></div><button class="btn btn-outline-primary" onclick="window.adminManager.loadOperations()"><i class="bi bi-arrow-clockwise me-1" aria-hidden="true"></i>Làm mới</button></header>
  <div id="operations-feedback" role="status" aria-live="polite" tabindex="-1" hidden></div>
  <div class="operations-grid">
    <section class="operations-card" aria-labelledby="backup-heading">
      <div class="operations-card-heading"><i class="bi bi-database-check" aria-hidden="true"></i><div><h5 id="backup-heading">Sao lưu & phục hồi</h5><p>Thu thập MQTT tiếp tục trong lúc sao lưu.</p></div></div>
      <div class="operations-actions"><button class="btn btn-primary" onclick="window.adminManager.operationAction(this, 'backup')">Tạo bản sao lưu</button><button class="btn btn-outline-secondary" onclick="document.getElementById('operations-upload').click()">Tải bản sao lưu lên</button><input type="file" id="operations-upload" accept=".zip" hidden onchange="window.adminManager.uploadOperationBackup(this)"></div>
      <form class="operations-form-row" onsubmit="event.preventDefault(); window.adminManager.operationAction(this.querySelector('button'), 'schedule')">
        <div><label for="operations-frequency">Lịch tự động</label><select id="operations-frequency" class="form-select"><option value="disabled">Tắt</option><option value="daily">Hằng ngày</option><option value="weekly">Hằng tuần</option></select></div>
        <div><label for="operations-next">Bắt đầu lúc</label><input id="operations-next" type="datetime-local" class="form-control"></div><button class="btn btn-outline-primary">Lưu lịch</button>
      </form>
      <p class="operations-note">Phục hồi tạo CSDL riêng để kiểm tra bản sao. Chuyển hệ thống sang bản phục hồi cần quy trình quản trị riêng.</p>
      <div id="operations-job" role="status" aria-live="polite"></div>
      <div id="operations-backups" class="operations-list">Đang tải bản sao lưu…</div>
    </section>
    <section class="operations-card" aria-labelledby="ntp-heading">
      <div class="operations-card-heading"><i class="bi bi-clock-history" aria-hidden="true"></i><div><h5 id="ntp-heading">Kiểm tra thời gian NTP</h5><p>Đo độ lệch đồng hồ máy chủ với nguồn NTP.</p></div></div>
      <form onsubmit="event.preventDefault(); window.adminManager.operationAction(this.querySelector('button'), 'ntp')">
        <label for="operations-ntp-server">Máy chủ NTP</label><input id="operations-ntp-server" class="form-control" required maxlength="253" value="pool.ntp.org">
        <div class="operations-actions"><button class="btn btn-outline-primary">Lưu & kiểm tra</button><button type="button" class="btn btn-outline-secondary" onclick="window.adminManager.operationDownload('/ntp/chrony-config', 'chrony-landslide.conf')">Tải cấu hình chrony</button></div>
      </form>
      <div id="operations-ntp-status" class="operations-note">Chưa kiểm tra.</div>
      <p class="operations-note">Đồng bộ đồng hồ do NTP/chrony của hệ điều hành thực hiện. Phép đo tại đây không thay đổi giờ hệ thống.</p>
    </section>
    <section class="operations-card operations-wide" aria-labelledby="audit-heading">
      <div class="operations-card-heading"><i class="bi bi-journal-text" aria-hidden="true"></i><div><h5 id="audit-heading">Nhật ký vận hành & Audit Log</h5><p>Thao tác, tài khoản, thời gian và thay đổi dữ liệu. Các trường bí mật được che.</p></div></div>
      <form class="operations-log-filters" onsubmit="event.preventDefault(); window.adminManager.operationLogOffset=0; window.adminManager.loadOperationLogs()">
        <div><label for="operations-log-kind">Loại nhật ký</label><select id="operations-log-kind" class="form-select"><option value="audit_log">Audit Log</option><option value="operation_log">Vận hành</option></select></div>
        <div><label for="operations-log-user">Tài khoản</label><input id="operations-log-user" class="form-control" placeholder="Tất cả"></div>
        <div><label for="operations-log-start">Từ thời điểm</label><input id="operations-log-start" type="datetime-local" class="form-control"></div>
        <div><label for="operations-log-end">Đến thời điểm</label><input id="operations-log-end" type="datetime-local" class="form-control"></div>
        <button class="btn btn-outline-primary">Lọc nhật ký</button>
      </form>
      <div class="operations-table-wrap"><table class="table"><thead><tr><th>Thời gian</th><th>Tài khoản / Vai trò</th><th>Hành động</th><th>Kết quả</th><th>Chi tiết</th></tr></thead><tbody id="operations-logs"><tr><td colspan="5">Đang tải nhật ký…</td></tr></tbody></table></div>
      <div class="operations-pagination"><span id="operations-log-count"></span><button id="operations-log-prev" class="btn btn-outline-secondary" onclick="window.adminManager.operationLogPage(-1)">Trước</button><button id="operations-log-next" class="btn btn-outline-secondary" onclick="window.adminManager.operationLogPage(1)">Sau</button></div>
    </section>
    <section class="operations-card operations-wide" aria-labelledby="integration-heading">
      <div class="operations-card-heading"><i class="bi bi-hdd-network" aria-hidden="true"></i><div><h5 id="integration-heading">Giao thức tại gateway hiện trường</h5><p>Thiết bị gửi dữ liệu lên hệ thống qua MQTT. Modbus/OPC UA được đọc tại gateway.</p></div></div>
      <div class="operations-form-row">
        <div><label for="operations-device">Thiết bị MQTT</label><select id="operations-device" class="form-select" onchange="window.adminManager.selectOperationDevice()"><option value="">Đang tải thiết bị…</option></select></div>
        <div><label for="operations-protocol">Nguồn dữ liệu tại hiện trường</label><select id="operations-protocol" class="form-select" onchange="window.adminManager.changeOperationProtocol()"><option value="mqtt">MQTT hiện có</option><option value="modbus_tcp">Modbus TCP qua gateway</option><option value="modbus_rtu">Modbus RTU qua gateway</option><option value="opcua">OPC UA qua gateway</option></select></div>
      </div>
      <div id="operations-profile-fields" hidden>
        <p class="operations-note">Địa chỉ bên dưới thuộc mạng hiện trường. Máy chủ chỉ nhận MQTT. Lưu cấu hình rồi tải và triển khai lên gateway khi cần.</p>
        <label class="operations-enable" for="operations-profile-enabled"><input id="operations-profile-enabled" type="checkbox">Cho phép gateway đọc thiết bị sau khi triển khai</label>
        <label for="operations-profile">Cấu hình đọc và ánh xạ trường dữ liệu (JSON)</label><textarea id="operations-profile" class="form-control operations-code" rows="10" spellcheck="false" aria-describedby="operations-profile-hint"></textarea>
        <p id="operations-profile-hint" class="operations-note">Nước: water_level (m); mưa: rainfall_mm; IMU: roll, pitch, yaw (độ). Địa chỉ thanh ghi Modbus bắt đầu từ 0.</p>
      </div>
      <div class="operations-actions"><button id="operations-save-profile" class="btn btn-primary" onclick="window.adminManager.operationAction(this, 'profile')">Lưu cấu hình</button><button class="btn btn-outline-secondary" onclick="window.adminManager.downloadGatewayProfile()">Tải cấu hình gateway</button></div>
      <details class="operations-guide"><summary>Tài liệu tích hợp MQTT / REST / Modbus / OPC UA</summary><div class="operations-actions"><button class="btn btn-outline-primary" onclick="window.adminManager.showIntegrationGuide()">Đọc tài liệu</button><a class="btn btn-outline-secondary" href="/docs" target="_blank" rel="noopener">OpenAPI</a></div><pre id="operations-guide-content"></pre></details>
    </section>
  </div>
</div>`;
