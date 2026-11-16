/* Shared bounded HTTP client for new UI code; existing authManager stays compatible. */
(() => {
    const active = new Map();
    const token = () => window.authSession?.getToken() || null;
    const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

    function computeDelay(attempt) {
        const jitter = (window.crypto?.getRandomValues ? window.crypto.getRandomValues(new Uint32Array(1))[0] / 4294967296 : 0.5) * 150;
        return 250 * (2 ** attempt) + jitter;
    }

    function prepareHeaders(customHeaders) {
        const headers = new Headers(customHeaders || {});
        const authToken = token();
        if (authToken && !headers.has('Authorization')) {
            headers.set('Authorization', `Bearer ${authToken}`);
        }
        return headers;
    }

    function shouldRetry(response, attempt, attempts) {
        if (response.status === 401) {
            window.dispatchEvent(new CustomEvent('auth:required'));
        }
        if (response.ok || attempt === attempts - 1) {
            return false;
        }
        return response.status === 429 || response.status === 503;
    }

    async function executeFetch(url, requestConfig, attempt, attempts) {
        try {
            const response = await fetch(url, requestConfig);
            if (!shouldRetry(response, attempt, attempts)) {
                return { done: true, response };
            }
        } catch (error) {
            if (attempt === attempts - 1 || requestConfig.signal?.aborted) {
                throw error;
            }
        }
        return { done: false };
    }

    window.apiClient = async function apiClient(url, options = {}) {
        const method = (options.method || 'GET').toUpperCase();
        const key = options.requestKey;
        if (key) active.get(key)?.abort();
        const controller = new AbortController();
        if (key) active.set(key, controller);
        const timeout = setTimeout(() => controller.abort(new DOMException('Timeout', 'TimeoutError')), options.timeout || 15000);
        const headers = prepareHeaders(options.headers);
        const attempts = method === 'GET' ? Math.max(1, Math.min(options.attempts || 2, 3)) : 1;
        const requestConfig = { ...options, method, headers, signal: controller.signal };

        async function runAttempt(attempt) {
            const result = await executeFetch(url, requestConfig, attempt, attempts);
            if (result.done) return result.response;
            await sleep(computeDelay(attempt));
            return runAttempt(attempt + 1);
        }

        try {
            return await runAttempt(0);
        } finally {
            clearTimeout(timeout);
            if (key && active.get(key) === controller) active.delete(key);
        }
    };
})();
