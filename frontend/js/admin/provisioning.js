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

        container.innerHTML = devices.map(d => `
            <div class="pending-device-card border rounded mb-2 p-3" id="pending-${d.device_code}">
                <div class="d-flex align-items-center justify-content-between mb-2">
                    <div>
                        <i class="bi bi-cpu me-2 text-warning"></i>
                        <strong>${d.name || d.device_code}</strong>
                        <small class="text-muted ms-2">(${d.device_type})</small>
                    </div>
                    <button class="btn btn-sm btn-outline-primary" onclick="window.adminManager.showDeviceDetail('${d.device_code}')">
                        <i class="bi bi-eye me-1"></i>Chi tiết
                    </button>
                </div>
                <div class="small text-muted">
                    Đăng ký: ${new Date((d.created_at || 0) * 1000).toLocaleString()}
                </div>
                <div id="detail-${d.device_code}" class="mt-2" style="display:none;">
                    <div class="bg-body-tertiary rounded p-3 mb-2">
                        <div class="mb-2">
                            <label class="form-label small fw-bold mb-1">Serial / Device Code:</label>
                            <div class="font-monospace bg-dark text-success p-2 rounded" style="font-size: 1.1rem; letter-spacing: 1px;">
                                ${d.device_code}
                            </div>
                        </div>
                        <div class="mb-2">
                            <label class="form-label small fw-bold mb-1">License:</label>
                            <div id="license-display-${d.device_code}" class="font-monospace text-muted small">
                                ${d.config?.license ? '<span class="text-success">✅ ' + d.config.license + '</span>' : '<span class="text-warning">⚠ï¸ Chưa có license</span>'}
                            </div>
                        </div>
                    </div>
                    <div class="d-flex gap-2">
                        <button class="btn btn-sm btn-warning flex-fill" onclick="window.adminManager.generateAndProvision('${d.device_code}')">
                            <i class="bi bi-key me-1"></i>Tạo Key & Gán vào trạm
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" onclick="window.adminManager.generateLicense('${d.device_code}')">
                            <i class="bi bi-key me-1"></i>Chỉ tạo Key
                        </button>
                    </div>
                </div>
            </div>
        `).join('');
    }

    showDeviceDetail(device_code) {
        const detailEl = document.getElementById(`detail-${device_code}`);
        if (detailEl) {
            detailEl.style.display = detailEl.style.display === 'none' ? 'block' : 'none';
        }
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
            const licenseEl = document.getElementById(`license-display-${device_code}`);
            if (licenseEl) {
                licenseEl.innerHTML = `<span class="text-success">✅ ${data.license}</span>`;
                if (data.pushed) {
                    licenseEl.innerHTML += ` <span class="badge bg-info">Đã gửi qua MQTT</span>`;
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
