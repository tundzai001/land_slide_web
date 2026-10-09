window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['pi-devices'] = String.raw`
            <!-- TAB: PI DEVICES -->
            <div class="tab-pane fade" id="tab-pi">
                <header class="ops-page-header">
                    <div>
                        <span class="ops-eyebrow">Thiết bị hiện trường</span>
                        <h4><i class="bi bi-cpu me-2" aria-hidden="true"></i>Quản lý thiết bị Pi</h4>
                        <p>Theo dõi kết nối, phạm vi gán trạm và thao tác thiết bị tại một nơi.</p>
                    </div>
                    <div class="ops-header-actions">
                        <button class="btn btn-outline-primary" id="pi-sync-button" onclick="window.adminManager.loadPiDevices()"><i class="bi bi-arrow-clockwise me-1" aria-hidden="true"></i>Đồng bộ</button>
                        <button class="btn btn-primary" id="pi-select-toggle" onclick="window.adminManager.togglePiSelectMode()"><i class="bi bi-check2-square me-1" aria-hidden="true"></i>Chọn thiết bị</button>
                    </div>
                </header>

                <section class="ops-kpi-grid pi-kpi-grid" id="pi-summary-cards" aria-label="Tổng quan thiết bị Pi">
                    <article class="ops-kpi is-amber"><span>Chờ kích hoạt</span><strong id="pi-pending-count">0</strong><small id="pi-pending-desc">Không có thiết bị chờ</small><i class="bi bi-hourglass-split" aria-hidden="true"></i></article>
                    <article class="ops-kpi is-green"><span>Đã kích hoạt · chưa gán</span><strong id="pi-activated-count">0</strong><small>Sẵn sàng gán vào trạm</small><i class="bi bi-check2-circle" aria-hidden="true"></i></article>
                    <article class="ops-kpi is-blue"><span>Đã gán vào trạm</span><strong id="pi-assigned-count">0</strong><small>Đang thuộc hệ thống quan trắc</small><i class="bi bi-broadcast-pin" aria-hidden="true"></i></article>
                    <article class="ops-kpi is-slate"><span>Đang trực tuyến</span><strong id="pi-online-count">0</strong><small>Dựa trên heartbeat 120 giây</small><i class="bi bi-wifi" aria-hidden="true"></i></article>
                </section>

                <section class="pi-console" aria-label="Danh sách thiết bị Pi">
                    <div class="pi-toolbar">
                        <label class="ops-search" for="pi-search-input"><i class="bi bi-search" aria-hidden="true"></i><input type="search" id="pi-search-input" placeholder="Tìm tên, serial hoặc trạm…" oninput="window.adminManager._filterPiGrid()"></label>
                        <label class="pi-filter-field" for="pi-status-filter"><span>Trạng thái</span><select class="form-select" id="pi-status-filter" onchange="window.adminManager._filterPiGrid()"><option value="all">Tất cả</option><option value="online">Online</option><option value="offline">Offline</option><option value="pending">Chờ kích hoạt</option><option value="activated">Chưa gán trạm</option><option value="assigned">Đã gán trạm</option><option value="locked">Đã khóa</option></select></label>
                    </div>
                    <div class="pi-list-head" aria-hidden="true"><span>Thiết bị</span><span>Serial</span><span>Trạng thái</span><span>Kết nối</span></div>
                    <div id="pi-grid-body" class="pi-device-list" aria-live="polite"><div class="ops-loading"><span class="spinner-border spinner-border-sm" aria-hidden="true"></span><span>Đang tải thiết bị…</span></div></div>
                    <footer class="pi-console-footer"><span id="pi-grid-info">0 thiết bị</span><span><i class="bi bi-circle-fill is-online" aria-hidden="true"></i> Online <i class="bi bi-circle-fill is-offline ms-3" aria-hidden="true"></i> Offline</span></footer>
                </section>

                <span id="pi-pending-badge" hidden>0</span><span id="pi-activated-badge" hidden>0</span><span id="pi-assigned-badge" hidden>0</span>
                <div id="pi-pending-list" hidden></div><div id="pi-activated-list" hidden></div><div id="pi-assigned-list" hidden></div>
            </div>`;
