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
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <h4><i class="bi bi-database me-2"></i>Quản lý Database</h4>

                    <!-- UPDATED BUTTONS -->
                    <div class="btn-group">
                        <button class="btn btn-outline-primary" onclick="window.dbManager.loadAllData()">
                            <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                        </button>

                        <!-- EXCEL EXPORT -->
                        <button class="btn btn-outline-success" onclick="window.dbManager.exportToExcel()">
                            <i class="bi bi-file-earmark-excel me-1"></i>Export Excel
                        </button>

                        <!-- CLEAR DATABASE -->
                        <button class="btn btn-outline-danger" onclick="window.dbManager.clearDatabase()">
                            <i class="bi bi-trash3 me-1"></i>Xóa DB
                        </button>
                    </div>
                </div>

                <!-- Filter & Search -->
                <div class="card mb-3">
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-3">
                                <select class="form-select" id="db-filter-table"
                                    onchange="window.dbManager.applyFilter()">
                                    <option value="all">Tất cả bảng</option>
                                    <option value="stations">Stations</option>
                                    <option value="devices">Devices</option>
                                    <option value="sensor_data">Sensor Data</option>
                                    <option value="alerts">Alerts</option>
                                </select>
                            </div>
                            <div class="col-md-6">
                                <input type="text" class="form-control" id="db-search" placeholder="Tìm kiếm..."
                                    oninput="window.dbManager.applyFilter()">
                            </div>
                            <div class="col-md-3">
                                <select class="form-select" id="db-limit" onchange="window.dbManager.applyFilter()">
                                    <option value="50">50 dòng</option>
                                    <option value="100" selected>100 dòng</option>
                                    <option value="500">500 dòng</option>
                                    <option value="1000">1000 dòng</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Database Viewer -->
                <div class="custom-table" style="max-height: 600px; overflow-y: auto;">
                    <table class="table table-hover table-sm mb-0">
                        <thead id="db-table-head" class="sticky-top">
                            <tr>
                                <th style="width: 80px;">ID</th>
                                <th style="width: 120px;">Table</th>
                                <th>Data Preview</th>
                                <th style="width: 150px;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="db-table-body">
                            <tr>
                                <td colspan="4" class="text-center py-4">
                                    <div class="spinner-border text-primary"></div>
                                    <p class="mt-2 text-muted">Đang tải...</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>

                <!-- Stats -->
                <div class="row g-3 mt-3">
                    <div class="col-md-3">
                        <div class="card bg-primary text-white">
                            <div class="card-body">
                                <h6 class="mb-1">Stations</h6>
                                <h3 id="stat-stations" class="mb-0">--</h3>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card bg-success text-white">
                            <div class="card-body">
                                <h6 class="mb-1">Devices</h6>
                                <h3 id="stat-devices" class="mb-0">--</h3>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card bg-info text-white">
                            <div class="card-body">
                                <h6 class="mb-1">Sensor Data</h6>
                                <h3 id="stat-data" class="mb-0">--</h3>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card bg-warning text-white">
                            <div class="card-body">
                                <h6 class="mb-1">Active Alerts</h6>
                                <h3 id="stat-alerts" class="mb-0">--</h3>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- TAB: RESCUE -->
            <div class="tab-pane fade" id="tab-rescue">
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h4 class="mb-1" style="font-weight:700;">
                            <i class="bi bi-life-preserver me-2" style="color:#ef4444"></i>QUẢN LÝ CỨU HỘ
                        </h4>
                        <small class="text-muted">Danh sách yêu cầu cứu hộ khẩn cấp.</small>
                    </div>
                    <button type="button" class="btn btn-sm btn-outline-primary"
                        onclick="window.adminManager?.loadRescueRequests()">
                        <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                    </button>
                </div>
                <div class="alert alert-info py-2 small mb-3">
                    Guest có thể gửi vị trí GPS + thông tin cứu hộ từ web map. Admin xử lý tại đây.
                </div>
                <div class="row g-2 mb-3">
                    <div class="col-6 col-md-3">
                        <div class="card border-0 shadow-sm" style="background: var(--bg-tertiary);">
                            <div class="card-body py-2 px-3">
                                <div class="small text-muted">Tổng trường hợp</div>
                                <div class="fw-bold fs-5" id="rescue-count-total">0</div>
                            </div>
                        </div>
                    </div>
                    <div class="col-6 col-md-3">
                        <div class="card border-0 shadow-sm" style="background: var(--bg-tertiary);">
                            <div class="card-body py-2 px-3">
                                <div class="small text-muted">Đang chờ</div>
                                <div class="fw-bold fs-5 text-danger" id="rescue-count-pending">0</div>
                            </div>
                        </div>
                    </div>
                    <div class="col-6 col-md-3">
                        <div class="card border-0 shadow-sm" style="background: var(--bg-tertiary);">
                            <div class="card-body py-2 px-3">
                                <div class="small text-muted">Đã xong</div>
                                <div class="fw-bold fs-5 text-success" id="rescue-count-resolved">0</div>
                            </div>
                        </div>
                    </div>
                    <div class="col-6 col-md-3">
                        <div class="card border-0 shadow-sm" style="background: var(--bg-tertiary);">
                            <div class="card-body py-2 px-3">
                                <div class="small text-muted">Từ chối</div>
                                <div class="fw-bold fs-5 text-secondary" id="rescue-count-rejected">0</div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="custom-table" style="max-height: 600px; overflow-y: auto;">
                    <table class="table table-hover table-sm align-middle mb-0" id="rescue-requests-table">
                        <thead class="sticky-top">
                            <tr>
                                <th>ID</th>
                                <th>Thời gian</th>
                                <th>Người gửi</th>
                                <th>Liên hệ</th>
                                <th>Vị trí</th>
                                <th>Nội dung</th>
                                <th>Trạng thái</th>
                                <th>Thao tác</th>
                            </tr>
                        </thead>
                        <tbody id="rescue-requests-body">
                            <tr>
                                <td colspan="8" class="text-muted text-center py-4">Chưa có dữ liệu</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
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
