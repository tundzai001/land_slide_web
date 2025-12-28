// =============================================
// AUTHENTICATION HANDLER - COMPLETE FIXED VERSION
// =============================================

class AuthManager {
    constructor() {
        this.token = localStorage.getItem('token');
        this.user = null;
        this.tokenCheckInterval = null;
    }

    // ✅ CRITICAL: Verify token on init
    async init() {
        console.log('🔒 [AUTH] Initializing...');
        
        if (this.token) {
            const isValid = await this.verifyToken();
            
            if (!isValid) {
                console.warn('⚠️ [AUTH] Token expired or invalid');
                this.logout(false); // Don't redirect immediately
                return false;
            }
            
            console.log('✅ [AUTH] Token valid');
            
            // ✅ Start periodic token check (every 5 minutes)
            this.startTokenCheck();
            
            return true;
        }
        
        console.log('ℹ️ [AUTH] No token found');
        return false;
    }

    // ✅ NEW: Periodic token validation
    startTokenCheck() {
        if (this.tokenCheckInterval) {
            clearInterval(this.tokenCheckInterval);
        }
        
        this.tokenCheckInterval = setInterval(async () => {
            const isValid = await this.verifyToken();
            if (!isValid) {
                console.warn('⚠️ [AUTH] Token expired during session');
                this.logout();
            }
        }, 5 * 60 * 1000); // Check every 5 minutes
    }

    // ✅ NEW: Verify token by calling backend
    async verifyToken() {
        if (!this.token) return false;
        
        try {
            const res = await fetch('/api/auth/me', {
                headers: {
                    'Authorization': `Bearer ${this.token}`
                }
            });

            if (res.ok) {
                this.user = await res.json();
                return true;
            } else {
                return false;
            }
        } catch (e) {
            console.error('❌ [AUTH] Verify failed:', e);
            return false;
        }
    }

    isAuthenticated() {
        return !!this.token && !!this.user;
    }

    getUserInfo() {
        return this.user;
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
            
            // Fetch user info immediately
            await this.verifyToken();
            
            // Start token check
            this.startTokenCheck();
            
            return { success: true, user: this.user };

        } catch (error) {
            console.error('Login error:', error);
            return { success: false, error: error.message };
        }
    }

    logout(redirect = true) {
        // Clear interval
        if (this.tokenCheckInterval) {
            clearInterval(this.tokenCheckInterval);
            this.tokenCheckInterval = null;
        }
        
        // Clear data
        this.token = null;
        this.user = null;
        localStorage.removeItem('token');
        sessionStorage.removeItem('justLoggedIn');
        
        // Redirect
        if (redirect) {
            window.location.href = '/';
        }
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
            console.log('✅ [AUTH] User authenticated:', this.user.username, '| Role:', this.user.role);
            
            // ============================================
            // UPDATE AUTH BUTTON (All Pages)
            // ============================================
            authBtn.innerHTML = `<i class="bi bi-person-check me-1"></i> ${this.user.username}`;
            authBtn.classList.remove('btn-primary');
            authBtn.classList.add('btn-outline-danger');
            authBtn.onclick = (e) => {
                e.preventDefault();
                if (confirm('Bạn muốn đăng xuất?')) {
                    this.logout();
                }
            };
            
            // ============================================
            // LANDING PAGE SPECIFIC
            // ============================================
            const userDisplay = document.getElementById('user-display');
            if (userDisplay) {
                userDisplay.textContent = `Hi, ${this.user.username}`;
                userDisplay.classList.remove('d-none');
                console.log('✅ [AUTH] Landing: User display updated');
            }
            
            const adminCard = document.getElementById('admin-card');
            if (adminCard && this.user.role === 'admin') {
                adminCard.classList.remove('d-none');
                console.log('✅ [AUTH] Landing: Admin card shown');
            }
            
            // ============================================
            // MAP PAGE SPECIFIC
            // ============================================
            const adminNavBtn = document.getElementById('admin-nav-btn');
            if (adminNavBtn) {
                if (this.user.role === 'admin') {
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
        if (!this.user || this.user.role !== 'admin') {
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

const initAuthUI = async () => {
    console.log('🚀 [AUTH] Initializing UI...');
    
    if (!window.authManager) {
        console.error('❌ [AUTH] AuthManager not available!');
        return;
    }
    
    // ✅ Verify token first
    await window.authManager.init();
    
    // Update UI
    window.authManager.updateAuthUI();
    
    // ✅ Retry with delays (handle timing issues)
    setTimeout(() => window.authManager.updateAuthUI(), 100);
    setTimeout(() => window.authManager.updateAuthUI(), 300);
};

// Run on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAuthUI);
} else {
    initAuthUI();
}

console.log('✅ [AUTH] AuthManager loaded');