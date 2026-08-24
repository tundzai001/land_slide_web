// =============================================
// TOAST NOTIFICATION SYSTEM (OPTIMIZED)
// =============================================

class ToastNotification {
    constructor() {
        this.injectStyles();
        this.container = this.createContainer();
    }

    // 1. Chèn CSS Animation một lần duy nhất lúc khởi tạo
    injectStyles() {
        if (document.getElementById('toast-animations')) return;
        
        const style = document.createElement('style');
        style.id = 'toast-animations';
        style.textContent = `
            @keyframes slideInRight {
                from { opacity: 0; transform: translateX(100%); }
                to { opacity: 1; transform: translateX(0); }
            }
            @keyframes slideOutRight {
                from { opacity: 1; transform: translateX(0); }
                to { opacity: 0; transform: translateX(100%); }
            }
            @media (max-width: 576px) {
                #toast-notification-container {
                    left: 20px;
                    max-width: none !important;
                }
            }
        `;
        document.head.appendChild(style);
    }

    createContainer() {
        let container = document.getElementById('toast-notification-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-notification-container';
            container.style.cssText = `
                position: fixed;
                top: 20px; /* Cách đỉnh 20px để dễ nhìn hơn */
                right: 20px;
                z-index: var(--z-toast); /* Above drawers and modals */
                display: flex;
                flex-direction: column;
                gap: 10px;
                max-width: 350px;
                pointer-events: none; /* Để click xuyên qua vùng trống */
            `;
            document.body.appendChild(container);
        }
        return container;
    }

    show(message, type = 'info', duration = 4000) {
        const toast = document.createElement('div');
        
        // Icon Bootstrap
        const icons = {
            success: 'bi-check-circle-fill',
            error:   'bi-x-octagon-fill',
            warning: 'bi-exclamation-triangle-fill',
            info:    'bi-info-circle-fill',
            danger:  'bi-fire'
        };

        // Màu sắc giao diện tối/hiện đại
        const colors = {
            success: { bg: '#10b981', border: '#059669', iconColor: '#fff' },
            error:   { bg: '#ef4444', border: '#b91c1c', iconColor: '#fff' },
            warning: { bg: '#f59e0b', border: '#d97706', iconColor: '#fff', text: '#fff' },
            info:    { bg: '#3b82f6', border: '#2563eb', iconColor: '#fff' },
            danger:  { bg: '#dc2626', border: '#991b1b', iconColor: '#fff' }
        };

        const config = colors[type] || colors.info;
        const textColor = config.text || '#ffffff';

        toast.className = 'toast-notification';
        toast.style.cssText = `
            background: ${config.bg};
            color: ${textColor};
            padding: 14px 18px;
            border-radius: 8px;
            border-left: 5px solid ${config.border};
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
            display: flex;
            align-items: flex-start;
            gap: 12px;
            font-family: system-ui, -apple-system, sans-serif;
            font-size: 0.95rem;
            line-height: 1.5;
            font-weight: 500;
            animation: slideInRight 0.3s cubic-bezier(0.23, 1, 0.32, 1);
            cursor: pointer;
            pointer-events: auto; /* Cho phép click vào toast */
            transition: transform 0.2s ease, opacity 0.2s ease;
            backdrop-filter: blur(4px);
            min-width: 300px;
        `;

        // Nội dung HTML
        toast.innerHTML = `
            <i class="bi ${icons[type]}" style="font-size: 1.25rem; color: ${config.iconColor}; margin-top: 2px;"></i>
            <div style="flex: 1;">${message}</div>
            <button style="background:none; border:none; color:white; opacity:0.7; cursor:pointer; padding:0;">
                <i class="bi bi-x-lg"></i>
            </button>
        `;

        // Sự kiện Hover
        toast.onmouseenter = () => {
            toast.style.transform = 'translateX(-5px)';
            // Tạm dừng auto-dismiss khi hover (nếu muốn)
        };
        toast.onmouseleave = () => {
            toast.style.transform = 'translateX(0)';
        };

        // Sự kiện Click để đóng
        const closeBtn = toast.querySelector('button');
        closeBtn.onclick = (e) => {
            e.stopPropagation();
            this.dismiss(toast);
        };
        toast.onclick = () => this.dismiss(toast);

        // Thêm vào container
        this.container.appendChild(toast);

        // Auto dismiss
        if (duration > 0) {
            setTimeout(() => {
                // Kiểm tra xem toast còn trong DOM không trước khi dismiss
                if (toast.isConnected) this.dismiss(toast);
            }, duration);
        }

        return toast;
    }

    dismiss(toast) {
        toast.style.animation = 'slideOutRight 0.4s cubic-bezier(0.23, 1, 0.32, 1) forwards';
        setTimeout(() => {
            if (toast.isConnected) toast.remove();
        }, 400);
    }

    // Các hàm tiện ích
    success(message, duration) { return this.show(message, 'success', duration); }
    error(message, duration) { return this.show(message, 'error', duration); }
    warning(message, duration) { return this.show(message, 'warning', duration); }
    info(message, duration) { return this.show(message, 'info', duration); }
    danger(message, duration) { return this.show(message, 'danger', duration); }
}

// Khởi tạo global
window.toast = new ToastNotification();
