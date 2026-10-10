(() => {
class AdminProvisioningFeature extends window.AdminManager {
    // =========================================================================
    // PENDING DEVICES (ADMIN PROVISIONING)
    // =========================================================================

    async loadAdminPendingDevices() {
        try {
            const res = await fetch('/api/admin/devices/pending', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) throw new Error('Không thể tải danh sách thiết bị chờ');

            const devices = await res.json();
            this.renderPendingDevices(devices);
        } catch (e) {
            console.error('Error loading pending devices:', e);
            window.toast?.error('Không lấy được danh sách Pi chờ');
        }
    }

    renderPendingDevices(devices) {
        const container = document.getElementById('pending-devices-list');
        if (!container) return;

        if (!devices || devices.length === 0) {
            container.innerHTML = `<div class="text-muted small p-3">Không có Pi chờ kích hoạt</div>`;
            return;
        }

        const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[char]);
        container.innerHTML = devices.map((d, index) => `
            <div class="pending-device-card border rounded mb-2 p-3" data-device-index="${index}">
                <div class="d-flex align-items-center justify-content-between mb-2">
                    <div>
                        <i class="bi bi-cpu me-2 text-warning"></i>
                        <strong>${escape(d.name || d.device_code)}</strong>
                        <small class="text-muted ms-2">(${escape(d.device_type)})</small>
                    </div>
                    <button type="button" class="btn btn-sm btn-outline-primary" data-device-action="details" aria-expanded="false" aria-controls="pending-detail-${index}">
                        <i class="bi bi-eye me-1"></i>Chi tiết
                    </button>
                </div>
                <div class="small text-muted">
                    Đăng ký: ${new Date((d.created_at || 0) * 1000).toLocaleString()}
                </div>
                <div id="pending-detail-${index}" class="mt-2" hidden>
                    <div class="bg-body-tertiary rounded p-3 mb-2">
                        <div class="mb-2">
                            <label class="form-label small fw-bold mb-1">Serial / Device Code:</label>
                            <div class="font-monospace bg-dark text-success p-2 rounded" style="font-size: 1.1rem; letter-spacing: 1px;">
                                ${escape(d.device_code)}
                            </div>
                        </div>
                        <div class="mb-2">
                            <label class="form-label small fw-bold mb-1">License:</label>
                            <div class="font-monospace text-muted small" data-license-display>
                                ${d.config?.license ? '<span class="text-success"><i class="bi bi-check-circle me-1" aria-hidden="true"></i>' + escape(d.config.license) + '</span>' : '<span class="text-warning"><i class="bi bi-exclamation-triangle me-1" aria-hidden="true"></i>Chưa có license</span>'}
                            </div>
                        </div>
                    </div>
                    <div class="d-flex gap-2">
                        <button type="button" class="btn btn-sm btn-warning flex-fill" data-device-action="provision">
                            <i class="bi bi-key me-1"></i>Tạo Key & Gán vào trạm
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-secondary" data-device-action="license">
                            <i class="bi bi-key me-1"></i>Chỉ tạo Key
                        </button>
                    </div>
                </div>
            </div>
        `).join('');
        container.querySelectorAll('[data-device-index]').forEach(card => {
            card.dataset.deviceCode = String(devices[Number(card.dataset.deviceIndex)].device_code);
        });
        container.querySelectorAll('[data-device-action]').forEach(button => {
            button.addEventListener('click', async () => {
                const card = button.closest('[data-device-index]');
                const device = devices[Number(card?.dataset.deviceIndex)];
                if (!device) return;
                const action = button.dataset.deviceAction;
                if (action === 'details') {
                    const detail = card.querySelector('[id^="pending-detail-"]');
                    detail.hidden = !detail.hidden;
                    button.setAttribute('aria-expanded', String(!detail.hidden));
                    return;
                }
                if (card.dataset.busy) return;
                card.dataset.busy = 'true';
                card.setAttribute('aria-busy', 'true');
                const actions = card.querySelectorAll('[data-device-action]:not([data-device-action="details"])');
                actions.forEach(item => { item.disabled = true; });
                const previousLabel = button.innerHTML;
                button.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Đang xử lý…';
                try {
                    if (action === 'provision') await this.generateAndProvision(device.device_code);
                    if (action === 'license') await this.generateLicense(device.device_code);
                } finally {
                    button.innerHTML = previousLabel;
                    actions.forEach(item => { item.disabled = false; });
                    card.removeAttribute('aria-busy');
                    delete card.dataset.busy;
                }
            });
        });
    }

    async generateLicense(device_code) {
        try {
            const res = await fetch('/api/admin/devices/generate-license', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ device_code: device_code })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi tạo license');
            }

            const data = await res.json();

            // Update license display
            const licenseEl = [...document.querySelectorAll('#pending-devices-list [data-device-index]')]
                .find(card => card.dataset.deviceCode === device_code)
                ?.querySelector('[data-license-display]');
            if (licenseEl) {
                licenseEl.replaceChildren();
                const value = document.createElement('span');
                value.className = 'text-success';
                value.textContent = `✓ ${data.license}`;
                licenseEl.appendChild(value);
                if (data.pushed) {
                    const pushed = document.createElement('span');
                    pushed.className = 'badge bg-info ms-1';
                    pushed.textContent = 'Đã gửi qua MQTT';
                    licenseEl.appendChild(pushed);
                }
            }

            window.toast?.success(`✅ License tạo xong${data.pushed ? ' & đã gửi đến Pi' : ''}`);
            return data;
        } catch (e) {
            console.error('Generate license error:', e);
            window.toast?.error('❌ ' + e.message);
        }
    }

    async generateAndProvision(device_code) {
        if (!this.currentStationId) {
            window.toast?.warning('Lưu trạm trước khi gán thiết bị');
            return;
        }

        if (!this.confirmDeviceProvisionWarnings(device_code)) return;

        try {
            // Step 1: Generate license
            window.toast?.info('🔑 Đang tạo license...');
            const licenseData = await this.generateLicense(device_code);
            if (!licenseData) return;

            // Step 2: Provision (assign to station) with license
            window.toast?.info('📡 Đang gán thiết bị vào trạm...');
            const res = await fetch('/api/admin/devices/provision', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    device_code: device_code,
                    station_id: this.currentStationId,
                    license: licenseData.license
                })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi khi gán thiết bị');
            }

            window.toast?.success(`✅ Pi ${device_code} đã gán vào trạm & license đã gửi!`);

            // Refresh pending list (device should disappear)
            this.loadAdminPendingDevices();
        } catch (e) {
            console.error('Generate & provision error:', e);
            window.toast?.error('❌ ' + e.message);
        }
    }

    async provisionDevice(device_code) {
        if (!this.currentStationId) {
            window.toast?.warning('Lưu trạm trước khi gán thiết bị');
            return;
        }

        if (!this.confirmDeviceProvisionWarnings(device_code)) return;

        const license = prompt('Nhập mã license/serial để lưu (hoặc để trống):');
        if (license === null) return; // cancelled

        try {
            const res = await fetch('/api/admin/devices/provision', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ device_code: device_code, station_id: this.currentStationId, license: license })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Lỗi khi gán thiết bị');
            }

            window.toast?.success('✅ Thiết bị đã được gán thành công');
            // refresh lists
            this.loadAdminPendingDevices();
            // reload station devices view if open
            this.editStation(this.currentStationId);
        } catch (e) {
            console.error('Provision error:', e);
            window.toast?.error('❌ ' + e.message);
        }
    }


}
window.applyAdminFeature(AdminProvisioningFeature);
})();
