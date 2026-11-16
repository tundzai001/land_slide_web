(() => {
    'use strict';
    if (window.authSession) return;

    // This marker is only a compatibility signal for legacy UI controllers.
    // The signed credential is in an HttpOnly cookie and never enters JavaScript.
    const marker = 'browser-session';
    const csrfNames = ['__Host-monitoring_csrf', 'monitoring_csrf'];
    const legacyKeys = ['token', 'rememberMe', 'auth_user'];
    for (const key of legacyKeys) {
        localStorage.removeItem(key);
        if (key !== 'auth_user') sessionStorage.removeItem(key);
    }

    function csrf() {
        for (const name of csrfNames) {
            const value = document.cookie.split('; ').find(part => part.startsWith(`${name}=`));
            if (value) return decodeURIComponent(value.slice(name.length + 1));
        }
        return null;
    }
    function getToken() { return csrf() ? marker : null; }
    function storeToken() { /* Server sets HttpOnly session and readable CSRF cookies. */ }
    function clearToken() {
        for (const key of legacyKeys) {
            localStorage.removeItem(key);
            sessionStorage.removeItem(key);
        }
        for (const name of csrfNames) document.cookie = `${name}=; Max-Age=0; Path=/; SameSite=Lax`;
    }
    async function inspect({ timeout = 10000 } = {}) {
        try {
            const response = await fetch('/api/auth/me', {
                signal: AbortSignal.timeout(timeout), cache: 'no-store', credentials: 'same-origin',
            });
            if (response.ok) {
                const user = await response.json();
                sessionStorage.setItem('auth_user', JSON.stringify(user));
                return { status: 'authenticated', token: marker, user };
            }
            if (response.status === 401 || response.status === 403) {
                clearToken();
                return { status: 'anonymous', token: null, user: null };
            }
            return { status: 'unavailable', token: getToken(), user: null };
        } catch (err) {
            console.debug('[SESSION] Validation unavailable:', err);
            return { status: 'unavailable', token: getToken(), user: null };
        }
    }

    const rawFetch = window.fetch.bind(window);
    window.fetch = function (input, options = {}) {
        let rawUrl = input?.url;
        if (input instanceof URL) {
            rawUrl = input.href;
        } else if (typeof input === 'string') {
            rawUrl = input;
        }
        const url = new URL(rawUrl, location.href);
        const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
        if (headers.get('Authorization') === `Bearer ${marker}`) headers.delete('Authorization');
        const method = String(options.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
        if (url.origin === location.origin && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
            const value = csrf();
            if (value) headers.set('X-CSRF-Token', value);
        }
        return rawFetch(input, { ...options, headers, credentials: url.origin === location.origin ? 'same-origin' : options.credentials });
    };
    window.authSession = Object.freeze({ getToken, storeToken, clearToken, inspect });
})();
