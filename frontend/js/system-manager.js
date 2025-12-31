// =====================================================
// SYSTEM MANAGER - Server-verified System Password
// =====================================================

class SystemManager {
    constructor() {
        this.token = localStorage.getItem('token');
        this.isVerified = false;
        
        // Khởi tạo chặn tab ngay lập tức
        this.setupTabInterceptor();
    }

    setupTabInterceptor() {
        // Tìm nút bấm mở tab System
        const systemTabBtn = document.querySelector('button[data-bs-target="#tab-system"]');
        
        if (!systemTabBtn) return;

        // ✅ QUAN TRỌNG: Dùng sự kiện 'show.bs.tab' thay vì 'click'
        // Sự kiện này kích hoạt TRƯỚC khi tab chuyển đổi
        systemTabBtn.addEventListener('show.bs.tab', (event) => {
            if (!this.isVerified) {
                // ⛔ CHẶN ĐỨNG việc chuyển tab ngay lập tức
                event.preventDefault(); 
                
                // Hiện bảng nhập mật khẩu
                this.showPasswordShield();
            }
            // Nếu đã verified (isVerified = true) thì cho phép chuyển tab bình thường
        });
    }

    showPasswordShield() {
        const shield = document.getElementById('password-shield');
        const input = document.getElementById('system-password-input');
        const error = document.getElementById('password-error');
        
        if (shield) {
            shield.style.display = 'flex';
            
            if (input) {
                input.value = '';
                input.focus();
                
                // Xử lý sự kiện Enter
                input.onkeyup = (e) => {
                    if (e.key === 'Enter') this.verifyPassword();
                    if (error) error.style.display = 'none';
                };
            }
            
            if (error) error.style.display = 'none';
        }
    }

    async verifyPassword() {
        const input = document.getElementById('system-password-input');
        const error = document.getElementById('password-error');
        const errorMsg = document.getElementById('error-message');
        const password = input?.value;

        if (!password) return;

        try {
            // Gọi API kiểm tra
            const res = await fetch('/api/admin/verify-system-password', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ password: password })
            });

            if (res.ok) {
                // ✅ ĐÚNG MẬT KHẨU
                this.isVerified = true;
                window.toast?.success('✅ Xác thực thành công!');
                
                // 1. Ẩn khiên
                const shield = document.getElementById('password-shield');
                if (shield) shield.style.display = 'none';

                // 2. Tự động chuyển sang tab System (vì lúc nãy mình đã chặn nó)
                const systemTabBtn = document.querySelector('button[data-bs-target="#tab-system"]');
                const tabInstance = new bootstrap.Tab(systemTabBtn);
                tabInstance.show();

                // 3. Load dữ liệu
                this.loadSystemConfig();

            } else {
                throw new Error('Mật khẩu không đúng');
            }

        } catch (e) {
            // ❌ SAI MẬT KHẨU
            if (error && errorMsg) {
                errorMsg.textContent = '❌ Sai mật khẩu hệ thống!';
                error.style.display = 'block';
            }
            if (input) {
                input.value = '';
                input.focus();
                input.style.animation = 'shake 0.5s';
                setTimeout(() => { input.style.animation = ''; }, 500);
            }
        }
    }

    cancelPasswordCheck() {
        // Khi ấn hủy, chỉ cần ẩn khiên đi.
        // Vì ta đã chặn chuyển tab ngay từ đầu (event.preventDefault),
        // nên người dùng vẫn đang đứng ở tab cũ (Ví dụ: Database), không bị lọt vào System.
        const shield = document.getElementById('password-shield');
        if (shield) shield.style.display = 'none';
    }

    async loadSystemConfig() {
        try {
            const res = await fetch('/api/admin/system-config', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) throw new Error('Failed to load');

            const config = await res.json();

            // Fill dữ liệu vào form
            if (config.mqtt) {
                document.getElementById('sys-mqtt-broker').value = config.mqtt.broker || '';
                document.getElementById('sys-mqtt-port').value = config.mqtt.port || 1883;
                document.getElementById('sys-reload-interval').value = config.mqtt.topic_reload_interval || 60;
                document.getElementById('sys-mqtt-user').value = config.mqtt.user || '';
                // Không hiển thị password vì bảo mật
            }

            if (config.confirmation) {
                document.getElementById('sys-confirm-gnss').value = config.confirmation.gnss || 3;
                document.getElementById('sys-confirm-rain').value = config.confirmation.rain || 2;
                document.getElementById('sys-confirm-water').value = config.confirmation.water || 3;
                document.getElementById('sys-confirm-imu').value = config.confirmation.imu || 1;
            }

            if (config.save_intervals) {
                document.getElementById('sys-save-gnss').value = config.save_intervals.gnss || 86400;
                document.getElementById('sys-save-rain').value = config.save_intervals.rain || 3600;
                document.getElementById('sys-save-water').value = config.save_intervals.water || 3600;
                document.getElementById('sys-save-imu').value = config.save_intervals.imu || 2592000;
            }

        } catch (e) {
            console.error(e);
            window.toast?.error('Không thể tải cấu hình hệ thống');
        }
    }

    async saveSystemConfig() {
        if (!confirm('⚠️ Bạn có chắc muốn lưu cấu hình toàn hệ thống?\n\nĐiều này sẽ ảnh hưởng tới TẤT CẢ trạm!')) {
            return;
        }

        const config = {
            mqtt: {
                broker: document.getElementById('sys-mqtt-broker').value.trim(),
                port: parseInt(document.getElementById('sys-mqtt-port').value) || 1883,
                user: document.getElementById('sys-mqtt-user').value.trim(),
                password: document.getElementById('sys-mqtt-password').value,
                topic_reload_interval: parseInt(document.getElementById('sys-reload-interval').value) || 60
            },
            confirmation: {
                gnss: parseInt(document.getElementById('sys-confirm-gnss').value) || 3,
                rain: parseInt(document.getElementById('sys-confirm-rain').value) || 2,
                water: parseInt(document.getElementById('sys-confirm-water').value) || 3,
                imu: parseInt(document.getElementById('sys-confirm-imu').value) || 1
            },
            save_intervals: {
                gnss: parseInt(document.getElementById('sys-save-gnss').value) || 86400,
                rain: parseInt(document.getElementById('sys-save-rain').value) || 3600,
                water: parseInt(document.getElementById('sys-save-water').value) || 3600,
                imu: parseInt(document.getElementById('sys-save-imu').value) || 2592000
            }
        };

        try {
            const res = await fetch('/api/admin/system-config', {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(config)
            });

            if (!res.ok) throw new Error('Failed to save');

            window.toast?.success('✅ Đã lưu cấu hình hệ thống!');
            
        } catch (e) {
            window.toast?.error('❌ Lỗi: ' + e.message);
        }
    }

    applyPreset(presetName) {
        // Logic apply preset (nếu cần)
        window.toast?.info('Chức năng Preset đang cập nhật...');
    }
}

// Khởi tạo
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('tab-system')) {
        window.systemManager = new SystemManager();
    }
});