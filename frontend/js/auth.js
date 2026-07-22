// =============================================
// AUTHENTICATION HANDLER - COMPLETE FIXED VERSION
// =============================================

class AuthManager {
    constructor() {
        this.token = localStorage.getItem('token') || sessionStorage.getItem('token');
        this.user = null;
        try {
            const cachedUser = sessionStorage.getItem('auth_user');
            this.user = this.token && cachedUser ? JSON.parse(cachedUser) : null;
        } catch (_) {
            sessionStorage.removeItem('auth_user');
        }
        this.tokenCheckInterval = null;
        this._isVerifyingToken = false;
        this._verifyPromise = null;
        this._unauthorizedCheckPromise = null;
    }

    // ✅ CRITICAL: Verify token on init
    async init() {
        console.log('🔒 [AUTH] Initializing...');

        if (this.token) {
            const isValid = await this.verifyToken();

            if (isValid === false) {
                console.warn('⚠️ [AUTH] Token expired or invalid');
                this.logout(false); // Don't redirect immediately
                return false;
            }

            if (isValid === null) {
                console.warn('⚠️ [AUTH] Server unavailable; retaining the existing session until verification recovers');
            } else {
                console.log('✅ [AUTH] Token valid');
            }

            // Keep validation lightweight; protected requests still confirm a
            // real 401 immediately through handleUnauthorizedResponse().
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
            const hadUser = Boolean(this.user);
            const isValid = await this.verifyToken();
            if (isValid === false) {
                console.warn('⚠️ [AUTH] Token expired during session');
                this.logout();
            } else if (isValid === true && !hadUser) {
                this.updateAuthUI();
            }
        }, 60 * 1000);
    }

    // ✅ NEW: Verify token by calling backend
    async verifyToken() {
        if (!this.token) return false;

        if (this._verifyPromise) return this._verifyPromise;

        const verification = (async () => {
            this._isVerifyingToken = true;
            try {
                const res = await fetch('/api/auth/me', {
                    headers: {
                        'Authorization': `Bearer ${this.token}`
                    }
                });

                if (res.ok) {
                    this.user = await res.json();
                    sessionStorage.setItem('auth_user', JSON.stringify(this.user));
                    return true;
                }
                if (res.status === 401) return false;

                console.warn(`⚠️ [AUTH] Verification temporarily unavailable (HTTP ${res.status})`);
                return null;
            } catch (e) {
                console.warn('⚠️ [AUTH] Verification network error; session retained:', e);
                return null;
            } finally {
                this._isVerifyingToken = false;
            }
        })();
        this._verifyPromise = verification;
        try {
            return await verification;
        } finally {
            if (this._verifyPromise === verification) this._verifyPromise = null;
        }
    }

    handleUnauthorizedResponse(source = '') {
        if (!this.token || this._isVerifyingToken) return;
        if (this._unauthorizedCheckPromise) return this._unauthorizedCheckPromise;

        const confirmation = (async () => {
            await new Promise(resolve => setTimeout(resolve, 200));
            const isValid = await this.verifyToken();
            if (isValid !== false || !this.token) {
                if (isValid === null) {
                    console.warn('⚠️ [AUTH] Could not confirm 401; preserving session:', source);
                } else {
                    console.warn('⚠️ [AUTH] Endpoint returned 401 but token remains valid:', source);
                }
                return;
            }

            if (!sessionStorage.getItem('kicked_alert_shown')) {
                sessionStorage.setItem('kicked_alert_shown', 'true');
                alert('Tài khoản của bạn đã bị khóa hoặc phiên đăng nhập hết hạn.');
            }
            this.logout(true);
        })().finally(() => {
            if (this._unauthorizedCheckPromise === confirmation) {
                this._unauthorizedCheckPromise = null;
            }
        });
        this._unauthorizedCheckPromise = confirmation;
        return confirmation;
    }

    isAuthenticated() {
        return !!this.token && !!this.user;
    }

    getUserInfo() {
        return this.user;
    }

    async login(username, password, rememberMe = false) {
        try {
            const formData = new URLSearchParams();
            formData.append('username', username);
            formData.append('password', password);
            if (rememberMe) {
                formData.append('scope', 'remember_me');
            }

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

            // Remember Me: localStorage = permanent, sessionStorage = session only
            if (rememberMe) {
                localStorage.setItem('token', data.access_token);
                localStorage.setItem('rememberMe', 'true');
            } else {
                sessionStorage.setItem('token', data.access_token);
                localStorage.removeItem('token');
                localStorage.removeItem('rememberMe');
            }

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

        // Clear data from both storages
        this.token = null;
        this.user = null;
        localStorage.removeItem('token');
        localStorage.removeItem('rememberMe');
        sessionStorage.removeItem('token');
        sessionStorage.removeItem('auth_user');
        sessionStorage.removeItem('justLoggedIn');
        sessionStorage.removeItem('loginReturnView');
        sessionStorage.removeItem('kicked_alert_shown');

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
            console.debug('[AUTH] Auth button not mounted yet');
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
            if (adminCard && (this.user.role === 'admin' || this.user.role === 'operator')) {
                adminCard.classList.remove('d-none');
                console.log('✅ [AUTH] Landing: Admin card shown');
            }

            // ============================================
            // MAP PAGE SPECIFIC
            // ============================================
            const adminNavBtn = document.getElementById('admin-nav-btn');
            if (adminNavBtn) {
                if (this.user.role === 'admin' || this.user.role === 'operator') {
                    adminNavBtn.style.display = 'inline-flex';
                    console.log('✅ [AUTH] Map: Admin button shown');
                } else {
                    adminNavBtn.style.display = 'none';
                    console.log('🔒 [AUTH] Map: Admin button hidden (viewer)');
                }
            }

            // Show data analysis buttons for authenticated users (viewer, admin, operator)
            const btnLongTerm = document.getElementById('btn-long-term');
            if (btnLongTerm) {
                btnLongTerm.classList.remove('d-none');
                console.log('✅ [AUTH] Map: Data analysis buttons shown');
            }

        } else {
            console.log('ℹ️ [AUTH] Not authenticated');

            // Reset auth button
            authBtn.innerHTML = '<i class="bi bi-box-arrow-in-right me-1"></i> <span>Login</span>';
            authBtn.classList.add('btn-primary');
            authBtn.classList.remove('btn-outline-danger');
            authBtn.onclick = () => {
                const currentPath = window.location.pathname;
                const currentView = currentPath === '/management' || currentPath === '/admin'
                    ? 'admin'
                    : 'map';
                sessionStorage.setItem('loginReturnView', currentView);
                if (typeof window.appNavigate === 'function') {
                    sessionStorage.setItem('openLandingLogin', 'true');
                    window.location.href = '/';
                    return;
                }
                sessionStorage.setItem('openLandingLogin', 'true');
                window.location.href = '/';
            };

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

            // Hide data analysis buttons for unauthenticated users (guests)
            const btnLongTerm = document.getElementById('btn-long-term');
            if (btnLongTerm) {
                btnLongTerm.classList.add('d-none');
                console.log('🔒 [AUTH] Map: Data analysis buttons hidden (guest)');
            }
        }
    }

    requireAuth(redirectUrl = '/') {
        if (!this.isAuthenticated()) {
            sessionStorage.setItem('openLandingLogin', 'true');
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
            sessionStorage.setItem('openLandingLogin', 'true');
            window.location.href = '/';
            return;
        }

        const headers = {
            ...options.headers,
            'Authorization': `Bearer ${this.token}`
        };

        const response = await fetch(url, { ...options, headers });

        if (response.status === 401) {
            void this.handleUnauthorizedResponse(url);
        }

        return response;
    }
}

// ============================================
// GLOBAL FETCH INTERCEPTOR
// ============================================
const originalFetch = window.fetch;
window.fetch = async function (...args) {
    const response = await originalFetch(...args);
    if (response.status === 401 && window.authManager && window.authManager.isAuthenticated() && !window.authManager._isVerifyingToken) {
        const requestUrl = typeof args[0] === 'string' ? args[0] : args[0]?.url;
        console.warn('⚠️ [AUTH] 401 detected; confirming token before logout:', requestUrl || 'unknown request');
        void window.authManager.handleUnauthorizedResponse(requestUrl || 'unknown request');
    }
    return response;
};

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
