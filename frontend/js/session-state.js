(() => {
    'use strict';

    if (window.authSession) return;

    const TOKEN_KEY = 'token';
    const REMEMBER_KEY = 'rememberMe';
    const USER_KEY = 'auth_user';

    function getToken() {
        // A tab-scoped login is always the most recent explicit choice.
        return sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY);
    }

    function storeToken(token, remember = false) {
        if (!token) return;
        if (remember) {
            localStorage.setItem(TOKEN_KEY, token);
            localStorage.setItem(REMEMBER_KEY, 'true');
            sessionStorage.removeItem(TOKEN_KEY);
        } else {
            sessionStorage.setItem(TOKEN_KEY, token);
            localStorage.removeItem(TOKEN_KEY);
            localStorage.removeItem(REMEMBER_KEY);
        }
        sessionStorage.removeItem(USER_KEY);
    }

    function clearToken(expectedToken = null) {
        if (!expectedToken || sessionStorage.getItem(TOKEN_KEY) === expectedToken) {
            sessionStorage.removeItem(TOKEN_KEY);
        }
        if (!expectedToken || localStorage.getItem(TOKEN_KEY) === expectedToken) {
            localStorage.removeItem(TOKEN_KEY);
            localStorage.removeItem(REMEMBER_KEY);
        }
        sessionStorage.removeItem(USER_KEY);
    }

    async function inspect({ timeout = 10000 } = {}) {
        const token = getToken();
        if (!token) return { status: 'anonymous', token: null, user: null };

        try {
            const response = await fetch('/api/auth/me', {
                headers: { Authorization: `Bearer ${token}` },
                signal: AbortSignal.timeout(timeout),
                cache: 'no-store',
            });
            if (response.ok) {
                const user = await response.json();
                sessionStorage.setItem(USER_KEY, JSON.stringify(user));
                return { status: 'authenticated', token, user };
            }
            if (response.status === 401 || response.status === 403) {
                clearToken(token);
                return { status: 'anonymous', token: null, user: null };
            }
            return { status: 'unavailable', token, user: null };
        } catch (_) {
            return { status: 'unavailable', token, user: null };
        }
    }

    window.authSession = Object.freeze({ getToken, storeToken, clearToken, inspect });
})();
