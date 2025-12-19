// =============================================
// AUTHENTICATION HANDLER ( frontend/js/auth.js )
// =============================================

class AuthManager {
    constructor() {
        this.token = localStorage.getItem('token');
        this.user = null;
    }

    isAuthenticated() {
        return !!this.token;
    }

    getUserInfo() {
        if (!this.token) return null;
        
        try {
            const base64Url = this.token.split('.')[1];
            const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
            const jsonPayload = decodeURIComponent(
                atob(base64).split('').map(c => 
                    '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
                ).join('')
            );
            
            return JSON.parse(jsonPayload);
        } catch (e) {
            console.error('Token decode error:', e);
            this.logout();
            return null;
        }
    }

    async login(username, password) {
        try {
            const formData = new URLSearchParams();
            formData.append('username', username);
            formData.append('password', password);

            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: formData
            });

            if (!response.ok) {
                if (response.status === 401) {
                    throw new Error('Sai tài khoản hoặc mật khẩu');
                }
                throw new Error('Lỗi đăng nhập. Vui lòng thử lại.');
            }

            const data = await response.json();
            
            this.token = data.access_token;
            localStorage.setItem('token', data.access_token);
            this.user = this.getUserInfo();
            
            return { success: true, user: this.user };

        } catch (error) {
            console.error('Login error:', error);
            return { success: false, error: error.message };
        }
    }

    logout() {
        this.token = null;
        this.user = null;
        localStorage.removeItem('token');
        sessionStorage.removeItem('justLoggedIn');
        window.location.href = '/';
    }

    // ✅ UNIVERSAL: Works for both Landing & Map pages
    updateAuthUI() {
        console.log('🔄 [AUTH] Updating UI...');
        
        const authBtn = document.getElementById('auth-btn');
        if (!authBtn) {
            console.warn('⚠️ [AUTH] Auth button not found');
            return;
        }

        if (this.isAuthenticated()) {
            const user = this.getUserInfo();
            
            if (!user) {
                console.error('❌ [AUTH] Failed to get user info');
                return;
            }

            console.log('✅ [AUTH] User authenticated:', user.sub, '| Role:', user.role);
            
            // ============================================
            // UPDATE AUTH BUTTON (All Pages)
            // ============================================
            authBtn.innerHTML = `<i class="bi bi-person-check me-1"></i> ${user.sub}`;
            authBtn.classList.remove('btn-primary');
            authBtn.classList.add('btn-outline-danger');
            authBtn.onclick = (e) => {
                e.preventDefault();
                this.logout();
            };
            
            // ============================================
            // LANDING PAGE SPECIFIC
            // ============================================
            const userDisplay = document.getElementById('user-display');
            if (userDisplay) {
                userDisplay.textContent = `Hi, ${user.sub}`;
                userDisplay.classList.remove('d-none');
                console.log('✅ [AUTH] Landing: User display updated');
            }
            
            const adminCard = document.getElementById('admin-card');
            if (adminCard && user.role === 'admin') {
                adminCard.classList.remove('d-none');
                console.log('✅ [AUTH] Landing: Admin card shown');
            }
            
            // ============================================
            // MAP PAGE SPECIFIC
            // ============================================
            const adminNavBtn = document.getElementById('admin-nav-btn');
            if (adminNavBtn) {
                if (user.role === 'admin') {
                    adminNavBtn.style.display = 'inline-flex';
                    console.log('✅ [AUTH] Map: Admin button shown');
                } else {
                    adminNavBtn.style.display = 'none';
                    console.log('🔒 [AUTH] Map: Admin button hidden (not admin)');
                }
            }
            
        } else {
            console.log('ℹ️ [AUTH] Not authenticated');
            
            // Reset auth button
            authBtn.innerHTML = '<i class="bi bi-box-arrow-in-right me-1"></i> Đăng nhập';
            authBtn.classList.add('btn-primary');
            authBtn.classList.remove('btn-outline-danger');
            authBtn.onclick = () => window.location.href = '/pages/login.html';
            
            // Hide user elements
            const userDisplay = document.getElementById('user-display');
            if (userDisplay) {
                userDisplay.classList.add('d-none');
            }
            
            // Hide admin elements
            const adminCard = document.getElementById('admin-card');
            if (adminCard) {
                adminCard.classList.add('d-none');
            }
            
            const adminNavBtn = document.getElementById('admin-nav-btn');
            if (adminNavBtn) {
                adminNavBtn.style.display = 'none';
            }
        }
    }

    requireAuth(redirectUrl = '/pages/login.html') {
        if (!this.isAuthenticated()) {
            window.location.href = redirectUrl;
            return false;
        }
        return true;
    }

    requireAdmin() {
        const user = this.getUserInfo();
        if (!user || user.role !== 'admin') {
            alert('Bạn không có quyền truy cập trang này');
            window.location.href = '/';
            return false;
        }
        return true;
    }

    async apiFetch(url, options = {}) {
        if (!this.token) {
            window.location.href = '/pages/login.html';
            return;
        }

        const headers = {
            ...options.headers,
            'Authorization': `Bearer ${this.token}`
        };

        const response = await fetch(url, { ...options, headers });

        if (response.status === 401) {
            this.logout();
            return;
        }

        return response;
    }
}

// ============================================
// INITIALIZATION
// ============================================
window.authManager = new AuthManager();

const initAuthUI = () => {
    console.log('🚀 [AUTH] Initializing UI...');
    
    if (!window.authManager) {
        console.error('❌ [AUTH] AuthManager not available!');
        return;
    }
    
    // Try immediately
    window.authManager.updateAuthUI();
    
    // Retry with delays (handle timing issues)
    setTimeout(() => window.authManager.updateAuthUI(), 100);
    setTimeout(() => window.authManager.updateAuthUI(), 300);
    setTimeout(() => window.authManager.updateAuthUI(), 500);
};

// Run on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAuthUI);
} else {
    initAuthUI();
}

console.log('✅ [AUTH] AuthManager loaded');