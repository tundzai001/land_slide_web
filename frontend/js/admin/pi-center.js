(() => {
class AdminPiCenterFeature extends window.AdminManager {
    // =========================================================================
    // FIELD STATION GẮN LIỀN VỚI PI CENTER
    // =========================================================================

    /** Assign selected pi_point(s) from the action bar to a Pi Center */
    async assignSelectedPointToCenter() {
        const checked = document.querySelectorAll('.pi-checkbox:checked');
        const pointIds = [];
        checked.forEach(cb => {
            const row = cb.closest('.pi-grid-row') || cb.closest('tr');
            if (row && row.dataset.piType === 'pi_point') {
                pointIds.push(parseInt(cb.dataset.piId));
            }
        });
        if (pointIds.length === 0) {
            window.toast?.warning('Không có Pi Hiện trường nào được chọn');
            return;
        }

        // Fetch available Pi Centers (activated or assigned, not pi_point)
        try {
            const res = await fetch('/api/field/pi-devices', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) throw new Error('Failed to load devices');
            const devices = await res.json();
            const centers = devices.filter(d =>
                d.device_type !== 'pi_point' &&
                (d.status === 'activated' || d.status === 'assigned')
            );

            if (centers.length === 0) {
                window.toast?.warning('Không có Pi Trung tâm nào khả dụng. Hãy kích hoạt Pi Trung tâm trước.');
                return;
            }

            // Build a quick modal to pick center
            const existing = document.getElementById('pickCenterModal');
            if (existing) existing.remove();

            const modal = document.createElement('div');
            modal.innerHTML = `
                <div class="modal fade" id="pickCenterModal" tabindex="-1">
                    <div class="modal-dialog modal-dialog-centered">
                        <div class="modal-content">
                            <div class="modal-header" style="background:linear-gradient(135deg,#0ea5e9,#6366f1);color:#fff">
                                <h5 class="modal-title"><i class="bi bi-link-45deg me-2"></i>Gán ${pointIds.length} Pi Hiện trường vào Pi Trung tâm</h5>
                                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                            </div>
                            <div class="modal-body">
                                <p class="text-muted small mb-3">Chọn Pi Trung tâm để gán:</p>
                                <div class="list-group list-group-flush" id="center-pick-list">
                                    ${centers.map(c => `
                                        <button type="button" class="list-group-item list-group-item-action d-flex gap-3 align-items-center center-pick-item"
                                               data-center-id="${c.id}" style="cursor:pointer; background:transparent; border-color:var(--border-color)">
                                            <div class="pick-indicator"><i class="bi bi-check-lg"></i></div>
                                            <div class="text-start">
                                                <strong>${c.name}</strong>
                                                <small class="d-block text-muted font-monospace">${c.serial}</small>
                                                ${c.station_name ? `<small class="text-info">📍 ${c.station_name}</small>` : ''}
                                            </div>
                                            <span class="badge ${c.status === 'assigned' ? 'bg-primary' : 'bg-success'} ms-auto">${c.status === 'assigned' ? '📍 Assigned' : '✅ Activated'}</span>
                                        </button>
                                    `).join('')}
                                </div>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                                <button type="button" class="btn btn-primary" id="btn-confirm-center-pick">
                                    <i class="bi bi-check-lg me-1"></i>Gán
                                </button>
                            </div>
                        </div>
                    </div>
                </div>`;
            document.body.appendChild(modal);

            const bsModal = new bootstrap.Modal(document.getElementById('pickCenterModal'));
            bsModal.show();

            let selectedCenterId = null;
            modal.querySelectorAll('.center-pick-item').forEach(item => {
                item.addEventListener('click', () => {
                    modal.querySelectorAll('.center-pick-item').forEach(x => x.classList.remove('is-selected'));
                    item.classList.add('is-selected');
                    selectedCenterId = parseInt(item.dataset.centerId, 10);
                });
            });

            document.getElementById('btn-confirm-center-pick').addEventListener('click', async () => {
                if (!selectedCenterId) {
                    window.toast?.warning('Vui lòng chọn Pi Trung tâm');
                    return;
                }
                const centerId = selectedCenterId;

                let ok = 0, fail = 0;
                for (const pointId of pointIds) {
                    try {
                        const r = await fetch(`/api/field/pi-devices/${pointId}/assign-to-center`, {
                            method: 'PUT',
                            headers: {
                                'Authorization': `Bearer ${this.token}`,
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify({ pi_center_id: centerId })
                        });
                        if (r.ok) ok++; else fail++;
                    } catch { fail++; }
                }

                bsModal.hide();
                if (ok > 0) window.toast?.success(`✅ Đã gán ${ok} Pi Hiện trường thành công!`);
                if (fail > 0) window.toast?.error(`❌ ${fail} thất bại`);

                // Exit select mode and reload
                this._piSelectMode = false;
                const toggleBtn = document.getElementById('pi-select-toggle');
                if (toggleBtn) { toggleBtn.classList.replace('btn-primary', 'btn-outline-secondary'); toggleBtn.innerHTML = '<i class="bi bi-check2-square me-1"></i>Chọn'; }
                const bar = document.getElementById('pi-action-bar');
                if (bar) bar.style.bottom = '-80px';
                setTimeout(() => this.loadPiDevices(), 500);
            });

            document.getElementById('pickCenterModal').addEventListener('hidden.bs.modal', () => {
                modal.remove();
            });

        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

    /** Open popup to assign an activated Pi Point to a Center */
    async openAssignPiPointModal(centerId) {
        document.getElementById('assign-center-id').value = centerId;
        const select = document.getElementById('point-device-select');
        const optionsBox = document.getElementById('point-device-options');
        if (select) select.value = '';
        if (optionsBox) optionsBox.innerHTML = '<div class="text-muted small">-- Đang tải ... --</div>';

        const modal = new bootstrap.Modal(document.getElementById('assignPiPointModal'));
        modal.show();

        try {
            // Load ALL devices again
            const res = await fetch('/api/field/pi-devices', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) throw new Error('Failed to load devices');
            const devices = await res.json();

            // Filter ones that are pi_point, activated, and have no pi_center_id
            const pointsToAssign = devices.filter(d =>
                d.device_type === 'pi_point' &&
                d.status === 'activated' &&
                !d.pi_center_id
            );

            if (pointsToAssign.length === 0) {
                if (optionsBox) {
                    optionsBox.innerHTML = '<div class="text-muted small">(Không có Pi Hiện trường nào đang rảnh và đã Activated)</div>';
                }
            } else {
                if (optionsBox) {
                    optionsBox.innerHTML = pointsToAssign.map(p => `
                        <button type="button" class="device-pick-option" data-point-id="${p.id}">
                            <div class="pick-indicator"><i class="bi bi-check-lg"></i></div>
                            <div class="text-start">
                                <strong>${p.name}</strong>
                                <small class="d-block text-muted font-monospace">${p.serial}</small>
                            </div>
                            <span class="badge bg-success ms-auto">✅ Activated</span>
                        </button>
                    `).join('');

                    optionsBox.querySelectorAll('.device-pick-option').forEach(item => {
                        item.addEventListener('click', () => {
                            optionsBox.querySelectorAll('.device-pick-option').forEach(x => x.classList.remove('is-selected'));
                            item.classList.add('is-selected');
                            if (select) select.value = item.dataset.pointId || '';
                        });
                    });
                }
            }
        } catch (e) {
            console.error(e);
            if (optionsBox) optionsBox.innerHTML = '<div class="text-danger small">(Lỗi tải danh sách)</div>';
        }
    }

    /** Call the PUT /assign-to-center endpoint */
    async confirmAssignPiPoint() {
        const centerId = document.getElementById('assign-center-id').value;
        const select = document.getElementById('point-device-select');
        const pointId = select.value;

        if (!pointId) {
            window.toast?.warning("Vui lòng chọn 1 Pi Hiện Trường");
            return;
        }

        try {
            const res = await fetch(`/api/field/pi-devices/${pointId}/assign-to-center`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ pi_center_id: parseInt(centerId) })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi gắn thiết bị');
            }

            window.toast?.success("✅ Đã gắn Pi Hiện Trường thành công!");
            bootstrap.Modal.getInstance(document.getElementById('assignPiPointModal'))?.hide();
            this.loadPiDevices();
        } catch (e) {
            window.toast?.error("❌ " + e.message);
        }
    }

    // ---- Wizard: Pi section (step 3) ----

    /** Called by updateWizardStep() when step 3 is opened in station wizard */
    async loadWizardPendingDevices() {
        const listEl = document.getElementById('pending-devices-list');
        const btnRow = document.getElementById('pi-assign-btn-row');
        const currentPiInfo = document.getElementById('current-pi-info');

        if (!listEl) return;

        listEl.innerHTML = `<div class="text-center py-3">
                    <div class="spinner-border spinner-border-sm text-primary"></div>
                    <small class="ms-2 text-muted">Đang tải...</small>
                </div>`;

        try {
            // 1. Check if this station already has an assigned Pi
            const allRes = await fetch('/api/field/pi-devices', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            const allDevices = await allRes.json();
            const assignedPi = allDevices.find(d => d.station_id === this.currentStationId && d.status === 'assigned' && d.device_type !== 'pi_point');

            if (assignedPi && currentPiInfo) {
                currentPiInfo.style.display = 'flex';
                currentPiInfo.style.alignItems = 'center';
                const piNameEl = document.getElementById('current-pi-name');
                if (piNameEl) piNameEl.textContent = `${assignedPi.name} (${assignedPi.serial})`;
                this._assignedPiId = assignedPi.id;
            } else if (currentPiInfo) {
                currentPiInfo.style.display = 'none';
                this._assignedPiId = null;
            }

            // 2. Load available Pi (activated, not assigned)
            const available = allDevices.filter(d => d.status === 'activated' && d.device_type !== 'pi_point');

            if (available.length === 0) {
                listEl.innerHTML = `<p class="text-muted small">
                Không có Pi nào đã kích hoạt và chưa được gán.
                <a href="#" onclick="event.preventDefault(); bootstrap.Tab.getOrCreateInstance(document.querySelector('[data-bs-target=&apos;#tab-pi&apos;]')).show(); window.adminManager.loadPiDevices();">
                    Đến tab Pi Devices để kích hoạt
                </a>
            </p>`;
                if (btnRow) btnRow.style.display = 'none';
                return;
            }

            listEl.innerHTML = `
                <div class="list-group list-group-flush">
                    ${available.map(d => `
                    <button type="button" class="list-group-item list-group-item-action d-flex gap-3 align-items-center wizard-pi-option"
                           data-pi-id="${d.id}" style="cursor:pointer; background:transparent; border-color:var(--border-color)">
                        <div class="pick-indicator"><i class="bi bi-check-lg"></i></div>
                        <div class="text-start">
                            <strong class="font-monospace">${d.name}</strong>
                            <small class="d-block text-muted font-monospace">${d.serial}</small>
                        </div>
                        <span class="badge bg-success ms-auto">✅ Sẵn sàng</span>
                    </button>
                `).join('')}
                </div>`;

            if (btnRow) btnRow.style.display = 'block';
            this._selectedWizardPiId = null;

            // Show assign button row only when a Pi is selected
            listEl.querySelectorAll('.wizard-pi-option').forEach(r => {
                r.addEventListener('click', () => {
                    listEl.querySelectorAll('.wizard-pi-option').forEach(x => x.classList.remove('is-selected'));
                    r.classList.add('is-selected');
                    this._selectedWizardPiId = parseInt(r.dataset.piId, 10);
                    if (btnRow) btnRow.style.display = 'block';
                });
            });

        } catch (e) {
            listEl.innerHTML = '<p class="text-danger small">Lỗi tải danh sách Pi</p>';
            console.error(e);
        }
    }

    /** Assign the selected Pi (from wizard radio) to the current station */
    async assignSelectedPiToStation() {
        const piId = this._selectedWizardPiId;
        if (!piId) {
            window.toast?.warning('Vui lòng chọn một Pi');
            return;
        }
        try {
            const res = await fetch(`/api/field/pi-devices/${piId}/assign`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ station_id: this.currentStationId })
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi gán trạm');
            }
            const data = await res.json();
            window.toast?.success(`✅ Đã gán Pi vào trạm "${data.station_name}"`);
            // Reload the wizard Pi section
            this.loadWizardPendingDevices();
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

    /** Unassign the currently-assigned Pi from the current station (wizard) */
    async unassignPiFromStation() {
        if (!this._assignedPiId) return;
        try {
            const res = await fetch(`/api/field/pi-devices/${this._assignedPiId}/unassign`, {
                method: 'PUT',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!res.ok) throw new Error('Lỗi');
            window.toast?.success('✅ Đã bỏ gán Pi');
            this._assignedPiId = null;
            this.loadWizardPendingDevices();
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }
}
window.applyAdminFeature(AdminPiCenterFeature);
})();
