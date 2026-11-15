// =============================================
// AUTHENTICATION HANDLER - COMPLETE FIXED VERSION
// =============================================

const authenticatedBlobUrls = new Map();

class AuthManager {
    constructor() {
        this.token = window.authSession?.getToken() || null;
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
        this.authzDeadlineAt = 0;
        this.authzDeadlineTimer = null;
        this.authzLocked = false;
        addEventListener('pageshow', () => this.enforceAuthzDeadline());
        addEventListener('visibilitychange', () => {
            if (!document.hidden) this.enforceAuthzDeadline();
        });
    }

    armAuthzDeadline(user) {
        const graceSeconds = Math.max(60, Math.min(Number(user?.private_authz_grace_seconds) || 300, 900));
        this.authzDeadlineAt = Date.now() + graceSeconds * 1000;
        this.authzLocked = false;
        document.documentElement.removeAttribute('data-authz-lock');
        if (this.authzDeadlineTimer) clearTimeout(this.authzDeadlineTimer);
        this.authzDeadlineTimer = setTimeout(() => this.enforceAuthzDeadline(), graceSeconds * 1000 + 20);
    }

    enforceAuthzDeadline() {
        if (!this.authzDeadlineAt || Date.now() < this.authzDeadlineAt) return false;
        this.authzLocked = true;
        document.documentElement.setAttribute('data-authz-lock', 'expired');
        window.revokeAuthenticatedBlobUrls?.();
        const privateElements = document.querySelectorAll('[data-private-content]');
        privateElements.forEach(element => {
            element.setAttribute('inert', '');
            element.setAttribute('aria-hidden', 'true');
        });
        if (privateElements.length && !document.getElementById('authz-expired-dialog')) {
            const dialog = document.createElement('div');
            dialog.id = 'authz-expired-dialog';
            dialog.className = 'authz-expired-dialog';
            dialog.setAttribute('role', 'alertdialog');
            dialog.setAttribute('aria-modal', 'true');
            dialog.setAttribute('aria-labelledby', 'authz-expired-title');
            dialog.innerHTML = '<div class="authz-expired-card"><i class="bi bi-shield-exclamation" aria-hidden="true"></i><h2 id="authz-expired-title">Phiên quyền đã hết hạn</h2><p>Quyền truy cập đã thay đổi hoặc phiên cần được xác thực lại. Hãy đăng nhập lại để tiếp tục.</p><a class="btn btn-primary" href="/login?return_to=' + encodeURIComponent(location.pathname) + '">Đăng nhập lại</a></div>';
            document.body.appendChild(dialog);
            dialog.querySelector('a')?.focus({ preventScroll: true });
        }
        window.dispatchEvent(new CustomEvent('authzExpired'));
        return true;
    }

    // ✅ CRITICAL: Verify token on init
    async init() {
        console.log('🔒 [AUTH] Initializing...');

        if (this.token) {
            const isValid = await this.verifyToken();

            if (isValid === false) {
                console.warn('⚠️ [AUTH] Token expired or invalid');
                await this.logout(false); // Don't redirect immediately
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
                void this.logout();
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
                    },
                    signal: AbortSignal.timeout(10000),
                    cache: 'no-store',
                });

                if (res.ok) {
                    const previousScopeHash = this.user?.authz_scope_hash || '';
                    const previousRole = this.user?.role || '';
                    const previousProjects = JSON.stringify(this.user?.assigned_projects || []);
                    this.user = await res.json();
                    this.armAuthzDeadline(this.user);
                    sessionStorage.setItem('auth_user', JSON.stringify(this.user));
                    const nextProjects = JSON.stringify(this.user?.assigned_projects || []);
                    if (
                        previousScopeHash &&
                        (
                            previousScopeHash !== (this.user?.authz_scope_hash || '') ||
                            previousRole !== (this.user?.role || '') ||
                            previousProjects !== nextProjects
                        )
                    ) {
                        window.dispatchEvent(new CustomEvent('authzChanged', {
                            detail: { previousScopeHash, user: this.user },
                        }));
                    }
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
            void this.logout(true);
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
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Session-Mode': 'cookie'
                },
                body: formData
            });

            if (!response.ok) {
                if (response.status === 401) {
                    throw new Error('Sai tài khoản hoặc mật khẩu');
                }
                throw new Error('Lỗi đăng nhập. Vui lòng thử lại.');
            }

            this.token = window.authSession.getToken();

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

    async logout(redirect = true) {
        if (this.token) {
            try {
                const response = await fetch('/api/auth/logout', { method: 'POST', cache: 'no-store' });
                if (!response.ok && response.status !== 401) throw new Error(`HTTP ${response.status}`);
            } catch (error) {
                console.warn('[AUTH] Logout could not revoke server session:', error);
                alert('Chưa thể đăng xuất. Vui lòng thử lại khi kết nối ổn định.');
                return false;
            }
        }
        if (this.tokenCheckInterval) clearInterval(this.tokenCheckInterval);
        if (this.authzDeadlineTimer) clearTimeout(this.authzDeadlineTimer);
        this.tokenCheckInterval = null;
        this.authzDeadlineTimer = null;
        this.authzDeadlineAt = 0;
        this.authzLocked = false;
        document.documentElement.removeAttribute('data-authz-lock');
        this.token = null;
        this.user = null;
        window.authSession.clearToken();
        sessionStorage.removeItem('justLoggedIn');
        sessionStorage.removeItem('loginReturnView');
        sessionStorage.removeItem('kicked_alert_shown');
        window.revokeAuthenticatedBlobUrls?.();
        window.dispatchEvent(new CustomEvent('authzExpired'));
        if (redirect) window.location.href = '/';
        return true;
    }

    async openSessions() {
        let dialog = document.getElementById('session-manager-dialog');
        if (!dialog) {
            dialog = document.createElement('dialog');
            dialog.id = 'session-manager-dialog';
            dialog.className = 'session-manager-dialog';
            dialog.setAttribute('aria-labelledby', 'session-manager-title');
            dialog.innerHTML = `<div class="session-manager-head"><div><span class="session-manager-kicker">Bảo mật tài khoản</span><h2 id="session-manager-title">Phiên đăng nhập</h2></div><button type="button" data-close aria-label="Đóng">×</button></div><p>Kiểm tra các thiết bị đang đăng nhập và kết thúc phiên không còn sử dụng.</p><div id="session-manager-status" role="status" aria-live="polite"></div><ul id="session-manager-list" aria-label="Các phiên đăng nhập"></ul><div class="session-manager-actions"><button type="button" data-revoke-others>Đăng xuất thiết bị khác</button><button type="button" data-logout>Đăng xuất thiết bị này</button></div>`;
            document.body.appendChild(dialog);
            dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
            dialog.querySelector('[data-logout]').addEventListener('click', () => void this.logout());
            dialog.querySelector('[data-revoke-others]').addEventListener('click', async () => {
                const button = dialog.querySelector('[data-revoke-others]');
                button.disabled = true;
                try {
                    const response = await fetch('/api/auth/sessions/revoke-others', { method: 'POST' });
                    if (!response.ok) throw new Error('Không thể kết thúc phiên khác.');
                    await this.loadSessions(dialog);
                } catch (error) { dialog.querySelector('#session-manager-status').textContent = error.message; }
                finally { button.disabled = false; }
            });
            dialog.addEventListener('close', () => this._sessionDialogOpener?.focus({ preventScroll: true }));
        }
        this._sessionDialogOpener = document.activeElement;
        if (!dialog.open) dialog.showModal();
        await this.loadSessions(dialog);
    }

    async loadSessions(dialog) {
        const list = dialog.querySelector('#session-manager-list');
        const status = dialog.querySelector('#session-manager-status');
        list.replaceChildren();
        list.setAttribute('aria-busy', 'true');
        status.textContent = 'Đang tải phiên đăng nhập…';
        try {
            const response = await fetch('/api/auth/sessions', { cache: 'no-store' });
            if (!response.ok) throw new Error('Không thể tải danh sách phiên. Vui lòng thử lại.');
            const sessions = await response.json();
            status.textContent = `${sessions.length} phiên đang hoạt động`;
            for (const session of sessions) {
                const row = document.createElement('li');
                const info = document.createElement('div');
                const title = document.createElement('strong');
                title.textContent = session.current ? 'Thiết bị này' : 'Thiết bị khác';
                const meta = document.createElement('small');
                const date = session.last_seen ? new Date(session.last_seen * 1000).toLocaleString('vi-VN') : 'Chưa rõ';
                meta.textContent = `${session.client || 'Trình duyệt'} · Hoạt động ${date}`;
                info.append(title, meta);
                row.append(info);
                if (!session.current) {
                    const end = document.createElement('button');
                    end.type = 'button'; end.textContent = 'Kết thúc';
                    end.setAttribute('aria-label', `Kết thúc phiên ${session.client || 'thiết bị khác'}`);
                    end.addEventListener('click', async () => {
                        end.disabled = true;
                        try {
                            const result = await fetch(`/api/auth/sessions/${encodeURIComponent(session.id)}`, { method: 'DELETE' });
                            if (!result.ok) throw new Error('Không thể kết thúc phiên.');
                            await this.loadSessions(dialog);
                        } catch (error) { status.textContent = error.message; end.disabled = false; }
                    });
                    row.append(end);
                }
                list.append(row);
            }
        } catch (error) {
            status.textContent = error.message;
            const retry = document.createElement('button');
            retry.type = 'button'; retry.textContent = 'Thử lại';
            retry.addEventListener('click', () => void this.loadSessions(dialog));
            list.append(retry);
        } finally { list.removeAttribute('aria-busy'); }
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
            const icon = document.createElement('i');
            icon.className = 'bi bi-person-check me-1';
            icon.setAttribute('aria-hidden', 'true');
            authBtn.replaceChildren(icon, document.createTextNode(this.user.username));
            authBtn.classList.remove('btn-primary');
            authBtn.classList.add('btn-outline-danger');
            authBtn.onclick = (e) => {
                e.preventDefault();
                void this.openSessions();
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

            const simulationBtn = document.getElementById('btn-digital-twin');
            if (simulationBtn) simulationBtn.style.display = this.user.role === 'admin' ? 'inline-flex' : 'none';

            // Show data analysis buttons for authenticated users (viewer, admin, operator)
            const btnLongTerm = document.getElementById('btn-long-term');
            if (btnLongTerm) {
                btnLongTerm.classList.remove('d-none');
                console.log('✅ [AUTH] Map: Data analysis buttons shown');
            }

        } else {
            console.log('ℹ️ [AUTH] Not authenticated');

            // Reset auth button
            authBtn.innerHTML = '<i class="bi bi-box-arrow-in-right me-1"></i> <span>Đăng nhập</span>';
            authBtn.classList.add('btn-primary');
            authBtn.classList.remove('btn-outline-danger');
            authBtn.onclick = () => {
                const currentPath = window.location.pathname;
                const returnTo = currentPath === '/management' || currentPath === '/admin' ? '/management' : '/map';
                window.location.href = `/login?return_to=${encodeURIComponent(returnTo)}`;
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

            const simulationBtn = document.getElementById('btn-digital-twin');
            if (simulationBtn) simulationBtn.style.display = 'none';

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
            const returnTo = redirectUrl.startsWith('/') ? redirectUrl : window.location.pathname;
            window.location.href = `/login?return_to=${encodeURIComponent(returnTo)}`;
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
            window.location.href = `/login?return_to=${encodeURIComponent(window.location.pathname)}`;
            return;
        }
        if (this.enforceAuthzDeadline()) {
            throw new Error('AUTHZ_GRACE_EXPIRED');
        }

        const headers = {
            ...options.headers,
            'Authorization': `Bearer ${this.token}`
        };

        const response = await fetch(url, { ...options, headers, cache: options.cache || 'no-store' });

        if (response.status === 401) {
            void this.handleUnauthorizedResponse(url);
        }

        return response;
    }
}

window.revokeAuthenticatedBlobUrls = function () {
    authenticatedBlobUrls.forEach(url => URL.revokeObjectURL(url));
    authenticatedBlobUrls.clear();
};

window.fetchAuthenticatedBlobUrl = async function (url) {
    const safeUrl = String(url || '').trim();
    if (!safeUrl.startsWith('/api/admin/')) {
        throw new Error('Refusing to fetch a non-admin protected asset');
    }
    if (authenticatedBlobUrls.has(safeUrl)) return authenticatedBlobUrls.get(safeUrl);
    const response = await window.authManager.apiFetch(safeUrl, { cache: 'no-store' });
    if (!response?.ok) throw new Error(`Protected asset HTTP ${response?.status || 0}`);
    const objectUrl = URL.createObjectURL(await response.blob());
    if (authenticatedBlobUrls.size >= 128) {
        const [oldestKey, oldestUrl] = authenticatedBlobUrls.entries().next().value;
        URL.revokeObjectURL(oldestUrl);
        authenticatedBlobUrls.delete(oldestKey);
    }
    authenticatedBlobUrls.set(safeUrl, objectUrl);
    return objectUrl;
};

window.hydrateAuthenticatedImages = async function (root = document) {
    const images = Array.from(root.querySelectorAll?.('img[data-auth-src]') || []);
    await Promise.all(images.map(async image => {
        if (image.dataset.authLoaded === 'true') return;
        image.dataset.authLoaded = 'pending';
        try {
            image.src = await window.fetchAuthenticatedBlobUrl(image.dataset.authSrc);
            image.dataset.authLoaded = 'true';
        } catch (error) {
            image.dataset.authLoaded = 'error';
            image.alt = 'Không tải được ảnh bảo mật';
            console.warn('[AUTH] Protected image unavailable:', error);
        }
    }));
};

window.downloadAuthenticatedFile = async function (url, fallbackName) {
    let safeUrl = String(url || '').trim();
    // Auto-rewrite legacy /static/adjustments/ URLs from older DB records.
    if (safeUrl.startsWith('/static/adjustments/')) {
        const filename = safeUrl.slice('/static/adjustments/'.length);
        const idMatch = filename.match(/^gnss_(?:binh_sai|adjustment)_(\d+)_/);
        if (idMatch) {
            safeUrl = `/api/admin/gnss/adjustment/reports/${idMatch[1]}/${filename}`;
            console.info('[Download] Chuyển URL cũ →', safeUrl);
        }
    }
    if (!safeUrl.startsWith('/api/admin/') || safeUrl.startsWith('//')) {
        throw new Error('Refusing to download a non-admin protected asset');
    }
    const response = await window.authManager.apiFetch(safeUrl, { cache: 'no-store' });
    if (!response?.ok) {
        let detail = '';
        let data = null;
        try {
            data = await response.json();
            const value = data?.detail || data?.message || '';
            detail = typeof value === 'string' ? value : JSON.stringify(value);
        } catch (_) {
            try {
                detail = await response.text();
            } catch (_) {}
        }
        const phase = data?.phase_label || response.headers?.get('X-Operation-Phase');
        const phaseCode = data?.phase && data.phase !== phase ? ` (${data.phase})` : '';
        const requestId = data?.request_id || response.headers?.get('X-Request-ID');
        if (phase) detail += `${detail ? ' · ' : ''}Giai đoạn: ${phase}${phaseCode}`;
        if (requestId) detail += `${detail ? ' · ' : ''}Mã yêu cầu: ${requestId}`;
        const errorMsg = detail ? `HTTP ${response?.status || 0}: ${detail}` : `Download HTTP ${response?.status || 0}`;
        console.error(`[Download] Thất bại khi tải file từ ${safeUrl}:`, errorMsg, response);
        throw new Error(errorMsg);
    }
    const blobUrl = URL.createObjectURL(await response.blob());
    try {
        const disposition = response.headers.get('content-disposition') || '';
        const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
        const plainName = disposition.match(/filename="?([^";]+)"?/i)?.[1];
        const anchor = document.createElement('a');
        anchor.href = blobUrl;
        anchor.download = encodedName
            ? decodeURIComponent(encodedName)
            : (plainName || fallbackName || 'download');
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
    } finally {
        setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
    }
};

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
    window.dispatchEvent(new CustomEvent('auth:ready', { detail: window.authManager.getUserInfo?.() || null }));

    // ✅ Retry with delays (handle timing issues)
    setTimeout(() => window.authManager.updateAuthUI(), 100);
    setTimeout(() => window.authManager.updateAuthUI(), 300);
};

// Run on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { void initAuthUI(); });
} else {
    void initAuthUI();
}

console.log('✅ [AUTH] AuthManager loaded');
