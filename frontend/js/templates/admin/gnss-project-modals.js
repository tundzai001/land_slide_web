window.LegacyTemplateParts ||= {};
window.LegacyTemplateParts['gnss-project-modals'] = String.raw`    <!-- MODAL GNSS VISUAL CALCULATION BOARD -->
    <div class="modal fade" id="gnssTerminalModal" tabindex="-1">
        <div class="modal-dialog modal-xl modal-dialog-centered" style="max-width: 95vw;">
            <div class="modal-content bg-dark text-light border-primary" style="height: 85vh;">
                <div class="modal-header border-bottom border-secondary py-2">
                    <h5 class="modal-title text-primary font-monospace" style="font-size: 1.1rem;">
                        <i class="bi bi-cpu me-2"></i>GNSS Agent Calculation Board (Real-time)
                    </h5>
                    <div id="gnss-phase-indicator" class="ms-4 text-warning fw-bold font-monospace">Phase: WAITING</div>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body p-0 d-flex flex-row" style="height: calc(100% - 60px);">
                    <!-- Cột Trái: Canvas Bản Vẽ (70%) -->
                    <div class="flex-grow-1 position-relative" style="background-color: #f8f9fa; border-right: 1px solid #444; overflow: hidden;" id="gnss-board-container">
                        <canvas id="gnss-board-canvas" style="width: 100%; height: 100%; display: block;"></canvas>
                        
                        <!-- Overlay Tooltips Container -->
                        <div id="gnss-board-tooltips" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;"></div>
                    </div>
                    
                    <!-- Cột Phải: Dữ liệu (30%) -->
                    <div class="d-flex flex-column" style="width: 450px; background-color: #1e1e1e;">
                        <div class="p-2 border-bottom border-secondary bg-black">
                            <h6 class="mb-0 text-info font-monospace"><i class="bi bi-table me-1"></i>Baseline Vectors</h6>
                        </div>
                        <div class="flex-grow-1" style="overflow-y: auto;" id="gnss-data-panel">
                            <table class="table table-dark table-sm table-hover font-monospace mb-0" style="font-size: 0.75rem;">
                                <thead>
                                    <tr class="text-secondary">
                                        <th>#</th>
                                        <th>From</th>
                                        <th>To</th>
                                        <th>dN(m)</th>
                                        <th>dE(m)</th>
                                        <th>dH(m)</th>
                                        <th></th>
                                    </tr>
                                </thead>
                                <tbody id="gnss-baseline-table-body">
                                    <!-- Rows appended dynamically -->
                                </tbody>
                            </table>
                        </div>
                        <!-- Báo cáo Kết Quả -->
                        <div id="adj-results-section" class="p-3 border-top border-secondary bg-black" style="display: none;">
                            <h6 id="adj-process-status" class="mb-2"></h6>
                            <div class="text-secondary font-monospace" style="font-size: 0.7rem;">Time: <span id="adj-val-time"></span></div>
                            <div id="adj-points-list" class="mt-2"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Modal chi tiết Advanced Data -->
    <div class="modal fade" id="gnssAdvancedDataModal" tabindex="-1">
        <div class="modal-dialog modal-lg">
            <div class="modal-content bg-dark text-light">
                <div class="modal-header border-secondary">
                    <h5 class="modal-title text-info font-monospace">AGRICA Advanced Fields</h5>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body font-monospace" style="font-size: 0.8rem; height: 500px; overflow-y: auto;">
                    <pre id="gnss-advanced-data-json" style="color: #a6e22e;"></pre>
                </div>
            </div>
        </div>
    </div>

    <!-- Project Config Modal -->
    <div class="modal fade" id="projectConfigModal" tabindex="-1">
        <div class="modal-dialog modal-xl modal-dialog-centered modal-dialog-scrollable">
            <div class="modal-content project-config-modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="projectConfigModalTitle">Chỉnh sửa dự án</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <section class="config-section project-profile-section mb-4">
                        <div class="section-header">
                            <i class="bi bi-building text-primary" aria-hidden="true"></i>
                            <div>
                                <h5>Thông tin dự án</h5>
                                <p class="mb-0">Tên, mã nhận diện và mô tả hiển thị trong trang quản trị.</p>
                            </div>
                        </div>
                        <div class="sensor-config-body">
                            <div class="row g-3">
                                <div class="col-md-4">
                                    <label class="form-label" for="project-config-code">Mã dự án <span class="text-danger">*</span></label>
                                    <input type="text" class="form-control" id="project-config-code" maxlength="100" autocomplete="off">
                                    <div class="form-text">Mã duy nhất dùng để nhận diện dự án.</div>
                                </div>
                                <div class="col-md-8">
                                    <label class="form-label" for="project-config-name">Tên dự án <span class="text-danger">*</span></label>
                                    <input type="text" class="form-control" id="project-config-name" maxlength="255" autocomplete="off">
                                </div>
                                <div class="col-12">
                                    <label class="form-label" for="project-config-description">Mô tả</label>
                                    <textarea class="form-control" id="project-config-description" rows="3" maxlength="1000" placeholder="Mô tả mục tiêu và phạm vi quan trắc"></textarea>
                                </div>
                                <div class="col-12">
                                    <label class="form-label" for="project-config-location">Địa điểm</label>
                                    <input type="text" class="form-control" id="project-config-location" maxlength="500" placeholder="Tỉnh, huyện hoặc khu vực triển khai">
                                </div>
                            </div>
                        </div>
                    </section>


                    <!-- GNSS CLUSTERS CONFIG -->
                    <div class="config-section mb-4">
                        <div class="section-header">
                            <i class="bi bi-diagram-3-fill text-primary"></i>
                            <h5>Quản lý Cụm Trạm (GNSS Clusters)</h5>
                            <button type="button" class="btn btn-sm btn-outline-primary ms-auto" onclick="window.adminManager.addClusterRow(document.getElementById('project-gnss-clusters-container'))">
                                <i class="bi bi-plus-lg"></i> Thêm Cụm
                            </button>
                        </div>
                        <div class="sensor-config-body">
                            <p class="text-muted small mb-3">
                                Chọn các trạm sẽ đưa vào cùng 1 cụm để bình sai đồng thời. Một rover có thể nằm trong nhiều cụm.
                            </p>
                            <div id="project-gnss-clusters-container">
                                <!-- Cluster rows will be appended here -->
                            </div>
                        </div>
                    </div>
                    <!-- AUTO-ADJUSTMENT SCHEDULING -->
                    <div class="config-section auto-adjustment-card mb-4" id="auto-adjustment-config-section">
                        <div class="section-header auto-adjustment-header">
                            <span class="auto-adjustment-icon"><i class="bi bi-clock-history"></i></span>
                            <div class="auto-adjustment-heading">
                                <h5>Bình sai tự động</h5>
                                <p>Thiết lập cụm GNSS và lịch xử lý định kỳ</p>
                            </div>
                            <div class="form-check form-switch auto-adjustment-switch ms-auto">
                                <input class="form-check-input" type="checkbox" id="auto-adj-enabled" onchange="window.adminManager.onAutoAdjToggle(this.checked)">
                                <label class="form-check-label" for="auto-adj-enabled">Kích hoạt</label>
                            </div>
                        </div>
                        <div class="sensor-config-body auto-adjustment-body" id="auto-adj-body" style="display:none;">
                            <div class="row g-3 auto-adjustment-grid">
                                <div class="col-md-6">
                                    <label class="form-label auto-adjustment-field-label"><i class="bi bi-diagram-3"></i> Chọn cụm chạy tự động</label>
                                    <div id="auto-adj-cluster-checkboxes" class="auto-adjustment-cluster-list">
                                        <span class="text-muted small">Lưu cấu hình cụm trước...</span>
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <div class="auto-adjustment-control-stack">
                                    <label class="form-label auto-adjustment-field-label" for="auto-adj-interval"><i class="bi bi-arrow-repeat"></i> Tần suất</label>
                                    <div class="auto-adjustment-input-wrap">
                                        <select class="form-select form-select-sm" id="auto-adj-interval" onchange="window.adminManager.generateSchedulePreview()">
                                            <option value="1">Mỗi 1 giờ</option>
                                            <option value="2">Mỗi 2 giờ</option>
                                            <option value="3">Mỗi 3 giờ</option>
                                            <option value="4" selected>Mỗi 4 giờ</option>
                                            <option value="6">Mỗi 6 giờ</option>
                                            <option value="8">Mỗi 8 giờ</option>
                                            <option value="12">Mỗi 12 giờ</option>
                                        </select>
                                    </div>
                                    <label class="form-label auto-adjustment-field-label" for="auto-adj-start-hour"><i class="bi bi-play-circle"></i> Mốc giờ bắt đầu</label>
                                    <div class="auto-adjustment-input-wrap auto-adjustment-hour-wrap">
                                        <select class="form-select form-select-sm" id="auto-adj-start-hour" onchange="window.adminManager.generateSchedulePreview()">
                                            <option value="0" selected>00:00</option><option value="1">01:00</option><option value="2">02:00</option><option value="3">03:00</option>
                                            <option value="4">04:00</option><option value="5">05:00</option><option value="6">06:00</option><option value="7">07:00</option>
                                            <option value="8">08:00</option><option value="9">09:00</option><option value="10">10:00</option><option value="11">11:00</option>
                                            <option value="12">12:00</option><option value="13">13:00</option><option value="14">14:00</option><option value="15">15:00</option>
                                            <option value="16">16:00</option><option value="17">17:00</option><option value="18">18:00</option><option value="19">19:00</option>
                                            <option value="20">20:00</option><option value="21">21:00</option><option value="22">22:00</option><option value="23">23:00</option>
                                        </select>
                                        <span>UTC+7</span>
                                    </div>
                                    </div>
                                </div>
                            </div>
                            <div class="auto-adjustment-schedule-block">
                                <label class="form-label auto-adjustment-field-label"><i class="bi bi-calendar3"></i> Lịch chạy trong ngày</label>
                                <div id="auto-adj-schedule-preview" class="auto-adjustment-schedule">
                                    <span class="text-muted small">Chưa có lịch</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="button" class="btn btn-primary" onclick="window.adminManager.saveProjectConfig()">
                        <i class="bi bi-check2-circle me-1"></i> Lưu thay đổi
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- 1. Add User Modal -->
    <div class="modal fade" id="addUserModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Thêm người dùng mới</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <form id="addUserForm">
                        <div class="mb-3">
                            <label class="form-label">Tài khoản</label>
                            <input type="text" class="form-control" id="new-username" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Mật khẩu</label>
                            <input type="password" class="form-control" id="new-password" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Họ tên</label>
                            <input type="text" class="form-control" id="new-fullname">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Vai trò</label>
                            <select class="form-select" id="new-role"
                                onchange="document.getElementById('project-assign-group').style.display = (this.value === 'operator' || this.value === 'viewer') ? 'block' : 'none'">
                                <option value="viewer">Viewer</option>
                                <option value="operator">Operator</option>
                                <option value="admin">Admin</option>
                            </select>
                        </div>
                        <div class="mb-3" id="project-assign-group">
                            <label class="form-label">Gán dự án <small class="text-muted">(Operator/Viewer, Viewer không chọn = tất cả)</small></label>
                            <div id="project-checkbox-list" class="project-checkbox-list"
                                style="max-height:200px;overflow-y:auto;border:1px solid var(--border-color);border-radius:8px;padding:10px">
                                <small class="text-muted">Đang tải danh sách dự án...</small>
                            </div>
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="button" class="btn btn-gradient" onclick="window.adminManager.createUser()">Tạo tài
                        khoản</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Edit User Configuration Modal -->
    <div class="modal fade" id="editUserModal" tabindex="-1" aria-labelledby="editUserModalLabel">
        <div class="modal-dialog modal-dialog-centered modal-lg">
            <div class="modal-content">
                <div class="modal-header">
                    <div><span class="ops-eyebrow">USER CONFIGURATION</span><h5 class="modal-title mt-1" id="editUserModalLabel">Sửa cấu hình người dùng</h5></div>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Đóng"></button>
                </div>
                <div class="modal-body">
                    <input type="hidden" id="edit-user-id">
                    <div class="row g-3">
                        <div class="col-md-6"><label class="form-label" for="edit-user-username">Tài khoản</label><input class="form-control" id="edit-user-username" readonly></div>
                        <div class="col-md-6"><label class="form-label" for="edit-user-fullname">Họ tên</label><input class="form-control" id="edit-user-fullname"></div>
                        <div class="col-md-6"><label class="form-label" for="edit-user-role">Vai trò</label><select class="form-select" id="edit-user-role" onchange="window.adminManager?.syncEditUserProjectVisibility()"><option value="viewer">Viewer</option><option value="operator">Operator</option><option value="admin">Admin</option></select></div>
                        <div class="col-md-6"><label class="form-label" for="edit-user-password">Mật khẩu mới</label><input type="password" class="form-control" id="edit-user-password" minlength="6" autocomplete="new-password" placeholder="Để trống nếu không đổi"><small class="form-text">Tối thiểu 6 ký tự khi thay đổi.</small></div>
                    </div>
                    <section class="user-project-scope mt-4" id="edit-user-project-group"><div><strong>Phạm vi dự án</strong><small>Chọn các dự án mà người dùng được phép truy cập.</small></div><div id="edit-user-projects" class="project-checkbox-list"><span class="text-muted small">Đang tải dự án…</span></div></section>
                </div>
                <div class="modal-footer"><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Hủy</button><button type="button" class="btn btn-primary" id="save-user-config-btn" onclick="window.adminManager?.saveUserConfiguration()"><i class="bi bi-check2-circle me-1"></i>Lưu cấu hình</button></div>
            </div>
        </div>
    </div>

    <!-- 2. Create Project Modal -->
    <div class="modal fade" id="createProjectModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Tạo Dự án Mới</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <form id="createProjectForm">
                        <div class="mb-3">
                            <label class="form-label">Mã dự án <span class="text-danger">*</span></label>
                            <input type="text" class="form-control" id="project-code" required>
                            <small class="text-muted">VD: DA_QUANGNINH_2024</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Tên dự án <span class="text-danger">*</span></label>
                            <input type="text" class="form-control" id="project-name" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Mô tả</label>
                            <textarea class="form-control" id="project-desc" rows="3"></textarea>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Vị trí</label>
                            <input type="text" class="form-control" id="project-location" placeholder="VD: Quảng Ninh">
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="button" class="btn btn-gradient" onclick="window.adminManager.createProject()">
                        <i class="bi bi-save me-1"></i> Tạo Dự án
                    </button>
                </div>
            </div>
        </div>
    </div>

`;
