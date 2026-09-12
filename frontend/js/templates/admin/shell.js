window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['shell'] = String.raw`
<!-- SECURITY: Block page render until auth verified -->
    



    <!-- Sidebar -->
    <div class="admin-sidebar">
        <div class="sidebar-brand" role="link" tabindex="0" onclick="window.location.href='/map'" onkeydown="if(event.key==='Enter') window.location.href='/map'"
            title="Về trang bản đồ">
            <span class="app-brand-plate"><img src="/assets/aitogy.png?v=__BUILD_VERSION__" width="759" height="329" alt="Aitogy"></span>
            <span class="app-brand-product"><strong>Landslide</strong><small>Monitor</small></span>
        </div>

        <nav>
            <div class="nav-item">
                <a class="nav-link active" href="#" data-tab="tab-users"
                    onclick="event.preventDefault(); window.adminManager?.switchTab('tab-users', this)">
                    <i class="bi bi-people"></i>
                    <span>Người dùng</span>
                </a>
            </div>
            <div class="nav-item">
                <a class="nav-link" href="#" data-tab="tab-projects"
                    onclick="event.preventDefault(); window.adminManager?.switchTab('tab-projects', this)">
                    <i class="bi bi-folder"></i>
                    <span>Dự án</span>
                </a>
            </div>
            <div class="nav-item">
                <a class="nav-link" href="#" data-tab="tab-database"
                    onclick="event.preventDefault(); window.adminManager?.switchTab('tab-database', this)">
                    <i class="bi bi-database"></i>
                    <span>Database</span>
                </a>
            </div>
            <div class="nav-item">
                <a class="nav-link" href="#" data-tab="tab-simulations"
                    onclick="event.preventDefault(); window.adminManager?.switchTab('tab-simulations', this)">
                    <i class="bi bi-boxes"></i>
                    <span>Mô phỏng</span>
                </a>
            </div>
            <div class="nav-item">
                <a class="nav-link" href="#" data-tab="tab-pi"
                    onclick="event.preventDefault(); window.adminManager?.switchTab('tab-pi', this)">
                    <i class="bi bi-cpu-fill" style="color:#0ea5e9"></i>
                    <span>Pi Devices</span>
                </a>
            </div>
            <div class="nav-item">
                <a class="nav-link" href="#" data-tab="tab-rescue"
                    onclick="event.preventDefault(); window.adminManager?.switchTab('tab-rescue', this)">
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
                <button type="button" id="theme-toggle-btn" class="theme-toggle-mini"
                    aria-label="Chuyển giao diện sáng tối" title="Giao diện sáng / tối">
                    <i class="bi bi-moon-stars-fill"></i>
                </button>
                <div class="user-profile d-flex align-items-center gap-2">
                    <div class="avatar-circle">A</div>
                    <span class="d-none d-sm-block">Administrator</span>
                </div>
            </div>
        </div>
    </nav>

    <!-- Main Content -->
    <div class="admin-main">

        <!-- Tab Content (no horizontal tabs — sidebar handles switching) -->
        <div class="tab-content" id="admin-tab-content">

            <!-- TAB 1: USERS -->
            <div class="tab-pane fade show active" id="tab-users">
                <header class="ops-page-header"><div><span class="ops-eyebrow">ACCESS CONTROL</span><h4><i class="bi bi-people me-2"></i>Quản lý người dùng</h4><p>Tài khoản, vai trò và phạm vi dự án được cấp quyền.</p></div><button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#addUserModal"><i class="bi bi-person-plus me-2"></i>Thêm người dùng</button></header>
                <div class="user-toolbar">
                    <label class="ops-search" for="user-search"><i class="bi bi-search"></i><input type="search" id="user-search" placeholder="Tìm tài khoản hoặc họ tên…" oninput="window.adminManager?.scheduleUserFilter()"></label>
                    <select class="form-select" id="user-role-filter" aria-label="Lọc theo vai trò" onchange="window.adminManager?.loadUsers()"><option value="">Tất cả vai trò</option><option value="admin">Admin</option><option value="operator">Operator</option><option value="viewer">Viewer</option></select>
                    <select class="form-select" id="user-status-filter" aria-label="Lọc theo trạng thái" onchange="window.adminManager?.loadUsers()"><option value="">Mọi trạng thái</option><option value="true">Hoạt động</option><option value="false">Đã khóa</option></select>
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
                        <button class="db-dataset" data-dataset="gnss_adjustments" onclick="window.dbManager.selectDataset('gnss_adjustments', this)"><i class="bi bi-crosshair2"></i><span>Bình sai GNSS</span><b id="db-count-gnss_adjustments">--</b></button>
                        <button class="db-dataset" data-dataset="alerts" onclick="window.dbManager.selectDataset('alerts', this)"><i class="bi bi-bell"></i><span>Cảnh báo</span><b id="db-count-alerts">--</b></button>
                    </nav>
                    <div class="db-workspace">
                        <div class="db-toolbar">
                            <div class="db-current-dataset"><span id="db-current-icon"><i class="bi bi-broadcast-pin"></i></span><div><strong id="db-current-title">Trạm</strong><small id="db-current-meta">Đang tải dữ liệu…</small></div></div>
                            <label class="ops-search" for="db-search"><i class="bi bi-search"></i><input type="search" id="db-search" placeholder="Tìm trong dataset…" oninput="window.dbManager.applyFilter()"></label>
                            <div id="db-context-filters" class="db-context-filters" aria-label="Bộ lọc dataset"></div>
                            <select class="form-select" id="db-sort" aria-label="Sắp xếp dữ liệu" onchange="window.dbManager.changeSort(this.value)"><option value="-id">Mới nhất</option><option value="id">Cũ nhất</option></select>
                            <select class="form-select" id="db-limit" aria-label="Số dòng mỗi trang" onchange="window.dbManager.changePageSize(this.value)"><option value="25">25 dòng</option><option value="50">50 dòng</option><option value="100" selected>100 dòng</option></select>
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

            <!-- TAB: SIMULATION AUDIT -->
            <div class="tab-pane fade" id="tab-simulations" data-private-permission="MANAGE_SIMULATIONS">
                <header class="ops-page-header simulation-audit-header">
                    <div><span class="ops-eyebrow">PHÂN TÍCH TÁI LẬP</span><h4><i class="bi bi-boxes me-2"></i>Mô phỏng</h4><p>Theo dõi trạng thái, tham số nguồn và kết quả mô phỏng Digital Twin mà không thay đổi mô hình vật lý hiện có.</p></div>
                    <button type="button" class="btn btn-outline-primary" onclick="window.adminManager?.loadSimulationRuns(true)"><i class="bi bi-arrow-clockwise me-1"></i>Làm mới</button>
                </header>
                <section class="simulation-audit-workspace" aria-live="polite">
                    <div class="simulation-audit-toolbar"><span id="simulation-audit-meta">Đang tải nhật ký…</span><span class="simulation-audit-note"><i class="bi bi-shield-check me-1"></i>Chỉ admin có quyền chạy, dừng, chạy lại và xuất báo cáo.</span></div>
                    <div id="simulation-audit-list" class="simulation-audit-list"><div class="ops-empty"><div class="spinner-border text-primary"></div><p>Đang tải nhật ký mô phỏng…</p></div></div>
                </section>
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

${window.LegacyTemplateParts['pi-devices'] || ''}

        </div>
    </div>

    <!-- ============================================
         MODALS
    ============================================ -->

    
`;
