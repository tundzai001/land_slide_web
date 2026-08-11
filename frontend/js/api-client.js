/* Shared bounded HTTP client for new UI code; existing authManager stays compatible. */
(() => {
    const active = new Map();
    const token = () => sessionStorage.getItem('token') || localStorage.getItem('token');
    const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
    window.apiClient = async function apiClient(url, options = {}) {
        const method = (options.method || 'GET').toUpperCase();
        const key = options.requestKey;
        if (key) active.get(key)?.abort();
        const controller = new AbortController();
        if (key) active.set(key, controller);
        const timeout = setTimeout(() => controller.abort(new DOMException('Timeout', 'TimeoutError')), options.timeout || 15000);
        const headers = new Headers(options.headers || {});
        if (token() && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token()}`);
        const attempts = method === 'GET' ? Math.max(1, Math.min(options.attempts || 2, 3)) : 1;
        try {
            for (let attempt = 0; attempt < attempts; attempt += 1) {
                try {
                    const response = await fetch(url, {...options, method, headers, signal: controller.signal});
                    if (response.status === 401) window.dispatchEvent(new CustomEvent('auth:required'));
                    if (response.ok || ![429, 503].includes(response.status) || attempt === attempts - 1) return response;
                } catch (error) {
                    if (attempt === attempts - 1 || controller.signal.aborted) throw error;
                }
                await sleep(250 * (2 ** attempt) + Math.random() * 150);
            }
        } finally {
            clearTimeout(timeout);
            if (key && active.get(key) === controller) active.delete(key);
        }
    };
})();
