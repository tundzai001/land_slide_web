// =============================================
// TOAST NOTIFICATION SYSTEM ( frontend/js/toast-notifications.js )
// Hiển thị thông báo đẹp thay thế alert()
// =============================================

class ToastNotification {
    constructor() {
        this.container = this.createContainer();
    }

    createContainer() {
        let container = document.getElementById('toast-notification-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-notification-container';
            container.style.cssText = `
                position: fixed;
                top: 80px;
                right: 20px;
                z-index: 9999;
                display: flex;
                flex-direction: column;
                gap: 12px;
                max-width: 400px;
            `;
            document.body.appendChild(container);
        }
        return container;
    }

    show(message, type = 'info', duration = 4000) {
        const toast = document.createElement('div');
        const icons = {
            success: 'bi-check-circle-fill',
            error: 'bi-x-circle-fill',
            warning: 'bi-exclamation-triangle-fill',
            info: 'bi-info-circle-fill',
            danger: 'bi-x-octagon-fill'
        };

        const colors = {
            success: { bg: 'rgba(81, 207, 102, 0.95)', border: '#51cf66' },
            error: { bg: 'rgba(250, 82, 82, 0.95)', border: '#fa5252' },
            warning: { bg: 'rgba(255, 212, 59, 0.95)', border: '#ffd43b', text: '#212529' },
            info: { bg: 'rgba(74, 172, 254, 0.95)', border: '#4facfe' },
            danger: { bg: 'rgba(220, 53, 69, 0.95)', border: '#dc3545' }
        };

        const config = colors[type] || colors.info;
        const textColor = config.text || '#ffffff';

        toast.className = 'toast-notification';
        toast.style.cssText = `
            background: ${config.bg};
            color: ${textColor};
            padding: 16px 20px;
            border-radius: 12px;
            border-left: 4px solid ${config.border};
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            backdrop-filter: blur(10px);
            display: flex;
            align-items: center;
            gap: 12px;
            font-weight: 500;
            animation: slideInRight 0.4s cubic-bezier(0.23, 1, 0.32, 1);
            cursor: pointer;
            transition: all 0.3s ease;
        `;

        toast.innerHTML = `
            <i class="bi ${icons[type]}" style="font-size: 1.5rem;"></i>
            <div style="flex: 1; line-height: 1.4;">${message}</div>
            <i class="bi bi-x" style="font-size: 1.2rem; opacity: 0.7;"></i>
        `;

        // Hover effect
        toast.onmouseenter = () => {
            toast.style.transform = 'translateX(-5px)';
            toast.style.boxShadow = '0 12px 48px rgba(0, 0, 0, 0.4)';
        };

        toast.onmouseleave = () => {
            toast.style.transform = 'translateX(0)';
            toast.style.boxShadow = '0 8px 32px rgba(0, 0, 0, 0.3)';
        };

        // Click to dismiss
        toast.onclick = () => this.dismiss(toast);

        // Add animation
        const style = document.createElement('style');
        style.textContent = `
            @keyframes slideInRight {
                from {
                    opacity: 0;
                    transform: translateX(100px);
                }
                to {
                    opacity: 1;
                    transform: translateX(0);
                }
            }
            @keyframes slideOutRight {
                to {
                    opacity: 0;
                    transform: translateX(100px);
                }
            }
        `;
        if (!document.getElementById('toast-animations')) {
            style.id = 'toast-animations';
            document.head.appendChild(style);
        }

        this.container.appendChild(toast);

        // Auto dismiss
        if (duration > 0) {
            setTimeout(() => this.dismiss(toast), duration);
        }

        return toast;
    }

    dismiss(toast) {
        toast.style.animation = 'slideOutRight 0.3s ease forwards';
        setTimeout(() => toast.remove(), 300);
    }

    // Convenience methods
    success(message, duration) {
        return this.show(message, 'success', duration);
    }

    error(message, duration) {
        return this.show(message, 'error', duration);
    }

    warning(message, duration) {
        return this.show(message, 'warning', duration);
    }

    info(message, duration) {
        return this.show(message, 'info', duration);
    }

    danger(message, duration) {
        return this.show(message, 'danger', duration);
    }
}

// Initialize globally
window.toast = new ToastNotification();