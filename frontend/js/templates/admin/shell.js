window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['shell'] = String.raw`
<!-- SECURITY: Block page render until auth verified -->
    



    <!-- Sidebar -->
    <div class="admin-sidebar">
        <div class="sidebar-brand" style="cursor:pointer" onclick="window.location.href='/?view=map'"
            title="Về trang bản đồ">
            <h4><i class="bi bi-map me-2"></i>Map</h4>
            <small class="text-muted">Bản đồ</small>
        </div>

        <nav>
            <div class="nav-item">
                <a class="nav-link active" href="#" data-tab="tab-users"
                    onclick="window.adminManager?.switchTab('tab-users', this)">
                    <i class="bi bi-people"></i>
                    <span>Người dùng</span>
                </a>
            </div>
            <div class="nav-item">
                <a class="nav-link" href="#" data-tab="tab-projects"
                    onclick="window.adminManager?.switchTab('tab-projects', this)">
                    <i class="bi bi-folder"></i>
                    <span>Dự án</span>
                </a>
            </div>
            <div class="nav-item">
                <a class="nav-link" href="#" data-tab="tab-database"
                    onclick="window.adminManager?.switchTab('tab-database', this)">
                    <i class="bi bi-database"></i>
                    <span>Database</span>
                </a>
            </div>
            <div class="nav-item">
                <a class="nav-link" href="#" data-tab="tab-pi"
                    onclick="window.adminManager?.switchTab('tab-pi', this); window.adminManager?.loadPiDevices()">
                    <i class="bi bi-cpu-fill" style="color:#0ea5e9"></i>
                    <span>Pi Devices</span>
                </a>
            </div>
            <div class="nav-item">
                <a class="nav-link" href="#" data-tab="tab-rescue"
                    onclick="window.adminManager?.switchTab('tab-rescue', this); window.adminManager?.loadRescueRequests()">
                    <i class="bi bi-life-preserver" style="color:#ef4444"></i>
                    <span>Cứu hộ</span>
                </a>
            </div>
            <div class="nav-item mt-5">
                <a class="nav-link text-danger" href="#" id="logout-btn">
                    <i class="bi bi-box-arrow-left"></i>
                    <span>Đăng xuất</span>
                </a>
            </div>
        </nav>
    </div>

    <!-- Top Navbar -->
    <nav class="admin-navbar">
        <div class="d-flex justify-content-between align-items-center w-100">
            <div class="navbar-left">
                <h5 class="mb-0 fw-bold" style="color:var(--text-primary)">
                    <i class="bi bi-grid-1x2 me-2" style="color:var(--accent-primary)"></i>
                    Trung tâm quản trị
                </h5>
            </div>
            <div class="navbar-right d-flex align-items-center gap-3">
                <div class="user-profile d-flex align-items-center gap-2">
                    <div class="avatar-circle">A</div>
                    <span class="d-none d-sm-block">Administrator</span>
                </div>
            </div>
        </div>
    </nav>

    <!-- Main Content -->
    <div class="admin-main">

        <!-- Tab Content (no horizontal tabs â€” sidebar handles switching) -->
        <div class="tab-content" id="admin-tab-content">

            <!-- TAB 1: USERS -->
            <div class="tab-pane fade show active" id="tab-users">
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <h4>Danh sách Người dùng</h4>
                    <button class="btn btn-outline-primary" data-bs-toggle="modal" data-bs-target="#addUserModal">
                        <i class="bi bi-person-plus me-2"></i>Thêm user
                    </button>
                </div>

                <div class="custom-table">
                    <table class="table table-hover mb-0">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Tài khoản</th>
                                <th>Họ tên</th>
                                <th>Vai trò</th>
                                <th>Trạng thái</th>
                                <th>Thao tác</th>
                            </tr>
                        </thead>
                        <tbody id="user-table-body">
                            <tr>
                                <td colspan="6" class="text-center py-4">
                                    <div class="spinner-border text-primary"></div>
                                    <p class="mt-2 text-muted">Đang tải...</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- TAB 2: PROJECTS -->
            <div class="tab-pane fade" id="tab-projects">
                <nav aria-label="breadcrumb" class="mb-3">
                    <ol class="breadcrumb" id="project-breadcrumb">
                        <li class="breadcrumb-item active">Dự án</li>
                    </ol>
                </nav>

                <div class="d-flex justify-content-between align-items-center mb-4">
                    <div class="d-flex gap-2 align-items-center">
                        <button class="btn btn-outline-secondary" id="btn-back-nav" style="display: none;"
                            onclick="window.adminManager.navigateBack()">
                            <i class="bi bi-arrow-left me-1"></i> Quay lại
                        </button>
                        <h4 id="current-view-title" class="mb-0">Danh sách Dự án</h4>
                    </div>
                    <div id="action-buttons-container">
                        <button class="btn btn-gradient" onclick="window.adminManager.openCreateProjectModal()">
                            <i class="bi bi-plus-circle me-2"></i>Tạo Dự án
                        </button>
                    </div>
                </div>

                <div id="projects-content-area">
                    <div class="text-center py-5">
                        <div class="spinner-border text-primary"></div>
                        <p class="text-muted mt-2">Đang tải...</p>
                    </div>
                </div>
            </div>

            <!-- TAB 3: DATABASE -->
            <div class="tab-pane fade" id="tab-database">
                <header class="ops-page-header">
                    <div><span class="ops-eyebrow">DATA OPERATIONS</span><h4><i class="bi bi-database me-2"></i>Data Explorer</h4><p>Kiểm tra cấu hình, dữ liệu cảm biến và cảnh báo trong cùng một workspace.</p></div>
                    <div class="ops-header-actions">
                        <button class="btn btn-outline-primary" onclick="window.dbManager.loadAllData()"><i class="bi bi-arrow-clockwise me-1"></i>Làm mới</button>
                        <button class="btn btn-success" onclick="window.dbManager.exportToExcel()"><i class="bi bi-box-arrow-down me-1"></i>Xuất dữ liệu</button>
                        <button class="btn btn-outline-danger" onclick="window.dbManager.clearDatabase()"><i class="bi bi-trash3 me-1"></i>Xóa dữ liệu</button>
                    </div>
                </header>

                <section class="ops-kpi-grid" aria-label="Tổng quan database">
                    <article class="ops-kpi is-blue"><span>Trạm</span><strong id="stat-stations">--</strong><i class="bi bi-broadcast-pin" aria-hidden="true"></i></article>
                    <article class="ops-kpi is-green"><span>Thiết bị</span><strong id="stat-devices">--</strong><i class="bi bi-cpu" aria-hidden="true"></i></article>
                    <article class="ops-kpi is-cyan"><span>Dữ liệu cảm biến</span><strong id="stat-data">--</strong><i class="bi bi-activity" aria-hidden="true"></i></article>
                    <article class="ops-kpi is-amber"><span>Cảnh báo</span><strong id="stat-alerts">--</strong><i class="bi bi-bell" aria-hidden="true"></i></article>
                </section>

                <section class="db-explorer" aria-label="Trình duyệt dữ liệu">
                    <nav class="db-dataset-rail" aria-label="Chọn dataset">
                        <div class="db-rail-heading">Datasets</div>
                        <button class="db-dataset active" data-dataset="stations" onclick="window.dbManager.selectDataset('stations', this)"><i class="bi bi-broadcast-pin"></i><span>Trạm</span><b id="db-count-stations">--</b></button>
                        <button class="db-dataset" data-dataset="devices" onclick="window.dbManager.selectDataset('devices', this)"><i class="bi bi-cpu"></i><span>Thiết bị</span><b id="db-count-devices">--</b></button>
                        <button class="db-dataset" data-dataset="sensor_data" onclick="window.dbManager.selectDataset('sensor_data', this)"><i class="bi bi-activity"></i><span>Cảm biến</span><b id="db-count-sensor_data">--</b></button>
                        <button class="db-dataset" data-dataset="alerts" onclick="window.dbManager.selectDataset('alerts', this)"><i class="bi bi-bell"></i><span>Cảnh báo</span><b id="db-count-alerts">--</b></button>
                    </nav>
                    <div class="db-workspace">
                        <div class="db-toolbar">
                            <div class="db-current-dataset"><span id="db-current-icon"><i class="bi bi-broadcast-pin"></i></span><div><strong id="db-current-title">Trạm</strong><small id="db-current-meta">Đang tải dữ liệu…</small></div></div>
                            <label class="ops-search" for="db-search"><i class="bi bi-search"></i><input type="search" id="db-search" placeholder="Tìm trong dataset…" oninput="window.dbManager.applyFilter()"></label>
                            <select class="form-select" id="db-sort" aria-label="Sắp xếp dữ liệu" onchange="window.dbManager.changeSort(this.value)"><option value="-id">Mới nhất</option><option value="id">Cũ nhất</option></select>
                            <select class="form-select" id="db-limit" aria-label="Số dòng mỗi trang" onchange="window.dbManager.changePageSize(this.value)"><option value="25">25 dòng</option><option value="50" selected>50 dòng</option><option value="100">100 dòng</option></select>
                        </div>
                        <div class="custom-table db-table-wrap">
                            <table class="table table-hover align-middle mb-0">
                                <thead id="db-table-head"><tr><th>ID</th><th>Thông tin chính</th><th>Trạng thái</th><th>Thời gian</th><th aria-label="Thao tác"></th></tr></thead>
                                <tbody id="db-table-body"><tr><td colspan="5" class="text-center py-5"><div class="spinner-border text-primary" role="status"></div><p class="mt-2 text-muted">Đang tải dữ liệu…</p></td></tr></tbody>
                            </table>
                        </div>
                        <footer class="ops-pagination"><span id="db-page-summary">0 bản ghi</span><div><button class="btn btn-outline-secondary" id="db-page-prev" onclick="window.dbManager.changePage(-1)" aria-label="Trang trước"><i class="bi bi-chevron-left"></i></button><span id="db-page-number">Trang 1</span><button class="btn btn-outline-secondary" id="db-page-next" onclick="window.dbManager.changePage(1)" aria-label="Trang sau"><i class="bi bi-chevron-right"></i></button></div></footer>
                    </div>
                </section>

                <div class="ops-drawer-backdrop" id="db-inspector-backdrop" onclick="window.dbManager.closeInspector()"></div>
                <aside class="ops-drawer" id="db-inspector" aria-hidden="true" aria-labelledby="db-inspector-title">
                    <header><div><span class="ops-eyebrow">RECORD INSPECTOR</span><h5 id="db-inspector-title">Chi tiết bản ghi</h5></div><button class="management-icon-btn btn btn-outline-secondary" onclick="window.dbManager.closeInspector()" aria-label="Đóng chi tiết"><i class="bi bi-x-lg"></i></button></header>
                    <div id="db-inspector-content" class="ops-drawer-body"></div>
                    <footer id="db-inspector-actions" class="ops-drawer-footer"></footer>
                </aside>
            </div>

            <!-- TAB: RESCUE -->
            <div class="tab-pane fade" id="tab-rescue">
                <header class="ops-page-header rescue-header">
                    <div><span class="ops-eyebrow">INCIDENT RESPONSE</span><h4><i class="bi bi-life-preserver me-2"></i>Điều phối cứu hộ</h4><p>Ưu tiên yêu cầu đang chờ và giữ đầy đủ ngữ cảnh khi xử lý.</p></div>
                    <button type="button" class="btn btn-primary" onclick="window.adminManager?.loadRescueRequests()"><i class="bi bi-arrow-clockwise me-1"></i>Làm mới queue</button>
                </header>
                <section class="ops-kpi-grid" aria-label="Tổng quan yêu cầu cứu hộ">
                    <article class="ops-kpi is-blue"><span>Tổng trường hợp</span><strong id="rescue-count-total">0</strong><i class="bi bi-inboxes"></i></article>
                    <article class="ops-kpi is-red"><span>Đang chờ</span><strong id="rescue-count-pending">0</strong><i class="bi bi-exclamation-triangle"></i></article>
                    <article class="ops-kpi is-green"><span>Đã xử lý</span><strong id="rescue-count-resolved">0</strong><i class="bi bi-check2-circle"></i></article>
                    <article class="ops-kpi is-slate"><span>Từ chối</span><strong id="rescue-count-rejected">0</strong><i class="bi bi-slash-circle"></i></article>
                </section>
                <section class="rescue-console">
                    <div class="rescue-toolbar">
                        <div class="rescue-status-tabs" role="group" aria-label="Lọc trạng thái"><button class="active" data-status="pending" onclick="window.adminManager?.setRescueStatus('pending', this)">Đang chờ</button><button data-status="all" onclick="window.adminManager?.setRescueStatus('all', this)">Tất cả</button><button data-status="resolved" onclick="window.adminManager?.setRescueStatus('resolved', this)">Đã xử lý</button><button data-status="rejected" onclick="window.adminManager?.setRescueStatus('rejected', this)">Từ chối</button></div>
                        <label class="ops-search" for="rescue-search"><i class="bi bi-search"></i><input type="search" id="rescue-search" placeholder="Tên, số điện thoại, nội dung…" oninput="window.adminManager?.scheduleRescueSearch()"></label>
                        <select class="form-select" id="rescue-sort" aria-label="Sắp xếp cứu hộ" onchange="window.adminManager?.changeRescueSort(this.value)"><option value="oldest">Chờ lâu nhất</option><option value="newest">Mới nhất</option></select>
                    </div>
                    <div id="rescue-requests-body" class="rescue-queue" aria-live="polite"><div class="ops-empty"><div class="spinner-border text-primary"></div><p>Đang tải yêu cầu cứu hộ…</p></div></div>
                    <footer class="ops-pagination"><span id="rescue-page-summary">0 yêu cầu</span><div><button class="btn btn-outline-secondary" id="rescue-page-prev" onclick="window.adminManager?.changeRescuePage(-1)" aria-label="Trang trước"><i class="bi bi-chevron-left"></i></button><span id="rescue-page-number">Trang 1</span><button class="btn btn-outline-secondary" id="rescue-page-next" onclick="window.adminManager?.changeRescuePage(1)" aria-label="Trang sau"><i class="bi bi-chevron-right"></i></button></div></footer>
                </section>
                <div class="ops-drawer-backdrop" id="rescue-inspector-backdrop" onclick="window.adminManager?.closeRescueInspector()"></div>
                <aside class="ops-drawer rescue-drawer" id="rescue-inspector" aria-hidden="true" aria-labelledby="rescue-inspector-title"><header><div><span class="ops-eyebrow">CASE DETAIL</span><h5 id="rescue-inspector-title">Chi tiết cứu hộ</h5></div><button class="management-icon-btn btn btn-outline-secondary" onclick="window.adminManager?.closeRescueInspector()" aria-label="Đóng chi tiết"><i class="bi bi-x-lg"></i></button></header><div id="rescue-inspector-content" class="ops-drawer-body"></div><footer id="rescue-inspector-actions" class="ops-drawer-footer"></footer></aside>
            </div>

            <!-- TAB 5: PI DEVICES -->
            <div class="tab-pane fade" id="tab-pi">

                <!-- Header -->
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h4 class="mb-1" style="font-weight:700;letter-spacing:.5px">
                            <i class="bi bi-broadcast me-2" style="color:#0ea5e9"></i>DEVICE MANAGEMENT
                        </h4>
                        <small class="text-muted">Monitor and configure connected Pi sensor nodes.</small>
                    </div>
                    <div class="d-flex gap-2 align-items-center">
                        <div class="input-group input-group-sm" style="width:200px">
                            <span class="input-group-text"
                                style="background:var(--bg-tertiary);border-color:var(--border-color)">
                                <i class="bi bi-search" style="color:var(--text-muted)"></i>
                            </span>
                            <input type="text" class="form-control form-control-sm" placeholder="Search ID..."
                                id="pi-search-input" oninput="window.adminManager._filterPiGrid(this.value)"
                                style="min-height:34px">
                        </div>
                        <button class="btn btn-sm btn-outline-primary" onclick="window.adminManager.loadPiDevices()">
                            <i class="bi bi-arrow-clockwise me-1"></i>Sync
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" id="pi-select-toggle"
                            onclick="window.adminManager.togglePiSelectMode()">
                            <i class="bi bi-check2-square me-1"></i>Chọn
                        </button>
                    </div>
                </div>

                <!-- Summary Cards -->
                <div class="row g-3 mb-4" id="pi-summary-cards" style="align-items:stretch">
                    <div class="col-md-4 d-flex">
                        <div class="card w-100" style="border-color:#f59e0b33">
                            <div class="card-body py-3 d-flex justify-content-between align-items-center">
                                <div>
                                    <div class="text-uppercase fw-bold small" style="color:#f59e0b;letter-spacing:1px">
                                        PENDING ACTIVATION</div>
                                    <div class="d-flex align-items-baseline gap-1">
                                        <span id="pi-pending-count"
                                            style="font-size:2rem;font-weight:800;line-height:1">0</span>
                                        <span class="text-muted small">nodes</span>
                                    </div>
                                    <small id="pi-pending-desc" class="text-muted">No devices awaiting handshake</small>
                                </div>
                                <i class="bi bi-hourglass-split" style="font-size:2rem;color:#f59e0b44"></i>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4 d-flex">
                        <div class="card w-100" style="border-color:#22c55e33">
                            <div class="card-body py-3 d-flex justify-content-between align-items-center">
                                <div>
                                    <div class="text-uppercase fw-bold small" style="color:#22c55e;letter-spacing:1px">
                                        ACTIVATED · UNASSIGNED</div>
                                    <div class="d-flex align-items-baseline gap-1">
                                        <span id="pi-activated-count"
                                            style="font-size:2rem;font-weight:800;line-height:1">0</span>
                                        <span class="text-muted small">nodes</span>
                                    </div>
                                    <small class="text-muted">System optimized. No idle units.</small>
                                </div>
                                <i class="bi bi-check-circle" style="font-size:2rem;color:#22c55e44"></i>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4 d-flex">
                        <div class="card w-100" style="border-color:#0ea5e933">
                            <div class="card-body py-3 d-flex justify-content-between align-items-center">
                                <div>
                                    <div class="text-uppercase fw-bold small" style="color:#0ea5e9;letter-spacing:1px">
                                        ASSIGNED TO STATION</div>
                                    <div class="d-flex align-items-baseline gap-1">
                                        <span id="pi-assigned-count"
                                            style="font-size:2rem;font-weight:800;line-height:1">0</span>
                                        <span class="text-muted small">nodes</span>
                                    </div>
                                </div>
                                <i class="bi bi-broadcast-pin" style="font-size:2rem;color:#0ea5e944"></i>
                            </div>
                            <div
                                style="height:3px;background:linear-gradient(90deg,#0ea5e9,#06b6d4);border-radius:0 0 12px 12px">
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Active Grid / Table -->
                <div class="card">
                    <div class="card-body p-0">
                        <div class="d-flex justify-content-between align-items-center px-3 py-2"
                            style="border-bottom:1px solid var(--border-color)">
                            <span class="fw-bold small text-uppercase" style="letter-spacing:1px">
                                <i class="bi bi-grid-3x3 me-1"></i>ACTIVE GRID
                            </span>
                            <div class="d-flex gap-3 small">
                                <span><i class="bi bi-circle-fill me-1"
                                        style="color:#22c55e;font-size:.5rem"></i>Online</span>
                                <span><i class="bi bi-circle-fill me-1"
                                        style="color:#ef4444;font-size:.5rem"></i>Offline</span>
                            </div>
                        </div>
                        <div class="table-responsive">
                            <table class="table mb-0">
                                <thead>
                                    <tr>
                                        <th style="width:40px"></th>
                                        <th>DEVICE ID / NAME</th>
                                        <th>SERIAL</th>
                                        <th>STATUS</th>
                                        <th>LAST PING</th>
                                    </tr>
                                </thead>
                                <tbody id="pi-grid-body">
                                    <tr>
                                        <td colspan="5" class="text-center text-muted py-4">Loading...</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                        <div class="d-flex justify-content-between align-items-center px-3 py-2"
                            style="border-top:1px solid var(--border-color)">
                            <small id="pi-grid-info" class="text-muted">Showing 0 entries</small>
                            <nav>
                                <ul class="pagination pagination-sm mb-0" id="pi-grid-pagination"></ul>
                            </nav>
                        </div>
                    </div>
                </div>

                <!-- Hidden legacy elements for badge compatibility -->
                <span id="pi-pending-badge" style="display:none">0</span>
                <span id="pi-activated-badge" style="display:none">0</span>
                <span id="pi-assigned-badge" style="display:none">0</span>
                <div id="pi-pending-list" style="display:none"></div>
                <div id="pi-activated-list" style="display:none"></div>
                <div id="pi-assigned-list" style="display:none"></div>

            </div>

        </div>
    </div>

    <!-- ============================================
         MODALS
    ============================================ -->

    
`;
